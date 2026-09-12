"""Shared test fixtures (S4, extended during integration).

An in-memory SQLite engine with a StaticPool (single shared connection) so the
test's own writes and the app's request-time reads see the same data. The
``client`` fixture overrides ``get_session`` to reuse the test's session.

Factories (``make_member``/``make_station``/``make_suite``/``make_user``) and the
``operator_token``/``member_token`` fixtures are the DRY seed layer every group's
tests build on.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, create_engine

from plume.auth.models import Role, User
from plume.auth.service import create_access_token, hash_password
from plume.db import get_session, init_db
from plume.main import app
from plume.members.models import Member, Status, Tier
from plume.spaces.models import Station, Suite


@pytest.fixture
def engine() -> Engine:
    eng = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    init_db(eng)
    return eng


@pytest.fixture
def session(engine: Engine) -> Iterator[Session]:
    with Session(engine) as sess:
        yield sess


@pytest.fixture
def client(session: Session) -> Iterator[TestClient]:
    def override_get_session() -> Iterator[Session]:
        yield session

    app.dependency_overrides[get_session] = override_get_session
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def make_member(session: Session) -> Callable[..., Member]:
    def _make(
        name: str = "Rory",
        email: str = "rory@example.com",
        *,
        phone: str | None = None,
        license_number: str | None = None,
        license_expiry: date | None = None,
        insurance_on_file: bool = False,
        tier: Tier = Tier.OPEN_STUDIO,
        status: Status = Status.PROSPECT,
    ) -> Member:
        member = Member(
            name=name,
            email=email,
            phone=phone,
            license_number=license_number,
            license_expiry=license_expiry,
            insurance_on_file=insurance_on_file,
            tier=tier,
            status=status,
        )
        session.add(member)
        session.commit()
        session.refresh(member)
        return member

    return _make


@pytest.fixture
def make_station(session: Session) -> Callable[..., Station]:
    def _make(name: str = "Chair 1", active: bool = True) -> Station:
        station = Station(name=name, active=active)
        session.add(station)
        session.commit()
        session.refresh(station)
        return station

    return _make


@pytest.fixture
def make_suite(session: Session) -> Callable[..., Suite]:
    def _make(
        name: str = "Suite 1",
        monthly_rate: float = 1200.0,
        active: bool = True,
        notes: str | None = None,
    ) -> Suite:
        suite = Suite(name=name, monthly_rate=monthly_rate, active=active, notes=notes)
        session.add(suite)
        session.commit()
        session.refresh(suite)
        return suite

    return _make


@pytest.fixture
def make_user(session: Session) -> Callable[..., User]:
    def _make(
        email: str = "op@example.com",
        password: str = "pw",
        role: Role = Role.OPERATOR,
        member_id: int | None = None,
    ) -> User:
        user = User(
            email=email,
            hashed_password=hash_password(password),
            role=role,
            member_id=member_id,
        )
        session.add(user)
        session.commit()
        session.refresh(user)
        return user

    return _make


@pytest.fixture
def operator_token(make_user: Callable[..., User]) -> str:
    return create_access_token(make_user(email="operator@example.com", role=Role.OPERATOR))


@pytest.fixture
def member_token(make_user: Callable[..., User]) -> str:
    return create_access_token(make_user(email="stylist@example.com", role=Role.MEMBER))
