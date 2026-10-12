"""Behaviour tests with real PostgreSQL/Redis when TEST_* URLs are supplied.
Default fallback is temporary SQLite and fakeredis, never a production claim.
"""

import asyncio
import os
import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import httpx
import pytest
import pytest_asyncio
from fakeredis.aioredis import FakeRedis
from redis.asyncio import Redis
from sqlalchemy import func, select
from backend.config import Settings
from backend.database import Enquiry, Outbox
from backend.main import create_app
from backend.limiter import RateLimiter
from backend.service import EnquiryService
from backend.schemas import EnquiryInput


@pytest_asyncio.fixture
async def app(tmp_path):
    settings = Settings(
        app_env="test",
        public_origin="http://test",
        database_url=os.environ.get(
            "TEST_DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path}/test.sqlite3"
        ),
        per_ip_limit=100,
        global_limit=1000,
    )
    redis_url = os.environ.get("TEST_REDIS_URL")
    redis = (
        Redis.from_url(redis_url, decode_responses=True)
        if redis_url
        else FakeRedis(decode_responses=True)
    )
    await redis.flushdb()  # TEST_REDIS_URL must be a disposable test database.
    instance = create_app(settings, redis)
    await instance.state.database.initialize()
    async with instance.state.database.sessions() as session:
        from sqlalchemy import delete

        await session.execute(delete(Outbox))
        await session.execute(delete(Enquiry))
        await session.commit()
    yield instance
    await redis.aclose()
    await instance.state.database.close()


@pytest_asyncio.fixture
async def client(app):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


def payload():
    return {
        "name": "Test Person",
        "company": "Test Company",
        "email": "person@example.org",
        "phone": "",
        "service": "Brand & Identity",
        "consultationDate": (datetime.now(ZoneInfo("Asia/Kolkata")) + timedelta(days=2)).strftime(
            "%Y-%m-%d"
        ),
        "consultationTime": "10:00",
        "message": "Create a brand identity",
        "website": "",
    }


def headers(key=None):
    return {"Origin": "http://test", "Idempotency-Key": key or str(uuid.uuid4())}


async def test_commit_and_outbox(client, app):
    response = await client.post("/api/enquiries", json=payload(), headers=headers())
    assert response.status_code == 201
    async with app.state.database.sessions() as session:
        assert await session.scalar(select(func.count()).select_from(Enquiry)) == 1
        assert await session.scalar(select(func.count()).select_from(Outbox)) == 1
    assert response.json()["appointment_confirmed"] is False


async def test_idempotency_replay(client, app):
    h = headers()
    data = payload()
    first = await client.post("/api/enquiries", json=data, headers=h)
    second = await client.post("/api/enquiries", json=data, headers=h)
    assert first.status_code == 201 and second.status_code == 200
    assert first.json()["id"] == second.json()["id"]


async def test_idempotency_conflict(client):
    h = headers()
    await client.post("/api/enquiries", json=payload(), headers=h)
    response = await client.post(
        "/api/enquiries", json={**payload(), "company": "Another company"}, headers=h
    )
    assert response.status_code == 409


async def test_concurrent_idempotency(client, app):
    h = headers()
    data = payload()
    results = await asyncio.gather(
        *[client.post("/api/enquiries", json=data, headers=h) for _ in range(20)]
    )
    assert sum(r.status_code == 201 for r in results) == 1
    assert all(r.status_code in (200, 201) for r in results)
    assert len({r.json()["id"] for r in results}) == 1


@pytest.mark.parametrize(
    "key,value",
    [
        ("name", []),
        ("email", "wrong"),
        ("message", "x" * 3001),
        ("consultationDate", "2020-01-01"),
        ("consultationDate", "2099-01-01"),
        ("service", "unknown"),
        ("consultationTime", "03:00"),
        ("website", "bot"),
        ("phone", "\x00"),
        ("unexpected", "value"),
    ],
)
async def test_validation(client, key, value):
    r = await client.post("/api/enquiries", json={**payload(), key: value}, headers=headers())
    assert r.status_code == 422
    assert "person@example.org" not in r.text


async def test_origin_and_content_type(client):
    assert (await client.post("/api/enquiries", json=payload())).status_code == 403
    assert (
        await client.post(
            "/api/enquiries", json=payload(), headers={**headers(), "Origin": "http://evil"}
        )
    ).status_code == 403
    assert (
        await client.post(
            "/api/enquiries", content="text", headers={**headers(), "Content-Type": "text/plain"}
        )
    ).status_code == 415


async def test_bad_host(client):
    assert (await client.get("/healthz", headers={"Host": "evil.test"})).status_code == 400


async def test_security_headers_on_errors(client):
    r = await client.post("/api/enquiries", json={})
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert "script-src 'self'" in r.headers["Content-Security-Policy"]
    assert r.headers["Cache-Control"] == "no-store"


async def test_body_size_and_compression(client):
    r = await client.post(
        "/api/enquiries",
        content="x" * 17000,
        headers={**headers(), "Content-Type": "application/json"},
    )
    assert r.status_code == 413
    r = await client.post(
        "/api/enquiries", json=payload(), headers={**headers(), "Content-Encoding": "gzip"}
    )
    assert r.status_code == 415


async def test_duplicate_json_key(client):
    r = await client.post(
        "/api/enquiries",
        content='{"name":"first","name":"second"}',
        headers={**headers(), "Content-Type": "application/json"},
    )
    assert r.status_code == 422


@pytest.mark.parametrize(
    "path",
    [
        "/.env",
        "/backend/config.py",
        "/data/dev.sqlite3",
        "/assets/../../backend/config.py",
        "/docs",
        "/openapi.json",
    ],
)
async def test_private_routes(client, path):
    assert (await client.get(path)).status_code == 404


async def test_liveness_readiness(client):
    assert (await client.get("/healthz")).status_code == 200
    assert (await client.get("/health/ready")).status_code == 200


async def test_parameterized_storage(client, app):
    data = {**payload(), "company": "O'Reilly; DROP TABLE enquiries;"}
    assert (await client.post("/api/enquiries", json=data, headers=headers())).status_code == 201
    assert (
        await client.post("/api/enquiries", json=payload(), headers=headers())
    ).status_code == 201


async def test_atomic_rate_limit(app):
    settings = Settings(app_env="test", per_ip_limit=5)
    limiter = RateLimiter(app.state.redis, settings)
    results = await asyncio.gather(*[limiter.check("192.0.2.10") for _ in range(50)])
    assert sum(r == 0 for r in results) == 5
    assert all(r >= 1 for r in results if r)


async def test_fail_closed_redis(client, app, monkeypatch):
    from redis.exceptions import ConnectionError

    async def fail(*args, **kwargs):
        raise ConnectionError("secret-internal-host")

    monkeypatch.setattr(app.state.redis, "eval", fail)
    r = await client.post("/api/enquiries", json=payload(), headers=headers())
    assert r.status_code == 503 and "secret-internal-host" not in r.text


async def test_static_asset_caching(client):
    r = await client.get("/")
    assert r.status_code == 200 and r.headers["Cache-Control"] == "no-cache"
    import re

    for path in set(re.findall(r'(?:src|href)="(/[^\"]+)"', r.text)):
        asset = await client.get(path)
        assert asset.status_code == 200, path
        if path.startswith("/assets/"):
            assert "immutable" in asset.headers["Cache-Control"]


def test_production_config_fail_fast():
    with pytest.raises(ValueError):
        Settings(app_env="production")


async def test_outbox_claim_finish_and_retry(app):
    from backend.worker import claim, finish
    from backend.database import utcnow

    service = EnquiryService(app.state.database, app.state.settings)
    await service.save(EnquiryInput.model_validate(payload()), str(uuid.uuid4()))
    job = await claim(app.state.database)
    assert job and job[2] == 1
    assert await claim(app.state.database) is None
    await finish(app.state.database, job, failed=True)
    async with app.state.database.sessions() as session:
        row = await session.get(Outbox, job[0])
        assert row.status == "pending"
        row.available_at = utcnow() - timedelta(seconds=1)
        await session.commit()
    retry = await claim(app.state.database)
    assert retry[2] == 2
    await finish(app.state.database, retry)
    async with app.state.database.sessions() as session:
        row = await session.get(Outbox, job[0])
        assert row.status == "sent"


async def test_stale_worker_cannot_complete_new_claim(app):
    from backend.worker import claim, finish
    from backend.database import utcnow

    service = EnquiryService(app.state.database, app.state.settings)
    await service.save(EnquiryInput.model_validate(payload()), str(uuid.uuid4()))
    original = await claim(app.state.database)
    async with app.state.database.sessions() as session:
        row = await session.get(Outbox, original[0])
        row.lease_until = utcnow() - timedelta(seconds=1)
        await session.commit()
    newer = await claim(app.state.database)
    assert newer[1] != original[1]
    await finish(app.state.database, original)
    async with app.state.database.sessions() as session:
        row = await session.get(Outbox, newer[0])
        assert row.status == "sending"
    await finish(app.state.database, newer)


async def test_chunked_size_limit_without_content_length(app):
    body = b"x" * 17000
    events = iter(
        [
            {"type": "http.request", "body": body[:8000], "more_body": True},
            {"type": "http.request", "body": body[8000:], "more_body": False},
        ]
    )
    sent = []

    async def receive():
        return next(events)

    async def send(event):
        sent.append(event)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/api/enquiries",
        "raw_path": b"/api/enquiries",
        "query_string": b"",
        "headers": [
            (b"host", b"test"),
            (b"origin", b"http://test"),
            (b"content-type", b"application/json"),
        ],
        "client": ("127.0.0.1", 1),
        "server": ("test", 80),
    }
    await app(scope, receive, send)
    assert sent[0]["status"] == 413


async def test_duplicate_sensitive_headers(client):
    r = await client.post(
        "/api/enquiries",
        content="{}",
        headers=[
            ("Origin", "http://test"),
            ("Origin", "http://evil"),
            ("Content-Type", "application/json"),
        ],
    )
    assert r.status_code == 400


async def test_liveness_survives_dependency_failure(client, app, monkeypatch):
    from redis.exceptions import ConnectionError

    async def fail(*args, **kwargs):
        raise ConnectionError("private-host")

    monkeypatch.setattr(app.state.redis, "ping", fail)
    assert (await client.get("/healthz")).status_code == 200
    r = await client.get("/health/ready")
    assert r.status_code == 503 and "private-host" not in r.text
