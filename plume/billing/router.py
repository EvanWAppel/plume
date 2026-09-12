"""Billing API (Group D — D5).

- ``POST /billing/run?period=`` (operator-guarded): generate suite-rent invoices.
- ``GET /invoices?member_id=&status=`` (read, open): list/filter invoices.
- ``POST /invoices/{id}/pay`` (operator-guarded): transition an invoice to PAID.

Domain errors from the service are translated to HTTP status codes here at the
boundary — messages preserved, causes chained, nothing swallowed.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlmodel import Session

from plume.auth.models import User
from plume.auth.service import require_operator
from plume.billing.models import Invoice, InvoiceStatus
from plume.billing.service import (
    InvalidInvoiceTransitionError,
    InvoiceNotFoundError,
    generate_monthly_invoices,
    list_invoices,
    mark_paid,
)
from plume.db import get_session

logger = logging.getLogger(__name__)

router = APIRouter(tags=["billing"])


@router.post("/billing/run", status_code=status.HTTP_201_CREATED)
def run_billing(
    period: str = Query(...),
    session: Session = Depends(get_session),
    _op: User = Depends(require_operator),
) -> list[Invoice]:
    """Generate this period's suite-rent invoices (idempotent per period)."""
    return generate_monthly_invoices(session, period)


@router.get("/invoices")
def get_invoices(
    member_id: int | None = Query(default=None),
    status: InvoiceStatus | None = Query(default=None),
    session: Session = Depends(get_session),
) -> list[Invoice]:
    return list_invoices(session, member_id=member_id, status=status)


@router.post("/invoices/{invoice_id}/pay")
def pay_invoice(
    invoice_id: int,
    session: Session = Depends(get_session),
    _op: User = Depends(require_operator),
) -> Invoice:
    try:
        return mark_paid(session, invoice_id)
    except InvoiceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except InvalidInvoiceTransitionError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
