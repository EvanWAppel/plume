"""Group D — Memberships & billing tests (TDD-first).

Covers:
- D1: Invoice model persists; status/kind enums validate.
- D2: generate_monthly_invoices — one SUITE_RENT invoice per occupied suite,
  idempotent per period, vacant suites skipped.
- D3: charge_day_rates — counts a member's reservations in a period and creates
  a DAY_RATE invoice of count * day_rate.
- D4: mark_paid / void_invoice with legal transitions; illegal → raises.
- D5: router — /billing/run, /invoices filters, /invoices/{id}/pay, and the
  operator guard on write endpoints.

Router tests spin up a LOCAL app, override ``get_session`` with the shared
``session`` fixture, and bypass ``require_operator`` (per Group D test contract)
so unit tests stay focused. A dedicated test uses the REAL guard to prove
non-operators are rejected.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import date

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from plume.auth.models import Role, User
from plume.auth.service import require_operator
from plume.billing.models import Invoice, InvoiceKind, InvoiceStatus
from plume.billing.router import router as billing_router
from plume.billing.service import (
    InvalidInvoiceTransitionError,
    InvoiceNotFoundError,
    charge_day_rates,
    generate_monthly_invoices,
    list_invoices,
    mark_paid,
    void_invoice,
)
from plume.db import get_session
from plume.members.models import Member
from plume.reservations.models import Reservation
from plume.spaces.models import Station, Suite

PERIOD = "2026-09"


# --- local app fixtures (router tests) --------------------------------------


@pytest.fixture
def billing_app(session: Session) -> FastAPI:
    """A minimal app mounting only the billing router, wired to the test session
    and with the operator guard bypassed."""
    app = FastAPI()
    app.include_router(billing_router)

    def override_get_session() -> Iterator[Session]:
        yield session

    app.dependency_overrides[get_session] = override_get_session
    app.dependency_overrides[require_operator] = lambda: User(
        email="op@test", hashed_password="x", role=Role.OPERATOR
    )
    return app


@pytest.fixture
def billing_client(billing_app: FastAPI) -> Iterator[TestClient]:
    with TestClient(billing_app) as test_client:
        yield test_client


# --- D1: model persistence + enum validation --------------------------------


def test_invoice_persists(session: Session) -> None:
    invoice = Invoice(
        member_id=1,
        period=PERIOD,
        amount=1200.0,
        status=InvoiceStatus.DRAFT,
        kind=InvoiceKind.SUITE_RENT,
    )
    session.add(invoice)
    session.commit()
    session.refresh(invoice)

    assert invoice.id is not None
    loaded = session.get(Invoice, invoice.id)
    assert loaded is not None
    assert loaded.member_id == 1
    assert loaded.period == PERIOD
    assert loaded.amount == 1200.0
    assert loaded.status is InvoiceStatus.DRAFT
    assert loaded.kind is InvoiceKind.SUITE_RENT


def test_invoice_status_defaults_to_draft(session: Session) -> None:
    invoice = Invoice(member_id=1, period=PERIOD, amount=10.0, kind=InvoiceKind.OTHER)
    session.add(invoice)
    session.commit()
    session.refresh(invoice)
    assert invoice.status is InvoiceStatus.DRAFT


def test_invoice_enums_validate() -> None:
    assert InvoiceStatus("PAID") is InvoiceStatus.PAID
    assert InvoiceKind("DAY_RATE") is InvoiceKind.DAY_RATE
    with pytest.raises(ValueError):
        InvoiceStatus("NOPE")
    with pytest.raises(ValueError):
        InvoiceKind("NOPE")


# --- D2: generate_monthly_invoices ------------------------------------------


def _occupy(session: Session, suite: Suite, member_id: int) -> None:
    suite.occupant_member_id = member_id
    session.add(suite)
    session.commit()
    session.refresh(suite)


def test_generate_one_invoice_per_occupied_suite(
    session: Session, make_suite: Callable[..., Suite], make_member: Callable[..., Member]
) -> None:
    m1 = make_member(email="a@x.com")
    m2 = make_member(email="b@x.com")
    assert m1.id is not None
    assert m2.id is not None
    s1 = make_suite(name="S1", monthly_rate=1400.0)
    s2 = make_suite(name="S2", monthly_rate=1200.0)
    _occupy(session, s1, m1.id)
    _occupy(session, s2, m2.id)

    invoices = generate_monthly_invoices(session, PERIOD)

    assert len(invoices) == 2
    amounts = sorted(inv.amount for inv in invoices)
    assert amounts == [1200.0, 1400.0]
    assert all(inv.kind is InvoiceKind.SUITE_RENT for inv in invoices)
    assert all(inv.period == PERIOD for inv in invoices)
    assert all(inv.status is InvoiceStatus.DRAFT for inv in invoices)


def test_generate_skips_vacant_suites(
    session: Session, make_suite: Callable[..., Suite], make_member: Callable[..., Member]
) -> None:
    m1 = make_member(email="a@x.com")
    assert m1.id is not None
    occupied = make_suite(name="Occupied", monthly_rate=1400.0)
    make_suite(name="Vacant", monthly_rate=1000.0)  # no occupant
    _occupy(session, occupied, m1.id)

    invoices = generate_monthly_invoices(session, PERIOD)

    assert len(invoices) == 1
    assert invoices[0].amount == 1400.0


def test_generate_is_idempotent_per_period(
    session: Session, make_suite: Callable[..., Suite], make_member: Callable[..., Member]
) -> None:
    m1 = make_member(email="a@x.com")
    assert m1.id is not None
    s1 = make_suite(name="S1", monthly_rate=1400.0)
    _occupy(session, s1, m1.id)

    first = generate_monthly_invoices(session, PERIOD)
    second = generate_monthly_invoices(session, PERIOD)

    assert len(first) == 1
    assert len(second) == 0  # rerun creates none
    total = session.exec(select(Invoice).where(Invoice.kind == InvoiceKind.SUITE_RENT)).all()
    assert len(total) == 1


def test_generate_distinct_periods_do_not_collide(
    session: Session, make_suite: Callable[..., Suite], make_member: Callable[..., Member]
) -> None:
    m1 = make_member(email="a@x.com")
    assert m1.id is not None
    s1 = make_suite(name="S1", monthly_rate=1400.0)
    _occupy(session, s1, m1.id)

    generate_monthly_invoices(session, "2026-09")
    october = generate_monthly_invoices(session, "2026-10")

    assert len(october) == 1
    total = session.exec(select(Invoice)).all()
    assert len(total) == 2


# --- D3: day-rate rollup ----------------------------------------------------


def test_charge_day_rates_counts_reservations_in_period(
    session: Session,
    make_member: Callable[..., Member],
    make_station: Callable[..., Station],
) -> None:
    member = make_member(email="dr@x.com")
    station = make_station()
    assert member.id is not None
    assert station.id is not None
    member_id = member.id
    station_id = station.id

    # 3 reservations in September, 1 in October (excluded), 1 for another member.
    for day in (1, 15, 30):
        session.add(
            Reservation(member_id=member_id, station_id=station_id, date=date(2026, 9, day))
        )
    session.add(Reservation(member_id=member_id, station_id=station_id, date=date(2026, 10, 1)))
    other = make_member(email="other@x.com")
    assert other.id is not None
    session.add(Reservation(member_id=other.id, station_id=station_id, date=date(2026, 9, 5)))
    session.commit()

    invoice = charge_day_rates(session, member_id, PERIOD, day_rate=55.0)

    assert invoice.amount == 3 * 55.0
    assert invoice.kind is InvoiceKind.DAY_RATE
    assert invoice.member_id == member_id
    assert invoice.period == PERIOD


def test_charge_day_rates_zero_reservations(
    session: Session, make_member: Callable[..., Member]
) -> None:
    member = make_member(email="none@x.com")
    assert member.id is not None
    invoice = charge_day_rates(session, member.id, PERIOD, day_rate=55.0)
    assert invoice.amount == 0.0
    assert invoice.kind is InvoiceKind.DAY_RATE


# --- D4: transitions --------------------------------------------------------


def _draft_invoice(session: Session) -> Invoice:
    invoice = Invoice(member_id=1, period=PERIOD, amount=100.0, kind=InvoiceKind.OTHER)
    session.add(invoice)
    session.commit()
    session.refresh(invoice)
    return invoice


def test_mark_paid_transitions(session: Session) -> None:
    invoice = _draft_invoice(session)
    assert invoice.id is not None
    paid = mark_paid(session, invoice.id)
    assert paid.status is InvoiceStatus.PAID


def test_void_invoice_transitions(session: Session) -> None:
    invoice = _draft_invoice(session)
    assert invoice.id is not None
    voided = void_invoice(session, invoice.id)
    assert voided.status is InvoiceStatus.VOID


def test_cannot_pay_a_void_invoice(session: Session) -> None:
    invoice = _draft_invoice(session)
    assert invoice.id is not None
    void_invoice(session, invoice.id)
    with pytest.raises(InvalidInvoiceTransitionError):
        mark_paid(session, invoice.id)


def test_cannot_void_a_paid_invoice(session: Session) -> None:
    invoice = _draft_invoice(session)
    assert invoice.id is not None
    mark_paid(session, invoice.id)
    with pytest.raises(InvalidInvoiceTransitionError):
        void_invoice(session, invoice.id)


def test_mark_paid_unknown_invoice_raises(session: Session) -> None:
    with pytest.raises(InvoiceNotFoundError):
        mark_paid(session, 9999)


def test_list_invoices_filters(session: Session, make_member: Callable[..., Member]) -> None:
    m = make_member(email="f@x.com")
    assert m.id is not None
    mid = m.id
    session.add(Invoice(member_id=mid, period=PERIOD, amount=10.0, kind=InvoiceKind.OTHER))
    session.add(
        Invoice(
            member_id=mid,
            period=PERIOD,
            amount=20.0,
            kind=InvoiceKind.OTHER,
            status=InvoiceStatus.PAID,
        )
    )
    session.add(Invoice(member_id=999, period=PERIOD, amount=30.0, kind=InvoiceKind.OTHER))
    session.commit()

    by_member = list_invoices(session, member_id=mid)
    assert len(by_member) == 2
    paid = list_invoices(session, status=InvoiceStatus.PAID)
    assert len(paid) == 1
    assert paid[0].amount == 20.0
    both = list_invoices(session, member_id=mid, status=InvoiceStatus.PAID)
    assert len(both) == 1


# --- D5: router -------------------------------------------------------------


def test_run_endpoint_generates_invoices(
    billing_client: TestClient,
    session: Session,
    make_suite: Callable[..., Suite],
    make_member: Callable[..., Member],
) -> None:
    m1 = make_member(email="run@x.com")
    assert m1.id is not None
    s1 = make_suite(name="S1", monthly_rate=1400.0)
    _occupy(session, s1, m1.id)

    resp = billing_client.post(f"/billing/run?period={PERIOD}")
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert len(body) == 1
    assert body[0]["amount"] == 1400.0
    assert body[0]["kind"] == "SUITE_RENT"


def test_list_invoices_endpoint_filters(
    billing_client: TestClient, session: Session, make_member: Callable[..., Member]
) -> None:
    m = make_member(email="le@x.com")
    assert m.id is not None
    mid = m.id
    session.add(Invoice(member_id=mid, period=PERIOD, amount=10.0, kind=InvoiceKind.OTHER))
    session.add(Invoice(member_id=999, period=PERIOD, amount=30.0, kind=InvoiceKind.OTHER))
    session.commit()

    resp = billing_client.get(f"/invoices?member_id={mid}")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body) == 1
    assert body[0]["member_id"] == mid


def test_pay_endpoint_transitions(billing_client: TestClient, session: Session) -> None:
    invoice = _draft_invoice(session)
    assert invoice.id is not None

    resp = billing_client.post(f"/invoices/{invoice.id}/pay")
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "PAID"


def test_pay_void_invoice_returns_409(billing_client: TestClient, session: Session) -> None:
    invoice = _draft_invoice(session)
    assert invoice.id is not None
    void_invoice(session, invoice.id)

    resp = billing_client.post(f"/invoices/{invoice.id}/pay")
    assert resp.status_code == 409, resp.text


def test_pay_unknown_invoice_returns_404(billing_client: TestClient) -> None:
    resp = billing_client.post("/invoices/424242/pay")
    assert resp.status_code == 404, resp.text


def test_write_endpoint_rejects_non_operator(session: Session) -> None:
    """Dedicated guard test: with the REAL require_operator in place (not
    bypassed) and no token, the write endpoint must be rejected (401/403)."""
    app = FastAPI()
    app.include_router(billing_router)

    def override_get_session() -> Iterator[Session]:
        yield session

    app.dependency_overrides[get_session] = override_get_session
    # NOTE: require_operator is NOT overridden here — the real guard runs.
    with TestClient(app) as guarded_client:
        resp = guarded_client.post(f"/billing/run?period={PERIOD}")
    assert resp.status_code in (401, 403), resp.text
