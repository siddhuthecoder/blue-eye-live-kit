"""Pure ASGI boundaries: bounded bodies, timeouts and privacy-safe telemetry."""

import asyncio
import json
import logging
import time
import uuid
from .config import Settings

logger = logging.getLogger("blueeye.requests")
MAX_BODY_BYTES = 16384


class BoundaryMiddleware:
    def __init__(self, app, settings: Settings):
        self.app = app
        self.settings = settings
        self.expected_host = settings.public_origin.split("://", 1)[1]

    def security_headers(self, request_id: str) -> list:
        headers = [
            (b"x-request-id", request_id.encode()),
            (b"x-content-type-options", b"nosniff"),
            (b"x-frame-options", b"DENY"),
            (b"referrer-policy", b"strict-origin-when-cross-origin"),
            (b"permissions-policy", b"camera=(), microphone=(), geolocation=()"),
            (
                b"content-security-policy",
                b"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'",
            ),
        ]
        if self.settings.app_env == "production":
            headers.append((b"strict-transport-security", b"max-age=31536000"))
        return headers

    async def reject(self, send, code: int, message: str, request_id: str):
        body = json.dumps({"error": message, "request_id": request_id}).encode()
        await send(
            {
                "type": "http.response.start",
                "status": code,
                "headers": self.security_headers(request_id)
                + [
                    (b"content-type", b"application/json"),
                    (b"cache-control", b"no-store"),
                    (b"content-length", str(len(body)).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        request_id = str(uuid.uuid4())
        scope.setdefault("state", {})["request_id"] = request_id
        started = time.perf_counter()
        pairs = scope.get("headers", [])
        headers = dict(pairs)
        for sensitive in (b"origin", b"content-length", b"content-type", b"idempotency-key"):
            if sum(key == sensitive for key, _ in pairs) > 1:
                return await self.reject(send, 400, "Duplicate request header.", request_id)
        if sum(k == b"host" for k, _ in pairs) != 1:
            return await self.reject(send, 400, "Invalid host.", request_id)
        if headers.get(b"host", b"").decode("latin1").lower() != self.expected_host.lower():
            return await self.reject(send, 400, "Invalid host.", request_id)
        status = 500
        response_started = False

        async def secure_send(message):
            nonlocal status, response_started
            if message["type"] == "http.response.start":
                response_started = True
                status = message["status"]
                message = dict(message)
                message["headers"] = list(message.get("headers", [])) + self.security_headers(
                    request_id
                )
                if scope["path"].startswith("/api/") or scope["path"].startswith("/health"):
                    message["headers"].append((b"cache-control", b"no-store"))
            await send(message)

        replay_receive = receive
        if scope["method"] in {"POST", "PUT", "PATCH"}:
            if headers.get(b"content-encoding", b"identity") != b"identity":
                return await self.reject(
                    send, 415, "Compressed submissions are unsupported.", request_id
                )
            if headers.get(b"origin", b"").decode("latin1") != self.settings.public_origin:
                return await self.reject(
                    send, 403, "Please submit through our website.", request_id
                )
            if (
                headers.get(b"content-type", b"").split(b";")[0].strip().lower()
                != b"application/json"
            ):
                return await self.reject(send, 415, "JSON required.", request_id)
            try:
                length = int(headers.get(b"content-length", b"0"))
                if length < 0 or length > MAX_BODY_BYTES:
                    return await self.reject(send, 413, "Submission too large.", request_id)
            except ValueError:
                return await self.reject(send, 400, "Invalid content length.", request_id)
            chunks = []
            total = 0
            try:
                async with asyncio.timeout(5):
                    while True:
                        event = await receive()
                        if event["type"] == "http.disconnect":
                            return
                        part = event.get("body", b"")
                        total += len(part)
                        if total > MAX_BODY_BYTES:
                            return await self.reject(send, 413, "Submission too large.", request_id)
                        chunks.append(part)
                        if not event.get("more_body", False):
                            break
            except TimeoutError:
                return await self.reject(send, 408, "Submission timed out.", request_id)
            body = b"".join(chunks)
            replayed = False

            async def replay_receive():
                nonlocal replayed
                if not replayed:
                    replayed = True
                    return {"type": "http.request", "body": body, "more_body": False}
                return await receive()

        try:
            # Slow database/Redis dependencies do not hold requests indefinitely.
            async with asyncio.timeout(12):
                await self.app(scope, replay_receive, secure_send)
        except TimeoutError:
            if not response_started:
                await self.reject(
                    send, 503, "Service busy. Retry using the same request key.", request_id
                )
            status = 503
        except Exception as exc:
            # No exception text, URLs, credentials, request bodies or email addresses.
            logger.error(
                json.dumps(
                    {
                        "event": "request_failure",
                        "request_id": request_id,
                        "kind": type(exc).__name__,
                    }
                )
            )
            if not response_started:
                await self.reject(send, 503, "Service temporarily unavailable.", request_id)
            status = 503
        finally:
            route = (
                scope["path"]
                if scope["path"] in {"/api/enquiries", "/healthz", "/health/ready"}
                else "public"
            )
            logger.info(
                json.dumps(
                    {
                        "event": "request",
                        "request_id": request_id,
                        "route": route,
                        "status": status,
                        "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                    }
                )
            )
