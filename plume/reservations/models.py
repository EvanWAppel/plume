"""Reservation model (S5): a member holds a station for a given date."""

from __future__ import annotations

from datetime import date as date_type

from sqlmodel import Field, SQLModel


class Reservation(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    member_id: int = Field(foreign_key="member.id", index=True)
    station_id: int = Field(foreign_key="station.id", index=True)
    date: date_type = Field(index=True)
