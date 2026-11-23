"""Offline HTTP boundary tests for the FastAPI chat UI."""

import asyncio
import os
import threading
import time
import unittest
from unittest.mock import patch

import httpx

from it_support.service import chat
from it_support.web import create_app

BASE_ENV = {
    "APP_ENV": "test",
    "APP_ALLOWED_HOSTS": "testserver",
    "AI_PROVIDER": "ollama",
    "PATH": os.environ.get("PATH", ""),
}


def csrf_headers(token):
    return {"x-csrf-token": token}


class WebIntegrationTests(unittest.TestCase):
    def test_authenticated_http_flow_and_login_throttle(self):
        async def exercise():
            app = create_app(chat_func=lambda message, history: "Safe reply")
            async with app.router.lifespan_context(app):
                transport = httpx.ASGITransport(app=app)
                async with httpx.AsyncClient(
                    transport=transport, base_url="http://testserver"
                ) as client:
                    session = await client.get("/api/session")
                    self.assertEqual(session.status_code, 200)
                    self.assertFalse(session.json()["authenticated"])
                    self.assertIn("httponly", session.headers["set-cookie"].lower())
                    self.assertIn("samesite=strict", session.headers["set-cookie"].lower())
                    token = session.json()["csrf_token"]
                    self.assertEqual((await client.get("/api/history")).status_code, 401)
                    self.assertEqual(
                        (
                            await client.post(
                                "/api/chat", json={"message": "Hi"}, headers=csrf_headers(token)
                            )
                        ).status_code,
                        401,
                    )
                    self.assertEqual(
                        (
                            await client.post(
                                "/login", json={"username": "support", "password": "wrong"}
                            )
                        ).status_code,
                        403,
                    )
                    wrong = await client.post(
                        "/login",
                        json={"username": "support", "password": "wrong"},
                        headers=csrf_headers(token),
                    )
                    self.assertEqual(wrong.status_code, 401)
                    login = await client.post(
                        "/login",
                        json={"username": "support", "password": "test-password-long"},
                        headers=csrf_headers(token),
                    )
                    self.assertEqual(login.status_code, 200)
                    self.assertTrue(login.json()["authenticated"])
                    new_token = login.json()["csrf_token"]
                    self.assertNotEqual(new_token, token)
                    self.assertEqual(
                        (
                            await client.post(
                                "/api/chat", json={"message": "Hi"}, headers=csrf_headers(token)
                            )
                        ).status_code,
                        403,
                    )
                    answer = await client.post(
                        "/api/chat", json={"message": "Hi"}, headers=csrf_headers(new_token)
                    )
                    self.assertEqual(answer.status_code, 200)
                    self.assertEqual(answer.json()["response"], "Safe reply")
                    history = (await client.get("/api/history")).json()["messages"]
                    self.assertEqual([item["role"] for item in history], ["user", "assistant"])
                    limited = await client.post(
                        "/login",
                        json={"username": "support", "password": "wrong"},
                        headers=csrf_headers(new_token),
                    )
                    self.assertEqual(limited.status_code, 429)
                    self.assertIn("retry-after", limited.headers)

        env = {
            **BASE_ENV,
            "APP_AUTH_USERNAME": "support",
            "APP_AUTH_PASSWORD": "test-password-long",
            "LOGIN_RATE_LIMIT_REQUESTS": "3",
        }
        with patch.dict(os.environ, env, clear=True):
            asyncio.run(exercise())

    def test_sessions_are_isolated_and_reset_is_scoped(self):
        async def exercise():
            app = create_app(chat_func=lambda message, history: str(len(history)))
            async with app.router.lifespan_context(app):
                transport = httpx.ASGITransport(app=app)
                async with (
                    httpx.AsyncClient(transport=transport, base_url="http://testserver") as a,
                    httpx.AsyncClient(transport=transport, base_url="http://testserver") as b,
                ):
                    token_a = (await a.get("/api/session")).json()["csrf_token"]
                    token_b = (await b.get("/api/session")).json()["csrf_token"]
                    self.assertNotEqual(token_a, token_b)
                    self.assertEqual(
                        (
                            await a.post(
                                "/api/chat",
                                json={"message": "first"},
                                headers=csrf_headers(token_a),
                            )
                        ).json()["response"],
                        "0",
                    )
                    self.assertEqual((await b.get("/api/history")).json()["messages"], [])
                    self.assertEqual(
                        (
                            await b.post(
                                "/api/chat",
                                json={"message": "second"},
                                headers=csrf_headers(token_b),
                            )
                        ).json()["response"],
                        "0",
                    )
                    self.assertEqual(
                        (
                            await a.post(
                                "/api/chat",
                                json={"message": "third"},
                                headers=csrf_headers(token_a),
                            )
                        ).json()["response"],
                        "2",
                    )
                    self.assertEqual(
                        (await a.post("/api/reset", headers=csrf_headers(token_a))).status_code, 204
                    )
                    self.assertEqual((await a.get("/api/history")).json()["messages"], [])
                    self.assertEqual(len((await b.get("/api/history")).json()["messages"]), 2)
                    self.assertEqual(
                        (
                            await a.post(
                                "/api/chat",
                                json={"message": "fourth"},
                                headers=csrf_headers(token_b),
                            )
                        ).status_code,
                        403,
                    )
                    self.assertEqual(
                        (await b.post("/logout", headers=csrf_headers(token_b))).status_code, 204
                    )
                    self.assertEqual((await b.get("/api/history")).status_code, 401)

        with patch.dict(os.environ, BASE_ENV, clear=True):
            asyncio.run(exercise())

    def test_rate_limit_and_provider_failure_do_not_expose_details(self):
        async def exercise():
            app = create_app(chat_func=chat)
            async with app.router.lifespan_context(app):
                transport = httpx.ASGITransport(app=app)
                async with httpx.AsyncClient(
                    transport=transport, base_url="http://testserver"
                ) as client:
                    token = (await client.get("/api/session")).json()["csrf_token"]
                    with patch(
                        "it_support.service.ask_ollama_agent",
                        side_effect=RuntimeError("private-provider-secret"),
                    ):
                        first = await client.post(
                            "/api/chat",
                            json={"message": "Printer offline password=Secret123"},
                            headers=csrf_headers(token),
                        )
                        second = await client.post(
                            "/api/chat",
                            json={"message": "Printer offline"},
                            headers=csrf_headers(token),
                        )
                    self.assertEqual(first.status_code, 200)
                    self.assertIn("could not contact", first.json()["response"])
                    self.assertNotIn("private-provider-secret", first.text)
                    self.assertEqual(second.status_code, 200)
                    third = await client.post(
                        "/api/chat",
                        json={"message": "Printer offline"},
                        headers=csrf_headers(token),
                    )
                    self.assertEqual(third.status_code, 429)
                    self.assertIn("retry-after", third.headers)
                    stored = str((await client.get("/api/history")).json())
                    self.assertNotIn("Secret123", stored)
                    self.assertNotIn("private-provider-secret", stored)

        with patch.dict(os.environ, {**BASE_ENV, "RATE_LIMIT_REQUESTS": "2"}, clear=True):
            asyncio.run(exercise())

    def test_concurrent_chat_requests_keep_one_session_history(self):
        def answer(message, history):
            time.sleep(0.01)
            return f"reply {message}"

        async def exercise():
            app = create_app(chat_func=answer)
            async with app.router.lifespan_context(app):
                transport = httpx.ASGITransport(app=app)
                async with httpx.AsyncClient(
                    transport=transport, base_url="http://testserver"
                ) as client:
                    token = (await client.get("/api/session")).json()["csrf_token"]
                    responses = await asyncio.gather(
                        *[
                            client.post(
                                "/api/chat",
                                json={"message": f"issue {i}"},
                                headers=csrf_headers(token),
                            )
                            for i in range(6)
                        ]
                    )
                    self.assertTrue(
                        all(response.status_code == 200 for response in responses), responses
                    )
                    history = (await client.get("/api/history")).json()["messages"]
                    self.assertEqual(len(history), 12)
                    self.assertEqual(
                        {item["content"] for item in history if item["role"] == "user"},
                        {f"issue {i}" for i in range(6)},
                    )

        with patch.dict(os.environ, BASE_ENV, clear=True):
            asyncio.run(exercise())

    def test_cancelled_request_holds_session_until_provider_finishes(self):
        started = threading.Event()
        release = threading.Event()
        calls = []

        def answer(message, history):
            calls.append(message)
            if message == "first":
                started.set()
                release.wait(timeout=2)
                raise RuntimeError("private-provider-secret")
            return str(len(history))

        async def exercise():
            app = create_app(chat_func=answer)
            async with app.router.lifespan_context(app):
                transport = httpx.ASGITransport(app=app)
                async with httpx.AsyncClient(
                    transport=transport, base_url="http://testserver"
                ) as client:
                    token = (await client.get("/api/session")).json()["csrf_token"]
                    first = asyncio.create_task(
                        client.post(
                            "/api/chat",
                            json={"message": "first"},
                            headers=csrf_headers(token),
                        )
                    )
                    self.assertTrue(await asyncio.to_thread(started.wait, 1))
                    first.cancel()
                    await asyncio.sleep(0.02)
                    second = asyncio.create_task(
                        client.post(
                            "/api/chat",
                            json={"message": "second"},
                            headers=csrf_headers(token),
                        )
                    )
                    try:
                        await asyncio.sleep(0.02)
                        self.assertFalse(first.done())
                        self.assertEqual(calls, ["first"])
                        self.assertFalse(second.done())
                    finally:
                        release.set()
                    with self.assertLogs("it_support", level="WARNING") as logged:
                        with self.assertRaises(asyncio.CancelledError):
                            await first
                    self.assertNotIn("private-provider-secret", str(logged.output))
                    response = await second
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(response.json()["response"], "0")
                    self.assertEqual(calls, ["first", "second"])

        with patch.dict(os.environ, BASE_ENV, clear=True):
            asyncio.run(exercise())

    def test_trusted_host_headers_and_no_upload_surface(self):
        async def exercise():
            app = create_app(chat_func=lambda message, history: "ok")
            async with app.router.lifespan_context(app):
                transport = httpx.ASGITransport(app=app)
                async with httpx.AsyncClient(
                    transport=transport, base_url="http://testserver"
                ) as client:
                    health = await client.get("/healthz")
                    self.assertEqual(health.json(), {"status": "ok"})
                    self.assertEqual(health.headers["x-content-type-options"], "nosniff")
                    self.assertEqual(health.headers["cache-control"], "no-store")
                    self.assertEqual((await client.get("/config")).status_code, 404)
                    self.assertEqual(
                        (await client.post("/upload", content=b"data")).status_code, 404
                    )
                    self.assertEqual(
                        (await client.get("/", headers={"host": "evil.example"})).status_code, 400
                    )

        with patch.dict(os.environ, BASE_ENV, clear=True):
            asyncio.run(exercise())


if __name__ == "__main__":
    unittest.main()
