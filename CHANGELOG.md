# Changelog

## Unreleased - 2026-11-05

- Documented runnable local checks, 60 multilingual evaluation scenarios, and measured limitations.
- Added HTTP and concurrency regression tests; protected untrusted session memory and anonymous rate-limit identity.
- Added process-local, content-free provider timing, error, and token aggregates.
- Refreshed Gradio and the hashed dependency lock; the audit still reports Pillow findings and blocks the release gate.

## 0.2.0 - 2026-08-26

- Split configuration, core logic, providers, safety, security, service, and web runtime into dedicated modules.
- Upgraded Gradio to 6.16.0 and added a hash-pinned transitive dependency lock.
- Added fail-closed production authentication and trusted-host validation.
- Added FastAPI/Uvicorn runtime, liveness endpoint, security headers, and safe proxy configuration.
- Added request, queue, concurrency, input, output, session, and provider-response bounds.
- Added multilingual deterministic safety guidance for English, Albanian, and German.
- Disabled the public Gradio API surface, monitoring, MCP, persistence, analytics, file transfer, and feedback storage.
- Added Ruff, Bandit, dependency auditing, immutable CI action SHAs, Dependabot, and production/security documentation.

