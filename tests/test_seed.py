"""Tests for the demo-data seed script (X5).

The seed builds a small but realistic salon-suite dataset using the real
service functions, so this test doubles as an integration smoke of the whole
service layer. It runs ``seed(session)`` against the in-memory ``session``
fixture and asserts the expected row counts.
"""

from __future__ import annotations

from sqlmodel import Session, func, select

from plume.auth.models import Role, User
from plume.billing.models import Invoice, InvoiceKind
from plume.members.models import Member, Status
from plume.reservations.models import Reservation
from plume.seed import (
    N_MEMBERS,
    N_RESERVATIONS,
    N_STATIONS,
    N_SUITES,
    N_SUITES_ASSIGNED,
    seed,
)
from plume.spaces.models import Station, Suite


def _count(session: Session, model: type) -> int:
    return session.exec(select(func.count()).select_from(model)).one()


def test_seed_creates_expected_rows(session: Session) -> None:
    summary = seed(session)

    # One operator user for Rory.
    operators = session.exec(select(User).where(User.role == Role.OPERATOR)).all()
    assert len(operators) == 1
    assert operators[0].email == "rory@plume.test"

    assert _count(session, Station) == N_STATIONS
    assert _count(session, Suite) == N_SUITES
    assert _count(session, Member) == N_MEMBERS
    assert _count(session, Reservation) == N_RESERVATIONS

    # A couple of suites are assigned an occupant; the rest stay vacant.
    occupied = session.exec(
        select(Suite).where(Suite.occupant_member_id != None)  # noqa: E711
    ).all()
    assert len(occupied) == N_SUITES_ASSIGNED

    # The monthly billing run creates one SUITE_RENT invoice per occupied suite.
    suite_invoices = session.exec(
        select(Invoice).where(Invoice.kind == InvoiceKind.SUITE_RENT)
    ).all()
    assert len(suite_invoices) == N_SUITES_ASSIGNED

    # The returned summary reflects what landed in the DB.
    assert summary["users"] == 1
    assert summary["stations"] == N_STATIONS
    assert summary["suites"] == N_SUITES
    assert summary["members"] == N_MEMBERS
    assert summary["reservations"] == N_RESERVATIONS
    assert summary["suite_invoices"] == N_SUITES_ASSIGNED


def test_seed_mixes_member_statuses(session: Session) -> None:
    seed(session)

    statuses = {m.status for m in session.exec(select(Member)).all()}
    # Demo data should exercise more than one lifecycle state.
    assert Status.ACTIVE in statuses
    assert len(statuses) >= 2

    # Every ACTIVE member satisfies the onboarding rule (license + insurance).
    for member in session.exec(select(Member).where(Member.status == Status.ACTIVE)).all():
        assert member.license_number
        assert member.insurance_on_file


def test_seed_is_idempotent(session: Session) -> None:
    first = seed(session)
    second = seed(session)

    # A re-run detects existing data and creates nothing new.
    assert second == {k: 0 for k in first}
    # Counts are unchanged after the second run.
    assert _count(session, Member) == N_MEMBERS
    assert _count(session, Station) == N_STATIONS
