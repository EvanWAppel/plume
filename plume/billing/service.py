"""Billing business rules (Group D — D2/D3/D4).

Errors are raised, never swallowed — the router (D5) translates them to HTTP
status codes at the boundary. Logging marks each decision point.

Note on cross-package reads: for the day-rate rollup (D3) we query the
``Reservation`` model DIRECTLY rather than calling Group C's service functions,
which are in flux.
"""

from __future__ import annotations

import logging
from datetime import date

from sqlmodel import Session, select

from plume.billing.models import Invoice, InvoiceKind, InvoiceStatus
from plume.reservations.models import Reservation
from plume.spaces.models import Suite

logger = logging.getLogger(__name__)


class InvoiceNotFoundError(Exception):
    """No invoice exists with the requested id."""


class InvalidInvoiceTransitionError(Exception):
    """An invoice cannot move from its current status to the requested one."""


# --- period helpers ---------------------------------------------------------


def _period_bounds(period: str) -> tuple[date, date]:
    """Return the ``[start, end)`` date range for a ``"YYYY-MM"`` period.

    ``start`` is the first of the month; ``end`` is the first of the following
    month (exclusive), so a half-open range cleanly captures every day.
    """
    year_str, month_str = period.split("-")
    year, month = int(year_str), int(month_str)
    start = date(year, month, 1)
    if month == 12:
        end = date(year + 1, 1, 1)
    else:
        end = date(year, month + 1, 1)
    return start, end


# --- D2: monthly suite-rent invoices ----------------------------------------


def generate_monthly_invoices(session: Session, period: str) -> list[Invoice]:
    """Create one ``SUITE_RENT`` invoice per OCCUPIED suite for ``period``.

    Idempotent per period: a suite that already has a ``SUITE_RENT`` invoice for
    this ``period`` (keyed by occupant member) is skipped, so re-running never
    duplicates. Vacant suites (no ``occupant_member_id``) are skipped. Returns
    only the invoices created on THIS call.
    """
    occupied = session.exec(
        select(Suite).where(Suite.occupant_member_id != None)  # noqa: E711
    ).all()

    created: list[Invoice] = []
    for suite in occupied:
        member_id = suite.occupant_member_id
        if member_id is None:  # defensive; the query already filtered these out
            continue
        existing = session.exec(
            select(Invoice)
            .where(Invoice.member_id == member_id)
            .where(Invoice.period == period)
            .where(Invoice.kind == InvoiceKind.SUITE_RENT)
        ).first()
        if existing is not None:
            logger.info(
                "generate_monthly_invoices: skip existing suite=%s member=%s period=%s",
                suite.id,
                member_id,
                period,
            )
            continue
        invoice = Invoice(
            member_id=member_id,
            period=period,
            amount=suite.monthly_rate,
            kind=InvoiceKind.SUITE_RENT,
            status=InvoiceStatus.DRAFT,
        )
        session.add(invoice)
        created.append(invoice)
        logger.info(
            "generate_monthly_invoices: create suite=%s member=%s period=%s amount=%s",
            suite.id,
            member_id,
            period,
            suite.monthly_rate,
        )

    session.commit()
    for invoice in created:
        session.refresh(invoice)
    logger.info(
        "generate_monthly_invoices: period=%s occupied=%s created=%s",
        period,
        len(occupied),
        len(created),
    )
    return created


# --- D3: day-rate rollup ----------------------------------------------------


def charge_day_rates(session: Session, member_id: int, period: str, day_rate: float) -> Invoice:
    """Roll a member's reservations within ``period`` into a ``DAY_RATE`` invoice.

    Counts the member's ``Reservation`` rows whose ``date`` falls in the period
    month and creates a single ``DAY_RATE`` invoice of ``count * day_rate``.
    """
    start, end = _period_bounds(period)
    count = len(
        session.exec(
            select(Reservation)
            .where(Reservation.member_id == member_id)
            .where(Reservation.date >= start)
            .where(Reservation.date < end)
        ).all()
    )
    amount = count * day_rate
    invoice = Invoice(
        member_id=member_id,
        period=period,
        amount=amount,
        kind=InvoiceKind.DAY_RATE,
        status=InvoiceStatus.DRAFT,
    )
    session.add(invoice)
    session.commit()
    session.refresh(invoice)
    logger.info(
        "charge_day_rates: member=%s period=%s count=%s rate=%s amount=%s",
        member_id,
        period,
        count,
        day_rate,
        amount,
    )
    return invoice


# --- D4: state transitions --------------------------------------------------


def _get_invoice(session: Session, invoice_id: int) -> Invoice:
    invoice = session.get(Invoice, invoice_id)
    if invoice is None:
        logger.info("invoice miss: id=%s", invoice_id)
        raise InvoiceNotFoundError(f"invoice {invoice_id} not found")
    return invoice


def mark_paid(session: Session, invoice_id: int) -> Invoice:
    """Move an invoice to ``PAID``. A VOID invoice cannot be paid."""
    invoice = _get_invoice(session, invoice_id)
    if invoice.status is InvoiceStatus.VOID:
        logger.info("mark_paid: illegal VOID→PAID for id=%s", invoice_id)
        raise InvalidInvoiceTransitionError(f"cannot pay a VOID invoice {invoice_id}")
    invoice.status = InvoiceStatus.PAID
    session.add(invoice)
    session.commit()
    session.refresh(invoice)
    logger.info("mark_paid: id=%s", invoice_id)
    return invoice


def void_invoice(session: Session, invoice_id: int) -> Invoice:
    """Move an invoice to ``VOID``. A PAID invoice cannot be voided."""
    invoice = _get_invoice(session, invoice_id)
    if invoice.status is InvoiceStatus.PAID:
        logger.info("void_invoice: illegal PAID→VOID for id=%s", invoice_id)
        raise InvalidInvoiceTransitionError(f"cannot void a PAID invoice {invoice_id}")
    invoice.status = InvoiceStatus.VOID
    session.add(invoice)
    session.commit()
    session.refresh(invoice)
    logger.info("void_invoice: id=%s", invoice_id)
    return invoice


# --- listing ----------------------------------------------------------------


def list_invoices(
    session: Session,
    *,
    member_id: int | None = None,
    status: InvoiceStatus | None = None,
) -> list[Invoice]:
    """Return invoices, optionally filtered by ``member_id`` and/or ``status``."""
    statement = select(Invoice)
    if member_id is not None:
        statement = statement.where(Invoice.member_id == member_id)
    if status is not None:
        statement = statement.where(Invoice.status == status)
    return list(session.exec(statement).all())
