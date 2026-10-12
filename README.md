# Blue Eye Media — Production Website Kit v2

This rebuild uses JavaScript in the browser, an asynchronous Python API, PostgreSQL for durable enquiries, Redis for shared rolling-window rate limits, and Caddy for HTTPS/static files. The backend exceeds the requested 500–600 line minimum through separate, useful modules. Line count is not a security or performance guarantee; the test results and deployment boundaries below describe what is actually established.

## What changed

- A browser retry uses the same idempotency key, so overlapping retries create one enquiry and one notification record.
- Enquiry and notification-outbox records commit in one database transaction. Optional email delivery runs separately from visitor requests, with retry/backoff and lease recovery.
- PostgreSQL connections have bounded pools and statement/lock timeouts. Redis limits are atomic across workers; unavailable Redis blocks submissions safely rather than bypassing controls.
- Public page/image traffic is served directly by Caddy. Responsive/lazy images, fingerprinted assets, immutable caching and precompressed text reduce repeat downloads and CPU work.
- Body limits cover chunked requests, not just Content-Length. Origin/host checks, duplicate-header rejection, strict fields, control-character checks, body/request deadlines and privacy-safe errors/logs protect the API boundary.
- The runtime database role has table permissions without administrator privileges. Database/Redis/API ports are not exposed publicly. The default API network has no outbound Internet access.
- Navigation, focus handling, skip link, reduced motion, readable controls and honest consultation confirmation improve the existing design.

## Files

| Path | Responsibility |
|---|---|
| `backend/config.py` | Typed configuration and safe startup failures |
| `backend/database.py` | Async pools, indexed enquiry/outbox models |
| `backend/schemas.py` | Bounded input validation and IST scheduling rules |
| `backend/limiter.py` | Atomic Redis rolling-window limits |
| `backend/service.py` | Transactional, idempotent writes |
| `backend/middleware.py` | HTTP boundaries, timeouts and security headers |
| `backend/main.py` | Submission API, liveness/readiness, development static routes |
| `backend/worker.py` | Optional durable email worker |
| `backend/bootstrap.py` | One-off schema/least-privilege role setup |
| `backend/cli.py` | Private listing, deletion, retention and queue tools |
| `public/` | Blue Eye Media interface, source JS/CSS and responsive assets |
| `scripts/build_static.py` | Fingerprint/precompress updated page assets |
| `scripts/load_test.py` | Reproducible concurrent HTTP load test |
| `tests/` | Security, data integrity, failure/retry regression tests |
| `compose.yaml`, `Dockerfile`, `Caddyfile` | Deployable production configuration |
| `LOAD_TEST_*.json`, `VERIFICATION.md`, `REVIEW.md` | Measurements, verification limits and review |

## Host requirements

Use a Linux host with Docker Engine/Compose v2, at least 2 vCPU and 4 GB RAM as an initial deployment baseline, SSD-backed persistent storage, SSH access and a domain you control. This starting size must be checked on your actual server; sharing a low-resource host with other busy applications can change performance. Static-only hosting/shared cPanel without Python containers is insufficient for this backend. No hosting purchase or public launch has been made by providing the kit.

The default topology is one API service with two Uvicorn workers, a separate Caddy service, PostgreSQL, Redis and an optional email worker. There are at most 15 database connections per API worker and 15 per mail worker; 100 visitors do not require 100 database connections. Add replicas only after checking the total database connection budget. Caddy serves reads independently of API/database availability.

## Launch

1. Copy this folder to your server and work from it. Point your selected hostname's DNS A record to the server's public IPv4 address. Add AAAA only when IPv6 works. Preserve existing MX/email records. This configuration uses one canonical hostname; www aliases need separate DNS and redirect configuration.
2. Allow inbound TCP 80 and 443; restrict SSH to trusted addresses. Never publish API, PostgreSQL or Redis ports. Check the hosting firewall as well as the operating-system firewall.
3. Create settings:

```sh
cp .env.example .env
chmod 600 .env
python3 -c "import secrets; print(secrets.token_hex(32))"
```

Run the last command independently four times. Paste distinct values into `POSTGRES_PASSWORD` (administrator), `APP_DB_PASSWORD` (runtime), `REDIS_PASSWORD` and `SIGNING_SECRET`. Set `SITE_DOMAIN` to your real hostname without a protocol/path, and `ACME_EMAIL` to an address you control. Do not deploy example values. Keep `.env` private and out of Git. Use hex passwords as specified so database/Redis URLs do not need additional escaping.

4. Validate and start:

```sh
docker compose config --quiet
docker compose build --pull
docker compose up -d
docker compose ps
docker compose logs --tail=50 api web init-db
```

The one-off initializer creates the tables and the restricted `blueeye_app` database role before API startup. It receives administrator credentials; the API and mail worker receive only runtime credentials. The initializer is for the initial schema, not an automatic schema migration framework. Use reviewed, versioned migrations for future model changes.

5. Open `https://YOUR_HOSTNAME/`. Check HTTP redirects to HTTPS, all dialogs/services, mobile layout, keyboard navigation and `/health/ready`. Submit a genuine test enquiry with a future IST date/time and inspect it:

```sh
docker compose exec api python -m backend.cli list --limit 10
```

Treat this output as personal data; use a private terminal. The preferred time is a request, not a calendar reservation.

6. Review the displayed mailbox, LinkedIn search link, Instagram URL, image rights and privacy wording. Verify `info@blueeyemedia.in` can receive messages. Configure your final canonical URL/sitemap after choosing the hostname. Check caching/compression headers on assets. Run the included GET load test on your host before admitting real traffic.

## Optional email notifications

The default installation saves every accepted enquiry and queues a notification, but SMTP is disabled until configured. Assign someone to inspect enquiries daily if email is not enabled.

Set `SMTP_HOST`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_SENDER`, and `NOTIFICATION_RECIPIENT`. Default port 465 uses TLS from connection start. For a provider requiring port 587, set `SMTP_PORT=587` and `SMTP_STARTTLS=true`. Certificate verification stays enabled. Never put SMTP credentials in public JavaScript or page files.

```sh
docker compose --profile notifications up -d worker
docker compose exec api python -m backend.cli queue-status
docker compose logs --tail=50 worker
```

Test with your own mailbox. Pending notifications from before activation will be processed: inspect the queue before enabling the worker. Delivery is at least once, not exactly once; a crash after the mail server accepts a message may cause a duplicate. Stable Message-ID lets downstream systems deduplicate. After eight failed attempts the notification is marked failed; the enquiry remains saved. Resolve the mail problem, then requeue deliberately:

```sh
docker compose exec api python -m backend.cli retry-failed
```

## Maintenance and backups

Create a consistent PostgreSQL logical backup:

```sh
mkdir -p backups
chmod 700 backups
umask 077
docker compose exec -T postgres pg_dump -U postgres -d blueeye --format=custom > backups/blueeye.dump
```

Copy to encrypted off-server storage and apply a documented backup retention policy. Use different filenames for dated backups. Never run `docker compose down -v` against live volumes unless intentionally deleting data.

Restore during a maintenance window after taking a fresh backup. The following replaces table data and therefore is destructive; first verify the backup and test restoration on a separate installation:

```sh
docker compose stop api worker
docker compose exec -T postgres pg_restore -U postgres -d blueeye --clean --if-exists --no-owner < backups/blueeye.dump
docker compose run --rm init-db
docker compose up -d api
```

Restart the worker with the notifications profile only if configured. Check readiness, one known enquiry and queue state. Bootstrap reapplies table permissions after restoration. Container volumes and off-server backups require encryption/restricted access; credentials and file permissions are not encryption at rest.

The public policy says unconverted enquiries normally expire after 180 days. Put the following command into your private operations scheduler daily, and apply the same retention rules to backups:

```sh
docker compose exec -T api python -m backend.cli purge
```

Move active client records to your authorised CRM before the deadline. For a verified individual deletion request, pause mail delivery first, then use the record's UUID:

```sh
docker compose stop worker
docker compose exec api python -m backend.cli delete --id RECORD_UUID
```

Restart the configured worker afterwards. No public administration, listing or deletion API exists. Operator access uses your server's authenticated SSH/Docker permissions. Restrict Docker membership to authorised administrators.

## Local development and tests

Use Python 3.12 and a private Redis test instance. The development profile uses SQLite only for local exercises; production configuration refuses SQLite.

```sh
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements-dev.txt
python -m backend.cli init-db
uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

Open exactly `http://localhost:8000`. Leave no production `.env` in your development folder, or explicitly set development variables in your environment. Start your own Redis on localhost:6379; `/healthz` remains live without Redis, but submissions/readiness require it.

Tests default to temporary SQLite and fakeredis. For actual PostgreSQL/Redis integration, point the test URLs at disposable databases: the fixtures delete all test tables' rows and flush the selected Redis database. Never use production URLs.

```sh
python -m pytest -q
# Optional disposable-services integration run:
TEST_DATABASE_URL='postgresql+psycopg://TEST_USER:TEST_PASSWORD@localhost/TEST_DB' TEST_REDIS_URL='redis://localhost:6379/15' python -m pytest -q
ruff check backend tests scripts
node --check public/app.js
pip-audit -r requirements.txt
```

Windows activation is `.venv\Scripts\activate`. Production runs the Docker deployment, not a development server. Browser rendering/accessibility and real PostgreSQL/SMTP checks remain part of your launch validation; see `VERIFICATION.md`.

After changing page content, CSS or browser JavaScript, regenerate fingerprinted/precompressed assets:

```sh
python scripts/build_static.py
```

Rebuild the web image and retain older fingerprinted files until their cache window expires. Do not edit a content-hashed image/code asset in place.

## Load testing

GET mode sends six page/asset requests per visitor per round, with 100 concurrent clients and no browser cache. It does not write enquiries:

```sh
python scripts/load_test.py --url https://YOUR_HOSTNAME --users 100 --rounds 5 --output load-result.json
```

POST mode is opt-in and creates synthetic data. Only use an isolated test deployment, with `PER_IP_LIMIT=100` set for the API and no mail worker running:

```sh
python scripts/load_test.py --url https://TEST_HOSTNAME --users 100 --allow-writes --output writes-result.json
```

Normal production settings allow ten submissions per client IP in a rolling ten-minute window and 1,000 submissions globally per rolling minute. Public page visits are unaffected. An office/carrier NAT can share an IP; review limits with actual traffic. The benchmark's raised write-test limit is not the production default. There is no special header that bypasses rate limits.

## Deployment boundaries

- Redis limits, body bounds and concurrency caps do not replace upstream DDoS protection. If public abuse rises, add a trusted edge/bot challenge and configure its IP trust deliberately.
- The API accepts only the configured Host/Origin and trusts proxy headers only because its port/network is private and Caddy is the only public ingress. Do not expose port 8000 or connect untrusted containers to the private network. A second proxy/CDN requires reviewing this configuration before use.
- Local benchmarks exclude Internet RTT, TLS, browser rendering and production PostgreSQL performance. Passing 100-client tests is evidence for the tested environment, not a guarantee for any hosting plan.
- Image tags are maintained major tags. Pin reviewed digests for reproducible infrastructure, scan/update images, and keep OS/dependencies patched. Python dependencies are pinned in `requirements.txt`.
- Preserve a previous release image/source and database backup for rollback. Do not roll back across a schema migration without its reviewed rollback procedure.
- If the first SQLite kit was already deployed, preserve its data before switching. This release starts a new PostgreSQL schema; it does not silently import or delete legacy enquiries. Arrange an explicit verified migration before cutting over a live installation.

Official technical references: https://fastapi.tiangolo.com/deployment/concepts/ ; https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html ; https://redis.io/docs/latest/commands/incr/ ; https://caddyserver.com/docs/automatic-https
