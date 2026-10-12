"""Private maintenance commands. No operator endpoints are public."""

import argparse
import asyncio
import json
from datetime import timedelta
from uuid import UUID
from sqlalchemy import delete, select, update
from .config import load_settings
from .database import Database, Enquiry, Outbox, utcnow


async def execute(args):
    settings = load_settings()
    db = Database(settings)
    try:
        if args.command == "init-db":
            await db.initialize()
            print("Schema initialized. Use versioned migrations for future schema changes.")
            return
        async with db.sessions() as session:
            if args.command == "list":
                rows = (
                    await session.scalars(
                        select(Enquiry).order_by(Enquiry.created_at.desc()).limit(args.limit)
                    )
                ).all()
                for row in rows:
                    print(
                        json.dumps(
                            {"id": row.id, "created_at": row.created_at.isoformat(), **row.payload},
                            ensure_ascii=False,
                        )
                    )
            elif args.command == "purge":
                cutoff = utcnow() - timedelta(days=settings.retention_days)
                identifiers = select(Enquiry.id).where(Enquiry.created_at < cutoff)
                await session.execute(delete(Outbox).where(Outbox.enquiry_id.in_(identifiers)))
                result = await session.execute(delete(Enquiry).where(Enquiry.created_at < cutoff))
                await session.commit()
                print(f"Deleted {result.rowcount} expired enquiries.")
            elif args.command == "delete":
                identifier = str(UUID(args.id))
                await session.execute(delete(Outbox).where(Outbox.enquiry_id == identifier))
                result = await session.execute(delete(Enquiry).where(Enquiry.id == identifier))
                await session.commit()
                print(f"Deleted {result.rowcount} enquiries.")
            elif args.command == "queue-status":
                from sqlalchemy import func

                rows = await session.execute(
                    select(Outbox.status, func.count()).group_by(Outbox.status)
                )
                print(json.dumps(dict(rows.all())))
            elif args.command == "retry-failed":
                result = await session.execute(
                    update(Outbox)
                    .where(Outbox.status == "failed")
                    .values(status="pending", attempts=0, available_at=utcnow(), last_error=None)
                )
                await session.commit()
                print(f"Requeued {result.rowcount} failed notifications.")
    finally:
        await db.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command", choices=["init-db", "list", "purge", "delete", "queue-status", "retry-failed"]
    )
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--id", default="")
    args = parser.parse_args()
    if not 1 <= args.limit <= 1000:
        parser.error("--limit must be between 1 and 1000")
    if args.command == "delete" and not args.id:
        parser.error("delete requires --id UUID")
    asyncio.run(execute(args))


if __name__ == "__main__":
    main()
