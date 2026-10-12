"""One-off schema initialization with a separate administrator connection.

The runtime role receives only table DML permissions. Do not run this utility
inside a visitor request or pass administrator credentials to the API service.
"""

import asyncio
import os
import psycopg
from psycopg import sql
from .config import load_settings
from .database import Database


async def initialize():
    settings = load_settings()
    password = os.environ.get("APP_DB_PASSWORD", "")
    if len(password) < 64 or any(c not in "0123456789abcdef" for c in password):
        raise RuntimeError("APP_DB_PASSWORD must be a random 64-character hex value.")
    database = Database(settings)
    try:
        await database.initialize()
    finally:
        await database.close()
    url = settings.database_url.get_secret_value().replace(
        "postgresql+psycopg://", "postgresql://", 1
    )
    # Psycopg SQL composition quotes passwords safely; values are never logged.
    with psycopg.connect(url, connect_timeout=5) as connection:
        with connection.cursor() as cursor:
            exists = cursor.execute(
                "SELECT 1 FROM pg_roles WHERE rolname=%s", ("blueeye_app",)
            ).fetchone()
            if not exists:
                cursor.execute("CREATE ROLE blueeye_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE")
            cursor.execute(
                sql.SQL("ALTER ROLE blueeye_app PASSWORD {}").format(sql.Literal(password))
            )
            cursor.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
            cursor.execute("GRANT USAGE ON SCHEMA public TO blueeye_app")
            cursor.execute(
                "GRANT SELECT,INSERT,UPDATE,DELETE ON enquiries,notification_outbox TO blueeye_app"
            )
    print("Schema ready; runtime role has table permissions only.")


if __name__ == "__main__":
    asyncio.run(initialize())
