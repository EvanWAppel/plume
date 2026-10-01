"""Persistence models for community events, RSVPs, and gallery art."""

from datetime import datetime as datetime_type
from enum import StrEnum

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, Relationship, SQLModel


class Event(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    title: str
    datetime: datetime_type = Field(index=True)
    capacity: int = Field(gt=0)
    rsvps: list["EventRSVP"] = Relationship(
        back_populates="event",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )


class EventRSVP(SQLModel, table=True):
    __table_args__ = (UniqueConstraint("event_id", "email", name="uq_event_rsvp_email"),)

    id: int | None = Field(default=None, primary_key=True)
    event_id: int = Field(foreign_key="event.id", index=True)
    name: str
    email: str
    event: Event | None = Relationship(back_populates="rsvps")


class ArtStatus(StrEnum):
    ON_DISPLAY = "ON_DISPLAY"
    SOLD = "SOLD"


class ArtPiece(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    artist: str
    title: str
    price: float = Field(ge=0)
    commission_percent: float = Field(ge=0, le=100)
    status: ArtStatus = Field(default=ArtStatus.ON_DISPLAY, index=True)
    salon_commission: float | None = None
    artist_payout: float | None = None
