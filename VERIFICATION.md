# Verification — 10 October 2026

Production backend: 911 lines across typed, formatted Python modules, excluding tests and documentation.

## Passed checks

- 36 regression cases against a real Redis 7.0.15 service and temporary async SQLite: validation, atomic distributed limits, simultaneous idempotent retries, database/outbox commit, host/origin rules, duplicate JSON/header rejection, chunked/body limits, private routes, cache/security headers, safe dependency failures, notification retry and stale-worker claims.
- Browser JavaScript syntax check and Python Ruff checks/formatting.
- Pinned production dependency audit: no known vulnerabilities reported by pip-audit at verification time.
- Redis production startup configuration and password authentication verified with a real Redis service.
- Caddy configuration validated with Caddy 2.6.2. HTTP routing and static delivery exercised in the load test.
- Static fingerprinting, reproducible gzip files and responsive image variants generated.

## Final HTTP load results

| Workload | Concurrent clients | Requests | Failures | Median | P95 | P99 | Maximum |
|---|---:|---:|---:|---:|---:|---:|---:|
| Cold page/asset journeys | 100 | 3000 | 0 | 100.18 ms | 423.54 ms | 627.53 ms | 1320.57 ms |
| Enquiry write burst | 100 | 100 | 0 | 204.43 ms | 334.41 ms | 512.33 ms | 618.67 ms |

The write burst persisted 100 enquiries and 100 notification records. Static requests achieved 632.27 requests/second over 4.745 seconds. Precompressed static text improved the first run's 9.319 seconds to this final run's 4.745 seconds. Each visitor repeatedly fetched six resources, five rounds, without browser caching. Results are local HTTP request latencies, not complete page-render times.

Test topology: Caddy HTTP static/proxy service, two Uvicorn processes, real Redis 7.0.15, temporary SQLite via the async database layer, and an HTTPX load generator in the same environment. API submission limit was increased to 100 for this isolated burst; production default is 10/IP per rolling ten minutes. Production PostgreSQL performance is not represented by the SQLite benchmark. The JSON artifacts contain the measured request-level results.

## Verification limits

- Production PostgreSQL connectivity, bootstrap grants, SKIP LOCKED behaviour and multi-worker mail delivery have not been exercised against a running PostgreSQL instance here. Regression tests of outbox state use SQLite, whose locking semantics differ. Repeat with disposable PostgreSQL/Redis using the TEST_* URLs in README before launch.
- Docker/Compose container builds, image permissions/network isolation and health orchestration are not executed here because Docker is unavailable.
- Real domain DNS, public TLS issuance, Internet RTT, actual SMTP delivery, server-disk encryption and restore are not tested.
- Browser visual, mobile rendering and accessibility behaviour have not been browser-tested. The interface uses the supplied design with targeted code improvements.

No public deployment was made. No credentials were included. Passing the recorded checks does not certify security or guarantee performance on arbitrary hosting.
