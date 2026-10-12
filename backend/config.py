"""Typed configuration; production mistakes fail before serving traffic."""

from pathlib import Path
from urllib.parse import urlsplit
from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    app_env: str = "development"
    public_origin: str = "http://localhost:8000"
    database_url: SecretStr = SecretStr("sqlite+aiosqlite:///./data/dev.sqlite3")
    redis_url: SecretStr = SecretStr("redis://localhost:6379/0")
    signing_secret: SecretStr = SecretStr("development-only-change-before-production")
    public_dir: Path = Path(__file__).resolve().parents[1] / "public"
    db_pool_size: int = Field(default=10, ge=1, le=50)
    db_max_overflow: int = Field(default=5, ge=0, le=30)
    per_ip_limit: int = Field(default=10, ge=1, le=100)
    global_limit: int = Field(default=1000, ge=100, le=10000)
    retention_days: int = Field(default=180, ge=1, le=365)
    smtp_host: str = ""
    smtp_port: int = Field(default=465, ge=1, le=65535)
    smtp_username: str = ""
    smtp_password: SecretStr = SecretStr("")
    smtp_sender: str = "info@blueeyemedia.in"
    notification_recipient: str = "info@blueeyemedia.in"
    smtp_starttls: bool = False

    @model_validator(mode="after")
    def check_configuration(self):
        origin = urlsplit(self.public_origin)
        if origin.path not in ("", "/") or origin.query or origin.fragment:
            raise ValueError("PUBLIC_ORIGIN must be an origin without a path.")
        if origin.username or origin.password or not origin.hostname:
            raise ValueError("Invalid PUBLIC_ORIGIN.")
        if self.app_env not in {"development", "test", "production"}:
            raise ValueError("Unsupported APP_ENV.")
        self.public_origin = self.public_origin.rstrip("/")
        if self.app_env == "production":
            secret = self.signing_secret.get_secret_value()
            if origin.scheme != "https" or origin.hostname.endswith(".example"):
                raise ValueError("Production requires a real HTTPS origin.")
            if len(secret) < 64 or any(c not in "0123456789abcdef" for c in secret):
                raise ValueError("SIGNING_SECRET must be 64 or more random hex characters.")
            if not self.database_url.get_secret_value().startswith("postgresql+psycopg://"):
                raise ValueError("Production requires PostgreSQL.")
            if "REPLACE" in self.database_url.get_secret_value():
                raise ValueError("Replace the example database password.")
            if "REPLACE" in self.redis_url.get_secret_value():
                raise ValueError("Replace the example Redis password.")
            for service_url in (self.database_url, self.redis_url):
                password = urlsplit(service_url.get_secret_value()).password or ""
                if len(password) < 64 or any(c not in "0123456789abcdef" for c in password):
                    raise ValueError("Production service passwords must be random hex secrets.")
        for address in (self.smtp_sender, self.notification_recipient):
            if "\r" in address or "\n" in address:
                raise ValueError("Mail addresses cannot contain newlines.")
        return self

    @property
    def hostname(self) -> str:
        return urlsplit(self.public_origin).hostname or "localhost"


def load_settings() -> Settings:
    """Never let Pydantic's raw configuration input appear in startup logs."""
    from pydantic import ValidationError

    try:
        return Settings()
    except ValidationError:
        raise RuntimeError(
            "Invalid configuration. Review .env against .env.example; secrets are not logged."
        ) from None
