# IT Support Chatbot

[![Tests and code quality](https://github.com/DijarBacaj/IT-Support-Chatbot/actions/workflows/tests.yml/badge.svg)](https://github.com/DijarBacaj/IT-Support-Chatbot/actions/workflows/tests.yml)
[![Dependency audit](https://github.com/DijarBacaj/IT-Support-Chatbot/actions/workflows/dependency-audit.yml/badge.svg)](https://github.com/DijarBacaj/IT-Support-Chatbot/actions/workflows/dependency-audit.yml)
![Python](https://img.shields.io/badge/Python-3.11%E2%80%933.13-3776AB?logo=python&logoColor=white)

A multilingual IT support assistant with **OpenAI and Ollama**, a Gradio chat interface, and a FastAPI runtime. It helps users work through everyday technical issues while keeping credentials out of model requests and directing high-risk incidents to a human.

The engineering focus is on testable behavior: provider adapters, bounded conversation context, authentication, request limits, sanitized failures, and evaluation scenarios in **English, Albanian, and German**.

[Try it locally](#run-locally) · [Run the tests](#verify-it-yourself) · [Architecture](#architecture) · [Deployment guide](docs/PRODUCTION.md) · [Engineering review](docs/REVIEW.md)

## What it does

- Troubleshoots common Wi-Fi, VPN, email, printer, and device problems using the selected model.
- Preserves recent context within the conversation, with a **Reset memory** command.
- Redacts common secrets and email addresses from the current request and history before calling a provider.
- Adds deterministic escalation guidance for detected physical danger, malware, account compromise, data loss, and broad outages. Physical-danger cases bypass the model.
- Supports authenticated access, per-identity request limits, login throttling, a bounded queue, and concurrency limits.
- Tracks provider latency, errors, and reported token usage through content-free, in-process metrics.

This project provides guidance. It cannot execute fixes, open tickets, or verify that an incident has been resolved.

## Run locally

Use **Python 3.11–3.13**. Choose either a running Ollama installation with a downloaded model or an OpenAI API key. Installing dependencies and downloading a model require internet access; the offline tests below do not call either provider.

### 1. Install

<details open>
<summary>Windows PowerShell</summary>

```powershell
git clone https://github.com/DijarBacaj/IT-Support-Chatbot.git
cd IT-Support-Chatbot
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --require-hashes -r requirements.lock
Copy-Item .env.example .env
```

</details>

<details>
<summary>Linux / macOS</summary>

```bash
git clone https://github.com/DijarBacaj/IT-Support-Chatbot.git
cd IT-Support-Chatbot
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --require-hashes -r requirements.lock
cp .env.example .env
```

</details>

### 2. Choose a provider

**Ollama — local model, no OpenAI key**

Start Ollama and download the model:

```text
ollama pull llama3.2
```

Set these values in `.env`:

```dotenv
AI_PROVIDER=ollama
OLLAMA_BASE_URL=http://127.0.0.1:11434
OLLAMA_MODEL=llama3.2
```

**OpenAI — hosted model**

Set these values in `.env`, replacing the placeholder with your own key:

```dotenv
AI_PROVIDER=openai
OPENAI_API_KEY=your_real_api_key
OPENAI_MODEL=gpt-4o-mini
```

OpenAI requests can incur charges. Never commit your `.env` file. With `AI_PROVIDER=auto`, the application selects OpenAI when a non-placeholder key is present and otherwise selects Ollama.

### 3. Check and start

```text
python it_support_agent.py --check
python it_support_agent.py
```

Open [http://127.0.0.1:7860](http://127.0.0.1:7860). Stop the server with `Ctrl+C`.

`--check` validates application and provider settings. For Ollama it also checks connectivity and model availability. For OpenAI it checks configuration without making a model request.

## Example interaction

**User**

> My Windows 11 laptop connects to Wi-Fi but has no internet. Other devices work, and I already restarted the laptop.

**Illustrative response structure — actual model output varies**

> Since other devices work, start with checks on this laptop. Confirm whether all websites fail or only one application. Check whether a VPN is connected, then compare access with the VPN disconnected if your company policy allows it. Note the exact error before changing network settings. If the issue persists, share the error and whether another trusted network works with your IT team.

For a deterministic safety example, enter **“My laptop has smoke and sparks.”** The application returns immediate safety and escalation guidance without sending the message to a model.

## Verify it yourself

After installing the runtime dependencies, run:

```text
python -m unittest -v
python -m evals.run
```

**No API key, running model, or provider network access is required.** The suite uses provider test doubles and exercises HTTP authentication, login throttling, secret redaction, history isolation, provider failures, token accounting, and concurrent requests. It also checks UI defaults and deployment configuration.

The evaluation runner writes `evals/results.json`. Its 60 scenarios cover:

| Category | Scenarios | What to inspect |
| --- | ---: | --- |
| Troubleshooting | 12 | Relevant, reversible steps and an actionable checklist |
| Ambiguous requests | 12 | Targeted clarification without an invented diagnosis |
| Prompt injection | 12 | Untrusted instructions do not expose prompts or credentials |
| Security incidents | 12 | Containment, human escalation, and no credential requests |
| Human escalation | 12 | Appropriate urgency and local physical-danger handling |

Each category includes four scenarios per language. The **offline result checks deterministic contracts**, including message roles and localized escalation. It does not measure whether a real model follows the troubleshooting or refusal criteria. See [the scenarios](evals/scenarios.json) and [evaluation methodology](docs/REVIEW.md#evaluation).

### Quality and security checks

```text
python -m pip install -r requirements-dev.txt
python -m ruff check .
python -m bandit -c pyproject.toml -r it_support it_support_agent.py run_ollama_agent.py
python -m pip_audit -r requirements.lock
```

[GitHub Actions](https://github.com/DijarBacaj/IT-Support-Chatbot/actions/workflows/tests.yml) runs the Python 3.11–3.13 test matrix, linting, static security analysis, compilation, and wheel build. A [separate scheduled dependency audit](https://github.com/DijarBacaj/IT-Support-Chatbot/actions/workflows/dependency-audit.yml) tracks the unresolved Pillow findings. Both badges show their actual run status. See [the engineering review](docs/REVIEW.md#verification-evidence-and-gaps) for measured results and limitations.

### Real-model evaluation — optional

Set provider variables in your shell, then run:

```text
python -m evals.run --live --output evals/live-results.local.json
```

The evaluation runner does not load `.env`. This command contacts the selected provider and may incur charges. It saves responses from the synthetic scenarios for human review against each scenario's acceptance criterion. Live results remain unreviewed until a person grades them; passing offline checks does not establish model quality.

## Architecture

```text
Browser
  → Gradio authentication and bounded queue
  → Identity-based request limiter
  → Service: validation, local safety rules, sanitized errors
  → Prompt builder: redacted history and untrusted session memory
  → OpenAI adapter / Ollama adapter
```

FastAPI wraps the interface with trusted-host validation, login throttling, browser security headers, and `GET /healthz`. The liveness response is `{"status":"ok"}`; it does not probe a provider or expose configuration.

| Module | Responsibility |
| --- | --- |
| [`config.py`](it_support/config.py) | Environment settings and startup validation |
| [`core.py`](it_support/core.py) | Prompt construction, recent history, and reset behavior |
| [`safety.py`](it_support/safety.py) | Language detection and deterministic escalation rules |
| [`security.py`](it_support/security.py) | Redaction, authentication, rate limits, and headers |
| [`providers.py`](it_support/providers.py) | OpenAI/Ollama requests and readiness checks |
| [`service.py`](it_support/service.py) | Request orchestration and safe failure responses |
| [`metrics.py`](it_support/metrics.py) | Thread-safe aggregate latency, errors, and token counts |
| [`web.py`](it_support/web.py) | Gradio interface and FastAPI/Uvicorn runtime |

The CLI remains in `it_support_agent.py`; `run_ollama_agent.py` provides an Ollama-oriented entry point. Tests live in `test_it_support_agent.py` and `test_regressions.py`.

## Privacy and deployment

Chat history is not written to disk by the application. The browser, active process, and selected provider temporarily process the conversation. Redaction is best-effort: do not submit passwords, MFA codes, private keys, or unnecessary personal data. OpenAI requests use `store=False`; provider-side handling still depends on the provider's policies and your account settings.

Production or non-local bindings require credentials and an explicit host allowlist. Remote Ollama requires HTTPS and an explicit opt-in. Deploy behind a trusted TLS proxy with an outer request limit, using **one application process**. Session state, limits, and metrics are process-local and reset on restart.

See [configuration reference](docs/CONFIGURATION.md), [deployment and operations](docs/PRODUCTION.md), [upgrade and rollback](docs/REVIEW.md#installation-upgrade-and-rollback), and [security policy](SECURITY.md).

## Known limitations

- Model answers can be incorrect. Destructive actions and security incidents require review by a trained person.
- Keyword-based language and risk detection can miss paraphrases or flag harmless text. Prompt-injection defenses do not guarantee model compliance.
- Full browser/Gradio queue testing and real-model quality evaluation remain separate validation work. Read the engineering review before making deployment decisions.
- Multiple workers need shared rate limiting and a session-routing design. Shared accounts and clients behind one address can share limits.
- Metrics contain aggregate token usage when available. They do not provide billed currency, durable monitoring, or queue-wait latency.
- There is no persistent ticket store, SSO integration, file upload, role management, or SLA workflow.
- No software license has been selected. A license decision is needed before granting reuse rights.
