"""User model + role enum (E1).

A ``User`` is an authentication principal. Passwords are NEVER stored in the
clear — only the bcrypt hash produced by ``plume.auth.service.hash_password``
lands in ``hashed_password``. A user may optionally link to a ``Member`` row
(``member_id`` FK) when the principal is a stylist rather than the operator.
"""

from __future__ import annotations

import enum

from sqlmodel import Field, SQLModel


class Role(enum.StrEnum):
    """Authorization role. OPERATOR = salon owner/admin; MEMBER = stylist."""

    OPERATOR = "OPERATOR"
    MEMBER = "MEMBER"


class User(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    email: str = Field(unique=True, index=True)
    hashed_password: str
    role: Role = Field(default=Role.MEMBER)
    member_id: int | None = Field(default=None, foreign_key="member.id")
