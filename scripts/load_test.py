"""Reproducible 100-user HTTP journeys. Run only against a site you control.
GET mode never creates records. POST mode creates synthetic enquiries and
requires --allow-writes plus a test environment with suitable rate limits.
"""

import argparse
import asyncio
import json
import statistics
import time
import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import httpx


async def run(args):
    paths = [
        "/",
        "/styles.css",
        "/app.js",
        "/assets/9e939dad027db0de.png",
        "/assets/83ac6a30e3402ba7-960w.webp",
        "/assets/647cc36013b8da36-960w.webp",
    ]
    samples = []
    codes = {}
    total_bytes = 0
    failures = 0
    limits = httpx.Limits(max_connections=args.users, max_keepalive_connections=args.users)
    async with httpx.AsyncClient(
        base_url=args.url, limits=limits, timeout=20, trust_env=False
    ) as client:
        import re

        page = await client.get("/")
        stylesheet = re.search(r'<link rel="stylesheet" href="([^"]+)"', page.text)
        script = re.search(r'<script src="([^"]+)"', page.text)
        if stylesheet:
            paths[1] = stylesheet.group(1)
        if script:
            paths[2] = script.group(1)

        async def request(method, path, **kwargs):
            nonlocal total_bytes, failures
            start = time.perf_counter()
            try:
                response = await client.request(method, path, **kwargs)
                samples.append((time.perf_counter() - start) * 1000)
                codes[str(response.status_code)] = codes.get(str(response.status_code), 0) + 1
                total_bytes += len(response.content)
                if response.status_code >= 400:
                    failures += 1
            except httpx.HTTPError:
                samples.append((time.perf_counter() - start) * 1000)
                failures += 1
                codes["transport_error"] = codes.get("transport_error", 0) + 1

        async def visitor():
            for _ in range(args.rounds):
                for path in paths:
                    await request("GET", path)

        async def submit():
            data = {
                "name": "Load Test",
                "company": "Synthetic Test",
                "email": "load@example.org",
                "service": "Brand & Identity",
                "consultationDate": (
                    datetime.now(ZoneInfo("Asia/Kolkata")) + timedelta(days=2)
                ).strftime("%Y-%m-%d"),
                "consultationTime": "10:00",
                "message": "Synthetic benchmark record; delete after testing.",
            }
            await request(
                "POST",
                "/api/enquiries",
                json=data,
                headers={"Origin": args.url.rstrip("/"), "Idempotency-Key": str(uuid.uuid4())},
            )

        start = time.perf_counter()
        await asyncio.gather(
            *[(submit() if args.allow_writes else visitor()) for _ in range(args.users)]
        )
        duration = time.perf_counter() - start
    ordered = sorted(samples)

    def percentile(p):
        return round(ordered[min(len(ordered) - 1, int((len(ordered) - 1) * p))], 2)

    report = {
        "mode": "enquiry_write" if args.allow_writes else "cold_page_journeys",
        "concurrent_users": args.users,
        "rounds": args.rounds,
        "requests": len(samples),
        "failures": failures,
        "status_codes": codes,
        "duration_seconds": round(duration, 3),
        "requests_per_second": round(len(samples) / duration, 2),
        "latency_ms": {
            "median": round(statistics.median(samples), 2),
            "p95": percentile(0.95),
            "p99": percentile(0.99),
            "max": round(max(samples), 2),
        },
        "decoded_bytes_received": total_bytes,
        "scope": "HTTP only; excludes browser rendering, internet latency, production TLS and hosting limits.",
    }
    print(json.dumps(report, indent=2))
    if args.output:
        from pathlib import Path

        Path(args.output).write_text(json.dumps(report, indent=2) + "\n")
    return failures


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    parser.add_argument("--users", type=int, default=100)
    parser.add_argument("--rounds", type=int, default=5)
    parser.add_argument("--allow-writes", action="store_true")
    parser.add_argument("--output")
    args = parser.parse_args()
    if not 1 <= args.users <= 1000 or not 1 <= args.rounds <= 100:
        parser.error("users: 1..1000; rounds: 1..100")
    raise SystemExit(1 if asyncio.run(run(args)) else 0)
