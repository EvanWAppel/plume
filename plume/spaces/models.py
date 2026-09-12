"""Space inventory models (Group B).

- ``Station``: front-of-house chairs booked per-day (S5). Extended with an
  optional ``notes`` field; ``Station(name=..., active=...)`` stays valid.
- ``Suite``: back-of-house monthly rooms holding at most one occupant.
"""

from __future__ import annotations

from sqlmodel import Field, SQLModel


class Station(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str
    active: bool = True
    notes: str | None = None


class Suite(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str
    active: bool = True
    notes: str | None = None
    monthly_rate: float = 0.0
    occupant_member_id: int | None = Field(default=None, foreign_key="member.id")
