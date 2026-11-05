"""Evaluate offline contracts, or collect live responses for separate human review.

python -m evals.run
python -m evals.run --live --output evals/live-results.local.json

Offline mode needs no key, Ollama server or network connection. Live mode uses the
current provider environment (not .env) and can incur charges. Automatic checks do
not grade model correctness, safe refusal or troubleshooting quality.
"""

import argparse
import hashlib
import json
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from it_support.config import (
    get_model_name,
    get_ollama_model_name,
    get_provider_setting,
    has_openai_api_key,
    is_supported_provider,
    resolve_provider,
)
from it_support.core import build_messages
from it_support.metrics import snapshot
from it_support.safety import HEADINGS, detect_risk_flags
from it_support.security import safe_config_value
from it_support.service import chat

SCENARIOS_PATH = Path(__file__).with_name("scenarios.json")
OFFLINE_RESULTS_PATH = Path(__file__).with_name("results.json")


def _offline_response(prompt, physical_danger):
    # Clear inherited provider/input-limit settings so anyone gets the same run.
    with (
        patch.dict("os.environ", {"AI_PROVIDER": "ollama"}, clear=True),
        patch(
            "it_support.service.ask_ollama_agent", return_value="Offline provider fixture."
        ) as provider,
        patch(
            "it_support.service.ask_it_agent", side_effect=AssertionError("Unexpected OpenAI call")
        ),
    ):
        response = chat(prompt, [])
        expected_calls = 0 if physical_danger else 1
        routing_ok = provider.call_count == expected_calls
    return response, routing_ok


def _live_configuration():
    if not is_supported_provider(get_provider_setting()):
        raise ValueError("Set AI_PROVIDER to auto, openai or ollama before a live run.")
    provider = resolve_provider()
    if provider == "openai" and not has_openai_api_key():
        raise ValueError("Set a non-placeholder OPENAI_API_KEY before a live OpenAI run.")
    model = get_model_name() if provider == "openai" else get_ollama_model_name()
    return provider, safe_config_value(model)


def run(live=False):
    source = SCENARIOS_PATH.read_bytes()
    cases = json.loads(source)
    results = []
    provider, model = _live_configuration() if live else ("fixture", None)
    for case in cases:
        prompt = case["prompt"]
        messages = build_messages(prompt, [])
        failures = []
        checks = ["latest_issue_has_user_role"]
        if messages[-1]["role"] != "user" or prompt not in messages[-1]["content"]:
            failures.append("latest_issue_has_user_role")
        risk_flags = detect_risk_flags(prompt)
        physical_danger = "possible physical danger" in risk_flags
        if case["category"] in {"security", "escalation"}:
            checks.extend(["risk_detection", "localized_escalation"])
            if not risk_flags:
                failures.append("risk_detection")
        if live:
            before = snapshot().get(f"{provider}.errors", 0)
            started = time.perf_counter()
            response = chat(prompt, [])
            elapsed = time.perf_counter() - started
            provider_failed = snapshot().get(f"{provider}.errors", 0) > before
            if provider_failed:
                failures.append("provider_error")
        else:
            response, routing_ok = _offline_response(prompt, physical_danger)
            checks.append(
                "local_safety_bypasses_provider" if physical_danger else "provider_routing"
            )
            if not routing_ok:
                failures.append("provider_routing")
        if case["category"] in {"security", "escalation"} and not response.startswith(
            HEADINGS[case["language"]]
        ):
            failures.append("localized_escalation")
        result = {
            "id": case["id"],
            "language": case["language"],
            "category": case["category"],
            "checks": checks,
            "failures": failures,
        }
        if live:
            result.update(
                response=response,
                elapsed_seconds=round(elapsed, 4),
                human_review="pending",
                criterion=case["criterion"],
            )
        results.append(result)
    report = {
        "schema_version": 1,
        "mode": "live-unreviewed" if live else "offline-contracts",
        "scope": "Automatic application contracts only; model quality requires human review.",
        "scenarios_sha256": hashlib.sha256(source).hexdigest(),
        "provider": provider,
        "model": model,
        "total": len(results),
        "passed": sum(not row["failures"] for row in results),
        "by_language": dict(sorted(Counter(case["language"] for case in cases).items())),
        "by_category": dict(sorted(Counter(case["category"] for case in cases).items())),
        "results": results,
    }
    if live:
        report["recorded_at_utc"] = datetime.now(UTC).isoformat()
        report["human_review"] = "pending"
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    output = args.output or Path(
        "evals/live-results.local.json" if args.live else "evals/results.json"
    )
    if args.live and output.resolve() == OFFLINE_RESULTS_PATH.resolve():
        parser.error(
            "Live results must not overwrite evals/results.json; use a separate .local.json file."
        )
    try:
        report = run(args.live)
    except ValueError as exc:
        parser.error(str(exc))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{report['mode']}: {report['passed']}/{report['total']} application contracts passed")
    if args.live:
        print("Model quality is ungraded. Review every response against its criterion.")
    return int(report["passed"] != report["total"])


if __name__ == "__main__":
    raise SystemExit(main())
