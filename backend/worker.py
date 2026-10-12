"""Durable email notifications, off the visitor request path.

Delivery is at least once: a process crash after SMTP accepts but before the
sent marker commits may cause a duplicate. Message-ID is stable for deduping.
"""

import asyncio
import logging
import signal
import smtplib
import ssl
import uuid
from datetime import timedelta
from email.message import EmailMessage
from sqlalchemy import and_, or_, select, update
from .config import Settings, load_settings
from .database import Database, Enquiry, Outbox, utcnow

log = logging.getLogger("blueeye.worker")


async def claim(database: Database):
    now = utcnow()
    token = str(uuid.uuid4())
    async with database.sessions() as session:
        async with session.begin():
            query = (
                select(Outbox)
                .where(
                    or_(
                        and_(Outbox.status == "pending", Outbox.available_at <= now),
                        and_(Outbox.status == "sending", Outbox.lease_until <= now),
                    )
                )
                .order_by(Outbox.available_at)
                .limit(1)
                .with_for_update(skip_locked=True)
            )
            job = await session.scalar(query)
            if job is None:
                return None
            enquiry = await session.get(Enquiry, job.enquiry_id)
            job.status = "sending"
            job.claim_token = token
            job.lease_until = now + timedelta(seconds=120)
            job.attempts += 1
            return (job.id, token, job.attempts, enquiry.id, enquiry.payload)


def send_notification(settings: Settings, identifier: str, payload: dict):
    message = EmailMessage()
    message["Subject"] = "New Blue Eye Media website enquiry"
    message["From"] = settings.smtp_sender
    message["To"] = settings.notification_recipient
    message["Message-ID"] = f"<{identifier}@{settings.hostname}>"
    # Plain text prevents HTML injection. User input never enters mail headers.
    message.set_content(
        "Enquiry reference: "
        + identifier
        + "\n\n"
        + "\n".join(f"{key}: {value}" for key, value in payload.items())
    )
    context = ssl.create_default_context()
    if settings.smtp_starttls:
        server = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15)
    else:
        server = smtplib.SMTP_SSL(
            settings.smtp_host, settings.smtp_port, timeout=15, context=context
        )
    with server:
        if settings.smtp_starttls:
            server.ehlo()
            server.starttls(context=context)
            server.ehlo()
        if settings.smtp_username:
            server.login(settings.smtp_username, settings.smtp_password.get_secret_value())
        server.send_message(message)


async def finish(database, job, failed=False):
    identifier, token, attempts, _, _ = job
    values = {"lease_until": None, "claim_token": None}
    if failed:
        values.update(
            status="failed" if attempts >= 8 else "pending",
            available_at=utcnow() + timedelta(seconds=min(3600, 30 * 2**attempts)),
            last_error="SMTP delivery failed",
        )
    else:
        values.update(status="sent", last_error=None)
    async with database.sessions() as session:
        await session.execute(
            update(Outbox)
            .where(Outbox.id == identifier, Outbox.claim_token == token)
            .values(**values)
        )
        await session.commit()


async def run():
    settings = load_settings()
    if settings.app_env != "production":
        raise RuntimeError("Notification workers require production PostgreSQL configuration.")
    if not settings.smtp_host:
        raise RuntimeError("Set SMTP_HOST before enabling the notification worker.")
    database = Database(settings)
    stopping = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stopping.set)
    try:
        while not stopping.is_set():
            try:
                job = await claim(database)
                if job:
                    try:
                        await asyncio.to_thread(send_notification, settings, job[3], job[4])
                    except Exception:
                        await finish(database, job, failed=True)
                        log.warning("notification_retry")
                    else:
                        await finish(database, job)
                    continue
            except Exception:
                # Lease recovery handles crashes without losing a committed enquiry.
                log.error("notification_worker_dependency_failure")
            try:
                await asyncio.wait_for(stopping.wait(), timeout=2)
            except TimeoutError:
                pass
    finally:
        await database.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run())
