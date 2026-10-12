"""Async HTTP API; production static traffic is served directly by Caddy."""

import asyncio
import json
import logging
import re
from contextlib import asynccontextmanager
from uuid import UUID
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import ValidationError
from redis.exceptions import RedisError
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from .config import load_settings
from .database import Database
from .limiter import RateLimiter, create_redis
from .middleware import BoundaryMiddleware
from .schemas import EnquiryInput
from .service import EnquiryService, IdempotencyConflict


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key.")
        result[key] = value
    return result


def create_app(settings=None, redis_client=None):
    settings = settings or load_settings()
    database = Database(settings)
    redis = redis_client or create_redis(settings)
    limiter = RateLimiter(redis, settings)
    service = EnquiryService(database, settings)

    @asynccontextmanager
    async def lifespan(app):
        logging.basicConfig(level=logging.INFO, format="%(message)s")
        try:
            yield
        finally:
            await redis.aclose()
            await database.close()

    app = FastAPI(
        title="Blue Eye Media API",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.database = database
    app.state.redis = redis
    app.state.settings = settings
    app.add_middleware(BoundaryMiddleware, settings=settings)

    @app.get("/healthz")
    async def health():
        # Liveness never fails merely because an external dependency is down.
        return {"status": "alive"}

    @app.get("/health/ready")
    async def ready():
        try:
            async with asyncio.timeout(3):
                async with database.sessions() as session:
                    await session.execute(text("SELECT 1 FROM enquiries LIMIT 1"))
                await redis.ping()
        except (TimeoutError, SQLAlchemyError, RedisError):
            return JSONResponse({"status": "not_ready"}, status_code=503)
        return {"status": "ready"}

    @app.post("/api/enquiries")
    async def enquiry(request: Request):
        try:
            retry_after = await limiter.check(request.client.host if request.client else "unknown")
        except RedisError:
            return JSONResponse({"error": "Submission service unavailable. Please try later."}, 503)
        if retry_after:
            return JSONResponse(
                {"error": "Too many requests. Please try later."},
                429,
                headers={"Retry-After": str(retry_after)},
            )
        try:
            key = request.headers.get("Idempotency-Key", "")
            parsed_key = UUID(key)
            if parsed_key.version != 4 or str(parsed_key) != key:
                raise ValueError("UUID4 required.")
            data = json.loads(await request.body(), object_pairs_hook=unique_object)
            form = EnquiryInput.model_validate(data)
        except (ValueError, ValidationError, UnicodeDecodeError, RecursionError):
            return JSONResponse(
                {"error": "Check your details and choose a future IST time within 180 days."}, 422
            )
        try:
            identifier, created = await service.save(form, key)
        except IdempotencyConflict:
            return JSONResponse(
                {"error": "This request key was already used. Please start a new enquiry."}, 409
            )
        except SQLAlchemyError:
            return JSONResponse(
                {"error": "Unable to confirm receipt. Retry using the same request key."}, 503
            )
        return JSONResponse(
            {"id": identifier, "status": "received", "appointment_confirmed": False},
            201 if created else 200,
        )

    @app.get("/{path:path}")
    async def static(path: str):
        # Development convenience; production Caddy avoids API work for assets.
        path = path or "index.html"
        if path not in {"index.html", "styles.css", "app.js", "robots.txt"} and not re.fullmatch(
            r"assets/[a-f0-9]{16}(?:-\d+w)?\.(png|jpg|webp|svg|js|css)", path
        ):
            return JSONResponse({"error": "Not found."}, 404)
        file = settings.public_dir / path
        if not file.is_file():
            return JSONResponse({"error": "Not found."}, 404)
        cache = "public, max-age=31536000, immutable" if path.startswith("assets/") else "no-cache"
        return FileResponse(file, headers={"Cache-Control": cache})

    return app


app = create_app()
