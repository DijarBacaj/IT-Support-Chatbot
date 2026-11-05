# Configuration reference

Copy `.env.example` to `.env` for local use. The CLI reads the `.env` file in the project root; existing shell environment variables take precedence. Restart the application after changing configuration. Keep real secrets out of source control and use a deployment secret manager when hosting.

| Variable | Default | Purpose |
| --- | --- | --- |
| `APP_ENV` | `development` | `development`, `test`, or `production` |
| `APP_AUTH_USERNAME` | blank | Required with a production/non-local bind |
| `APP_AUTH_PASSWORD` | blank | Required with a production/non-local bind; at least 16 characters |
| `APP_ALLOWED_HOSTS` | local hosts | Comma-separated trusted HTTP Host values; explicit configuration required for production/non-local bindings |
| `APP_EXTERNAL_HTTPS` | `false` | Enables HSTS when clients access the app through HTTPS |
| `APP_ROOT_PATH` | blank | Optional reverse-proxy URL prefix |
| `FORWARDED_ALLOW_IPS` | `127.0.0.1` | Proxies trusted for forwarded client metadata |
| `AI_PROVIDER` | `auto` | `auto`, `openai`, or `ollama` |
| `OPENAI_API_KEY` | blank | OpenAI credential; never place it in tracked files |
| `OPENAI_MODEL` | `gpt-4o-mini` | OpenAI chat model |
| `OPENAI_TIMEOUT_SECONDS` | `30` | Clamped to 5–300 seconds |
| `OLLAMA_BASE_URL` | `http://127.0.0.1:11434` | Local or explicitly allowed HTTPS Ollama URL |
| `OLLAMA_MODEL` | `llama3.2` | Installed Ollama chat model |
| `OLLAMA_KEEP_ALIVE` | `5m` | Ollama model retention duration |
| `OLLAMA_TIMEOUT_SECONDS` | `120` | Clamped to 5–600 seconds |
| `ALLOW_REMOTE_OLLAMA` | `false` | Explicitly permits a remote HTTPS Ollama endpoint |
| `MAX_INPUT_CHARS` | `4000` | Per-message limit, clamped to 500–12000 |
| `MAX_RESPONSE_TOKENS` | `600` | Output limit, clamped to 128–2000 |
| `LOGIN_RATE_LIMIT_REQUESTS` | `5` | Login attempts allowed per source/window |
| `LOGIN_RATE_LIMIT_WINDOW_SECONDS` | `300` | Login-attempt window, clamped to 30–3600 seconds |
| `RATE_LIMIT_REQUESTS` | `12` | Messages allowed per identity/window |
| `RATE_LIMIT_WINDOW_SECONDS` | `60` | Sliding-window duration, clamped to 10–3600 seconds |
| `MAX_CONCURRENT_REQUESTS` | `4` | Provider calls processed concurrently, clamped to 1–32 |
| `MAX_QUEUE_SIZE` | `32` | Maximum queued calls, clamped to 1–500 |
| `STATE_SESSION_CAPACITY` | `1000` | Bound on Gradio session state, clamped to 10–10000 |
| `GRADIO_SERVER_NAME` | `127.0.0.1`; `0.0.0.0` in production | Listen address; `.env.example` explicitly selects loopback |
| `GRADIO_SERVER_PORT` | `7860` | Listen port |
| `LOG_LEVEL` | `WARNING` | Valid Python log level |

`OPENAI_MAX_RESPONSE_TOKENS` is accepted as a legacy fallback when `MAX_RESPONSE_TOKENS` is unset. Prefer the provider-neutral setting for new installations.

## Production example

```dotenv
APP_ENV=production
GRADIO_SERVER_NAME=0.0.0.0
APP_ALLOWED_HOSTS=support.example.com
APP_AUTH_USERNAME=support
APP_AUTH_PASSWORD=replace-with-a-random-password-of-at-least-16-characters
APP_EXTERNAL_HTTPS=true
FORWARDED_ALLOW_IPS=127.0.0.1
```

Set provider variables separately. Keep TLS at a trusted reverse proxy and restrict forwarded metadata to that proxy. `APP_EXTERNAL_HTTPS=true` enables HSTS; it does not configure TLS. Validate with `python it_support_agent.py --check` before launch. Read [the deployment guide](PRODUCTION.md) for the full operational requirements.
