"""Demo-data seed script (X5).

Builds a small, realistic salon-suite dataset by calling the REAL service
functions (auth / members / spaces / reservations / billing) — never by
inserting rows behind the service layer. That keeps the demo data honest to the
business rules (e.g. an ACTIVE member must carry a license + insurance, a
monthly billing run only invoices occupied suites) and makes this script a
living smoke test of the whole service stack.

Run it standalone against the real SQLite file:

    uv run python -m plume.seed

The ``__main__`` block initializes ``plume.db`` (``init_db(get_engine())``) and
seeds a fresh session, logging a one-line summary of what was created.

Idempotency: the seed is safe to re-run. It keys off the operator user
(``rory@plume.test``); if that user already exists the run is a no-op and every
count in the returned summary is ``0``. To reseed from scratch, delete
``plume.db`` first.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta

from sqlmodel import Session, select

from plume.auth.models import Role, User
from plume.auth.service import hash_password
from plume.billing.service import generate_monthly_invoices
from plume.db import get_engine, init_db
from plume.members.models import Status, Tier
from plume.members.service import onboard_member
from plume.reservations.service import reserve_station
from plume.spaces.service import add_station, add_suite, assign_suite, list_stations

logger = logging.getLogger(__name__)

# Demo-data sizing. Exposed as module constants so the tests assert against the
# same numbers the seed produces (single source of truth).
N_STATIONS = 8
N_SUITES = 6
N_SUITES_ASSIGNED = 2
N_MEMBERS = 5
N_RESERVATIONS = 4

OPERATOR_EMAIL = "rory@plume.test"
# Dev-only password for the demo operator. This is throwaway seed data for a
# local SQLite file, never a production credential.
OPERATOR_PASSWORD = "plume-dev"  # noqa: S105

# Billing period for the demo monthly run ("YYYY-MM").
BILLING_PERIOD = "2026-09"


def _empty_summary() -> dict[str, int]:
    return {
        "users": 0,
        "stations": 0,
        "suites": 0,
        "members": 0,
        "reservations": 0,
        "suite_invoices": 0,
    }


def seed(session: Session) -> dict[str, int]:
    """Populate ``session`` with demo data; return a count summary.

    Idempotent: if the demo operator already exists, nothing is created and a
    zero-filled summary is returned.
    """
    existing = session.exec(select(User).where(User.email == OPERATOR_EMAIL)).first()
    if existing is not None:
        logger.info("seed: operator %s already present — skipping (idempotent)", OPERATOR_EMAIL)
        return _empty_summary()

    summary = _empty_summary()

    # --- Operator user -------------------------------------------------------
    operator = User(
        email=OPERATOR_EMAIL,
        hashed_password=hash_password(OPERATOR_PASSWORD),
        role=Role.OPERATOR,
    )
    session.add(operator)
    session.commit()
    session.refresh(operator)
    summary["users"] += 1
    logger.info("seed: created operator user id=%s email=%s", operator.id, operator.email)

    # --- Stations (front-of-house, day-rentable) -----------------------------
    for i in range(1, N_STATIONS + 1):
        add_station(session, name=f"Chair {i}", notes="Demo station")
        summary["stations"] += 1

    # --- Suites (back-of-house, monthly) -------------------------------------
    suites = []
    for i in range(1, N_SUITES + 1):
        suite = add_suite(
            session,
            name=f"Suite {i}",
            monthly_rate=1200.0 + (i - 1) * 100.0,
            notes="Demo suite",
        )
        suites.append(suite)
        summary["suites"] += 1

    # --- Members (mix of lifecycle statuses) ---------------------------------
    # A blend of PROSPECT / ACTIVE / INACTIVE. ACTIVE members carry a license
    # number + insurance so they satisfy the onboarding rule (A3).
    member_specs = [
        ("Alex Rivera", "alex@plume.test", Status.ACTIVE, Tier.PRIVATE_STUDIO, True),
        ("Bianca Cole", "bianca@plume.test", Status.ACTIVE, Tier.PRIVATE_STUDIO, True),
        ("Cameron Diaz", "cameron@plume.test", Status.ACTIVE, Tier.OPEN_STUDIO, True),
        ("Dana Fox", "dana@plume.test", Status.PROSPECT, Tier.OPEN_STUDIO, False),
        ("Eli Grant", "eli@plume.test", Status.INACTIVE, Tier.OPEN_STUDIO, True),
    ]
    assert len(member_specs) == N_MEMBERS
    members = []
    for idx, (name, email, status, tier, complete) in enumerate(member_specs, start=1):
        member = onboard_member(
            session,
            name=name,
            email=email,
            phone=f"702-555-01{idx:02d}",
            license_number=(f"NV-COS-{1000 + idx}" if complete else None),
            license_expiry=(date.today() + timedelta(days=365) if complete else None),
            insurance_on_file=complete,
            tier=tier,
            status=status,
        )
        members.append(member)
        summary["members"] += 1

    # --- Assign a couple of suites to active private-studio members ----------
    active_members = [m for m in members if m.status == Status.ACTIVE]
    for suite, member in zip(
        suites[:N_SUITES_ASSIGNED], active_members[:N_SUITES_ASSIGNED], strict=True
    ):
        assert suite.id is not None
        assert member.id is not None
        assign_suite(session, suite.id, member.id)

    # --- Reservations (front day-rental) -------------------------------------
    # Book a handful of upcoming days for active members on the first stations.
    # Reservations are keyed by (station, date); vary both so none collide.
    stations = list_stations(session, active=True)
    tomorrow = date.today() + timedelta(days=1)
    for n in range(N_RESERVATIONS):
        member = active_members[n % len(active_members)]
        station = stations[n]
        assert member.id is not None
        assert station.id is not None
        reserve_station(session, member.id, station.id, tomorrow + timedelta(days=n))
        summary["reservations"] += 1

    # --- Monthly billing run -------------------------------------------------
    # One SUITE_RENT invoice per occupied suite for the demo period.
    invoices = generate_monthly_invoices(session, BILLING_PERIOD)
    summary["suite_invoices"] = len(invoices)

    logger.info(
        "seed: done users=%s stations=%s suites=%s members=%s reservations=%s suite_invoices=%s",
        summary["users"],
        summary["stations"],
        summary["suites"],
        summary["members"],
        summary["reservations"],
        summary["suite_invoices"],
    )
    return summary


def main() -> None:
    """Initialize the real DB and seed it, logging a summary."""
    from plume.logging_conf import configure_logging

    configure_logging()
    engine = get_engine()
    init_db(engine)
    with Session(engine) as session:
        summary = seed(session)
        logger.info("seed complete: %s", summary)
        print(f"Seed complete: {summary}")  # noqa: T201 — CLI feedback


if __name__ == "__main__":
    main()
