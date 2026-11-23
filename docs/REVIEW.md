# Engineering review — 2026-11-23

## Architecture and tradeoffs

Browser → FastAPI session authentication and CSRF checks → identity limiter and
bounded concurrency → service validation and local safety rules → redacted,
bounded history → OpenAI or Ollama adapter. FastAPI also supplies liveness,
trusted-host checks, login throttling and browser headers. The server owns each
session's history; clients cannot submit another session's conversation as history.
Untrusted memory is now a user message, never a system instruction. This reduces
instruction privilege but does not prove resistance to model prompt injection.

The anonymous limiter uses the client address rather than a user-controlled session
identifier. Users behind one NAT share a limit. Authenticated users sharing one
account also share a limit. Capacity eviction can weaken limits under identity
churn: enforce an outer gateway limit before exposing the service.

## Observability

`it_support.metrics.snapshot()` returns thread-safe process aggregates for each
provider: calls, errors, total adapter seconds, reported input/output tokens and
observation counts. It stores no prompts, responses, identities, URLs or credentials.
Counters reset on restart and are intentionally not exposed on a public endpoint.
Latency excludes queue wait and local safety responses; client creation errors are
outside adapter metrics. These are operational building blocks, not full monitoring.
Neither adapter supplies billed currency: cost is unknown, not zero. Token counts
must not be presented as a bill; cached tokens and account pricing affect charges.
Uvicorn access logging is disabled because request paths/queries can contain private
data. Review reverse-proxy and provider SDK logging separately.

## Evaluation

`python -m evals.run` runs 60 synthetic scenarios: 20 per language, covering
troubleshooting, ambiguity, injection, security and escalation. The checked-in
`evals/results.json` reports 60/60 offline contracts passing. These checks validate
message role, provider routing and deterministic escalation only; they do not grade
troubleshooting quality, refusal behavior or actual model language adherence.

`python -m evals.run --live --output evals/live-results.local.json` explicitly calls
the configured provider and can incur charges. Set provider environment variables
first; this runner does not load `.env`. Never use real private tickets. Each live
response needs human grading against its scenario criterion: pass only if every
criterion is met, with no unsafe instruction, secret request or invented action.
Report scores per language/category and model/version; any safety violation blocks
release. No real-model evaluation was performed in this review.

## Verification evidence and gaps

- Windows, Python 3.12 and 3.13: 54 unittest tests passed per version after a
  hashed-lock install. Coverage includes HTTP login/CSRF, login throttling,
  concurrent and canceled requests, redaction, session isolation, provider failure
  and token accounting. Python 3.11 clean-install validation remains for CI.
- Ruff passed; Bandit passed with an existing unmatched B104 suppression warning.
- Python compilation, dependency compatibility (`pip check`) and a wheel build
  passed. The wheel contains all three browser assets.
- The local dependency audit on 2026-11-23 found zero known vulnerabilities in the
  23 locked packages; see `evals/dependency-audit-summary.json`. The previous
  Gradio-based lock had 39 Pillow findings. Removing Gradio/Pillow removed those
  packages and their unused image-processing surface. A clean audit reflects the
  database at scan time; continue the scheduled CI audit for new advisories.
- The local app returned `200` from `/`, `/healthz` and `/api/session`. One
  end-to-end HTTP request to the locally installed Ollama `llama3.2` model also
  returned `200` with a troubleshooting answer in 69.6 seconds. This is a smoke
  check, not a quality or throughput evaluation.
- The previously published [test run](https://github.com/DijarBacaj/IT-Support-Chatbot/actions/runs/42050325102)
  passed and [audit run](https://github.com/DijarBacaj/IT-Support-Chatbot/actions/runs/42050324764)
  failed before this dependency change. New GitHub CI results must be checked after
  publishing this revision.
- Browser visual interaction, real-model quality, load limits and production
  readiness remain unverified. HTTP integration tests exercise the request boundary.

## Installation, upgrade and rollback

Follow README and PRODUCTION for a clean virtual environment and hashed install.
Use one worker/process. Sessions, counters and limits are memory-only; adding workers
requires shared identity/limits and queue/session routing, not just a worker flag.

For an upgrade, preserve the previous release commit, lock, environment and service
configuration. Build a separate release directory/virtual environment, run tests,
audit, `--check`, live evaluation and authenticated smoke tests. Stop intake and
allow in-flight requests to drain within provider timeout before switching the
service path. Restart once and verify login, health and a safe support request.
Sessions are lost on restart; inform users. Do not reuse an environment with mixed
old/new dependencies.

For rollback, stop the new process and switch the service path to the preserved
previous release and its environment, restore compatible configuration, restart and
repeat the same smoke checks. There is no application database migration. Rollback
does not reverse actions users took following model advice. Never roll back to a
known vulnerable release without an explicit incident decision.
