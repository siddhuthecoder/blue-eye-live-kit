"""Idempotent writes: enquiry and notification commit together."""

import hashlib
import hmac
import json
import uuid
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from .config import Settings
from .database import Database, Enquiry, Outbox
from .schemas import EnquiryInput


class IdempotencyConflict(Exception):
    """A previously accepted key cannot be reused for different content."""


class EnquiryService:
    def __init__(self, database: Database, settings: Settings):
        self.database = database
        self.settings = settings

    def fingerprint(self, payload: dict) -> str:
        encoded = json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode()
        return hmac.new(
            self.settings.signing_secret.get_secret_value().encode(), encoded, hashlib.sha256
        ).hexdigest()

    async def save(self, form: EnquiryInput, key: str) -> tuple[str, bool]:
        payload = form.stored_payload()
        fingerprint = self.fingerprint(payload)
        async with self.database.sessions() as session:
            existing = await session.scalar(select(Enquiry).where(Enquiry.idempotency_key == key))
            if existing:
                if not hmac.compare_digest(existing.fingerprint, fingerprint):
                    raise IdempotencyConflict()
                return existing.id, False
            identifier = str(uuid.uuid4())
            session.add(
                Enquiry(
                    id=identifier, idempotency_key=key, fingerprint=fingerprint, payload=payload
                )
            )
            try:
                # Explicit flush establishes the parent before the outbox foreign key.
                await session.flush()
                session.add(Outbox(id=str(uuid.uuid4()), enquiry_id=identifier))
                await session.commit()
                return identifier, True
            except IntegrityError:
                await session.rollback()
                # A racing request with the same key may have just committed.
                existing = await session.scalar(
                    select(Enquiry).where(Enquiry.idempotency_key == key)
                )
                if existing is None:
                    raise
                if not hmac.compare_digest(existing.fingerprint, fingerprint):
                    raise IdempotencyConflict()
                return existing.id, False
