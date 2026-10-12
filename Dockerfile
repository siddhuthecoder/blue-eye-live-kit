FROM python:3.12-slim AS api
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && useradd --uid 10001 --create-home site
COPY --chown=site:site backend ./backend
USER site
EXPOSE 8000
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2", "--proxy-headers", "--forwarded-allow-ips", "*", "--limit-concurrency", "200", "--timeout-keep-alive", "5", "--timeout-graceful-shutdown", "20", "--no-access-log"]
FROM caddy:2-alpine AS web
COPY public /srv/public
COPY Caddyfile /etc/caddy/Caddyfile
