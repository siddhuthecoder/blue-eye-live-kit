"""Strict bounded input; validation never reflects personal data in errors."""

import unicodedata
from datetime import date, datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

Service = Literal[
    "Brand & Identity",
    "Social Media",
    "Content & Production",
    "Digital Marketing",
    "Growth Strategy",
    "Web & Digital",
    "Integrated support",
]
Slot = Literal[
    "10:00", "10:30", "11:00", "11:30", "12:00", "14:30", "15:00", "15:30", "16:00", "16:30"
]


class EnquiryInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=2, max_length=100, strict=True)
    company: str = Field(min_length=2, max_length=160, strict=True)
    email: EmailStr = Field(max_length=254)
    phone: str = Field(default="", max_length=40, strict=True)
    service: Service
    consultationDate: date
    consultationTime: Slot
    message: str = Field(default="", max_length=3000, strict=True)
    website: str = Field(default="", max_length=200, strict=True)

    @field_validator("name", "company", "phone", "message", "website", mode="before")
    @classmethod
    def normalize_text(cls, value):
        if not isinstance(value, str):
            raise ValueError("Text required.")
        # Reject excessive raw input even when normalization would shrink it.
        if len(value) > 4000:
            raise ValueError("Text too long.")
        if any(unicodedata.category(c) == "Cc" and c not in "\n\r\t" for c in value):
            raise ValueError("Control characters not allowed.")
        return unicodedata.normalize("NFC", value)

    @field_validator("consultationDate", mode="before")
    @classmethod
    def date_format(cls, value):
        import re

        if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            raise ValueError("Use YYYY-MM-DD.")
        return value

    @model_validator(mode="after")
    def validate_request(self):
        if self.website:
            raise ValueError("Submission rejected.")
        now = datetime.now(ZoneInfo("Asia/Kolkata"))
        preferred = datetime.fromisoformat(f"{self.consultationDate}T{self.consultationTime}")
        preferred = preferred.replace(tzinfo=ZoneInfo("Asia/Kolkata"))
        if not now < preferred <= now + timedelta(days=180):
            raise ValueError("Choose a future IST time within 180 days.")
        return self

    def stored_payload(self) -> dict:
        return self.model_dump(mode="json", exclude={"website"})
