"""Billing models + enums (Group D — D1).

An ``Invoice`` is a single charge against a member for a billing ``period``
(``"YYYY-MM"``). ``kind`` records what it bills for (suite rent, day rates,
retail, other); ``status`` tracks its lifecycle (draft → sent → paid, or void).

Enums subclass ``str`` (``StrEnum``) so they serialize cleanly to JSON and
persist as plain strings in SQLite, matching the pattern in
``plume.members.models`` and ``plume.auth.models``.
"""

from __future__ import annotations

from enum import StrEnum

from sqlmodel import Field, SQLModel


class InvoiceStatus(StrEnum):
    """Lifecycle of an invoice."""

    DRAFT = "DRAFT"
    SENT = "SENT"
    PAID = "PAID"
    VOID = "VOID"


class InvoiceKind(StrEnum):
    """What the invoice bills for."""

    SUITE_RENT = "SUITE_RENT"
    DAY_RATE = "DAY_RATE"
    RETAIL = "RETAIL"
    OTHER = "OTHER"


class Invoice(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    member_id: int = Field(foreign_key="member.id", index=True)
    period: str = Field(index=True)  # e.g. "2026-09"
    amount: float = 0.0
    status: InvoiceStatus = Field(default=InvoiceStatus.DRAFT)
    kind: InvoiceKind = Field(default=InvoiceKind.OTHER)


class LineItem(SQLModel, table=True):
    """Optional per-line breakdown belonging to an ``Invoice``.

    Not required by the current service layer (invoices carry a single
    ``amount``), but modeled so future itemization (retail SKUs, per-day-rate
    lines) has a home without a schema migration.
    """

    id: int | None = Field(default=None, primary_key=True)
    invoice_id: int = Field(foreign_key="invoice.id", index=True)
    description: str = ""
    quantity: float = 1.0
    unit_amount: float = 0.0
