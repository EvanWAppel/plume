"""Member model + enums (S5 → Group A A1).

Backward compatible: ``Member(name=..., email=...)`` still works — every new
field carries a default. Enums subclass ``str`` so they serialize cleanly to
JSON and persist as plain strings in SQLite.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from enum import StrEnum

from sqlalchemy import DateTime
from sqlalchemy.engine import Dialect
from sqlalchemy.types import TypeDecorator
from sqlmodel import Field, SQLModel


class UTCDateTime(TypeDecorator[datetime]):
    """Store datetimes as UTC and always return them timezone-aware.

    SQLite has no native timezone support, so a plain ``DateTime`` column
    round-trips to a naive value. This decorator normalizes any aware value to
    UTC on write and re-attaches ``UTC`` on read, giving consistent tz-aware
    ``datetime`` objects across drivers.
    """

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


class Tier(StrEnum):
    """Which kind of space the member rents."""

    OPEN_STUDIO = "OPEN_STUDIO"
    PRIVATE_STUDIO = "PRIVATE_STUDIO"


class Status(StrEnum):
    """Lifecycle of a member/stylist relationship."""

    PROSPECT = "PROSPECT"
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


def _utcnow() -> datetime:
    """Timezone-aware 'now' factory (kept small so ``default_factory`` is a name)."""
    return datetime.now(UTC)


class Member(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str
    email: str
    phone: str | None = None
    license_number: str | None = None
    license_expiry: date | None = None
    insurance_on_file: bool = False
    tier: Tier = Field(default=Tier.OPEN_STUDIO)
    status: Status = Field(default=Status.PROSPECT)
    created_at: datetime = Field(default_factory=_utcnow, sa_type=UTCDateTime)
