"""FastAPI chat UI with bounded, process-local authenticated sessions."""

from __future__ import annotations

import asyncio
import json
import secrets
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import LOGGER
from .config import (
    get_allowed_hosts,
    get_auth_credentials,
    get_bool_env,
    get_concurrency_limit,
    get_forwarded_allow_ips,
    get_log_level,
    get_login_rate_limit_requests,
    get_login_rate_limit_window_seconds,
    get_max_input_chars,
    get_queue_size,
    get_rate_limit_requests,
    get_rate_limit_window_seconds,
    get_root_path,
    get_server_name,
    get_server_port,
    get_state_session_capacity,
    validate_web_security_configuration,
)
from .core import MAX_HISTORY_MESSAGES, is_memory_reset_message
from .providers import get_runtime_status
from .security import (
    LoginRateLimitMiddleware,
    SecurityHeadersMiddleware,
    SlidingWindowRateLimiter,
    build_auth_callback,
    redact_sensitive_text,
    request_identity,
)
from .service import chat

STATIC = Path(__file__).with_name("static")
COOKIE_NAME = "it_support_session"
SESSION_IDLE_SECONDS = 30 * 60
MAX_JSON_BYTES = 50_000  # 12,000 Unicode characters can occupy 48,000 UTF-8 bytes.


@dataclass
class ChatSession:
    token: str
    csrf_token: str
    authenticated: bool
    username: str = ""
    history: list[dict[str, str]] = field(default_factory=list)
    last_seen: float = field(default_factory=time.monotonic)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class SessionStore:
    """Bounded process-local sessions; tokens never appear in logs or URLs."""

    def __init__(self, capacity: int):
        self.capacity = capacity
        self._sessions: dict[str, ChatSession] = {}
        self._lock = threading.Lock()

    def get(self, token: str | None) -> ChatSession | None:
        if not token:
            return None
        with self._lock:
            session = self._sessions.get(token)
            if session and time.monotonic() - session.last_seen < SESSION_IDLE_SECONDS:
                session.last_seen = time.monotonic()
                return session
            self._sessions.pop(token, None)
            return None

    def create(self, authenticated: bool = False, username: str = "") -> ChatSession:
        now = time.monotonic()
        session = ChatSession(
            token=secrets.token_urlsafe(32),
            csrf_token=secrets.token_urlsafe(32),
            authenticated=authenticated,
            username=username,
            last_seen=now,
        )
        with self._lock:
            expired = [
                key
                for key, value in self._sessions.items()
                if now - value.last_seen >= SESSION_IDLE_SECONDS
            ]
            for key in expired:
                self._sessions.pop(key, None)
            while len(self._sessions) >= self.capacity:
                oldest = min(self._sessions, key=lambda key: self._sessions[key].last_seen)
                self._sessions.pop(oldest)
            self._sessions[session.token] = session
        return session

    def remove(self, token: str) -> None:
        with self._lock:
            self._sessions.pop(token, None)


def create_app(chat_func=chat) -> Any:
    errors = validate_web_security_configuration()
    if errors:
        raise RuntimeError("Unsafe application configuration:\n- " + "\n- ".join(errors))
    authenticate = build_auth_callback(get_auth_credentials())
    sessions = SessionStore(get_state_session_capacity())
    limiter = SlidingWindowRateLimiter(get_rate_limit_requests(), get_rate_limit_window_seconds())
    concurrency = get_concurrency_limit()
    slots = asyncio.Semaphore(concurrency)
    capacity = threading.BoundedSemaphore(concurrency + get_queue_size())
    cookie_path = get_root_path() or "/"
    secure_cookie = get_bool_env("APP_EXTERNAL_HTTPS", False)

    app = FastAPI(
        title="IT Support Agent",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        root_path=get_root_path() or "",
    )
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=get_allowed_hosts())
    app.add_middleware(
        LoginRateLimitMiddleware,
        limit=get_login_rate_limit_requests(),
        window_seconds=get_login_rate_limit_window_seconds(),
    )
    app.add_middleware(SecurityHeadersMiddleware, enable_hsts=secure_cookie)

    @app.middleware("http")
    async def content_security_policy(request: Request, call_next):
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = (
            "default-src 'none'; script-src 'self'; style-src 'self'; "
            "connect-src 'self'; img-src 'self' data:; base-uri 'none'; "
            "form-action 'self'; frame-ancestors 'none'"
        )
        return response

    def set_cookie(response: Response, session: ChatSession) -> None:
        response.set_cookie(
            COOKIE_NAME,
            session.token,
            max_age=SESSION_IDLE_SECONDS,
            path=cookie_path,
            secure=secure_cookie,
            httponly=True,
            samesite="strict",
        )

    def existing_session(request: Request, *, authenticated: bool = False) -> ChatSession:
        session = sessions.get(request.cookies.get(COOKIE_NAME))
        if session is None or (authenticated and not session.authenticated):
            raise HTTPException(status_code=401, detail="Sign in to continue.")
        return session

    def require_csrf(request: Request, session: ChatSession) -> None:
        supplied = request.headers.get("x-csrf-token", "")
        if not supplied or not secrets.compare_digest(supplied, session.csrf_token):
            raise HTTPException(status_code=403, detail="Invalid session token.")

    async def json_object(request: Request, maximum: int = MAX_JSON_BYTES) -> dict[str, Any]:
        if (
            request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
            != "application/json"
        ):
            raise HTTPException(status_code=415, detail="Expected JSON.")
        content = bytearray()
        async for chunk in request.stream():
            content.extend(chunk)
            if len(content) > maximum:
                raise HTTPException(status_code=413, detail="Request too large.")
        try:
            payload = json.loads(content)
        except (UnicodeDecodeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail="Invalid JSON.") from exc
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="Expected a JSON object.")
        return payload

    @app.get("/healthz", include_in_schema=False)
    async def healthcheck() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        return FileResponse(STATIC / "index.html", media_type="text/html")

    @app.get("/assets/app.js", include_in_schema=False)
    async def javascript() -> FileResponse:
        return FileResponse(STATIC / "app.js", media_type="text/javascript")

    @app.get("/assets/style.css", include_in_schema=False)
    async def stylesheet() -> FileResponse:
        return FileResponse(STATIC / "style.css", media_type="text/css")

    @app.get("/api/session", include_in_schema=False)
    async def session_info(request: Request) -> JSONResponse:
        session = sessions.get(request.cookies.get(COOKIE_NAME))
        if session is None:
            session = sessions.create(authenticated=authenticate is None)
        response = JSONResponse(
            {
                "authenticated": session.authenticated,
                "csrf_token": session.csrf_token,
                "provider": get_runtime_status() if session.authenticated else None,
                "can_logout": authenticate is not None,
                "max_input_chars": get_max_input_chars(),
            }
        )
        set_cookie(response, session)
        return response

    @app.post("/login", include_in_schema=False)
    async def login(request: Request) -> JSONResponse:
        session = existing_session(request)
        require_csrf(request, session)
        payload = await json_object(request, maximum=2048)
        username = payload.get("username")
        password = payload.get("password")
        if not isinstance(username, str) or not isinstance(password, str):
            raise HTTPException(status_code=400, detail="Expected username and password.")
        if len(username) > 128 or len(password) > 1024:
            raise HTTPException(status_code=400, detail="Credentials too long.")
        if authenticate is None or not authenticate(username, password):
            raise HTTPException(status_code=401, detail="Invalid credentials.")
        sessions.remove(session.token)
        authenticated_session = sessions.create(authenticated=True, username=username)
        response = JSONResponse(
            {
                "authenticated": True,
                "csrf_token": authenticated_session.csrf_token,
                "provider": get_runtime_status(),
                "can_logout": True,
                "max_input_chars": get_max_input_chars(),
            }
        )
        set_cookie(response, authenticated_session)
        return response

    @app.post("/logout", include_in_schema=False)
    async def logout(request: Request) -> Response:
        session = existing_session(request)
        require_csrf(request, session)
        sessions.remove(session.token)
        response = Response(status_code=204)
        response.delete_cookie(COOKIE_NAME, path=cookie_path)
        return response

    @app.get("/api/history", include_in_schema=False)
    async def history(request: Request) -> dict[str, Any]:
        session = existing_session(request, authenticated=True)
        async with session.lock:
            return {"messages": list(session.history)}

    @app.post("/api/reset", include_in_schema=False)
    async def reset(request: Request) -> Response:
        session = existing_session(request, authenticated=True)
        require_csrf(request, session)
        async with session.lock:
            session.history.clear()
        return Response(status_code=204)

    @app.post("/api/chat", include_in_schema=False)
    async def send_message(request: Request) -> JSONResponse:
        session = existing_session(request, authenticated=True)
        require_csrf(request, session)
        payload = await json_object(request)
        message = payload.get("message")
        if not isinstance(message, str) or not message.strip():
            raise HTTPException(status_code=400, detail="Enter a support question.")
        if len(message) > get_max_input_chars():
            raise HTTPException(status_code=413, detail="Message too long.")
        identity = f"user:{session.username}" if session.username else request_identity(request)
        decision = limiter.check(identity)
        if not decision.allowed:
            raise HTTPException(
                status_code=429,
                detail="Too many requests. Try again later.",
                headers={"Retry-After": str(decision.retry_after_seconds)},
            )
        if not capacity.acquire(blocking=False):
            raise HTTPException(status_code=503, detail="Support queue is full.")
        try:
            async with session.lock:
                async with slots:
                    provider_task = asyncio.create_task(
                        asyncio.to_thread(chat_func, message, list(session.history))
                    )
                    try:
                        response_text = await asyncio.shield(provider_task)
                    except asyncio.CancelledError:
                        # Cancelling the HTTP task does not stop a running thread. Keep
                        # the session and capacity permits until the provider finishes.
                        while not provider_task.done():
                            try:
                                await asyncio.shield(provider_task)
                            except asyncio.CancelledError:
                                continue
                            except Exception:
                                break
                        if not provider_task.cancelled():
                            try:
                                provider_task.result()
                            except Exception as exc:
                                LOGGER.warning("Chat request failed: %s", exc.__class__.__name__)
                        raise
                    except Exception as exc:
                        LOGGER.warning("Chat request failed: %s", exc.__class__.__name__)
                        raise HTTPException(
                            status_code=502, detail="Support is unavailable. Try again later."
                        ) from None
                    safe_response = redact_sensitive_text(response_text)
                    if is_memory_reset_message(message):
                        session.history.clear()
                    else:
                        session.history.extend(
                            [
                                {"role": "user", "content": redact_sensitive_text(message)},
                                {"role": "assistant", "content": safe_response},
                            ]
                        )
                        session.history = session.history[-MAX_HISTORY_MESSAGES:]
                    return JSONResponse({"response": safe_response})
        finally:
            capacity.release()

    return app


def launch_app() -> None:
    try:
        import uvicorn
    except ImportError as exc:
        raise RuntimeError(
            "Install runtime dependencies with: pip install -r requirements.lock"
        ) from exc
    uvicorn.run(
        create_app(),
        host=get_server_name(),
        port=get_server_port(),
        log_level=get_log_level().lower(),
        proxy_headers=True,
        forwarded_allow_ips=get_forwarded_allow_ips(),
        server_header=False,
        date_header=False,
        access_log=False,
    )
