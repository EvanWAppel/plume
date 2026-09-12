"""Group F — minimal web UI tests (HTMX + Jinja).

These build a LOCAL FastAPI app that only mounts ``web_router`` (the web UI is
not wired into the global app yet), overriding ``get_session`` to reuse the
test's in-memory session — mirroring the pattern in ``conftest.py``.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import date, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import Session

from plume.auth.models import Role, User
from plume.auth.service import create_access_token
from plume.db import get_session
from plume.members.models import Member, Status
from plume.reservations.service import list_reservations
from plume.spaces.models import Station, Suite
from plume.web.router import web_router


@pytest.fixture
def web_client(session: Session) -> Iterator[TestClient]:
    app = FastAPI()
    app.include_router(web_router)

    def override_get_session() -> Iterator[Session]:
        yield session

    app.dependency_overrides[get_session] = override_get_session
    # Disable redirect following so we can assert 302s on auth-gated routes.
    with TestClient(app, follow_redirects=False) as client:
        yield client
    app.dependency_overrides.clear()


# --- F1: landing page -------------------------------------------------------


def test_index_renders_200(web_client: TestClient) -> None:
    resp = web_client.get("/")
    assert resp.status_code == 200
    assert "plume" in resp.text.lower()
    assert "text/html" in resp.headers["content-type"]


# --- F4: auth ---------------------------------------------------------------


def test_login_page_renders_form(web_client: TestClient) -> None:
    resp = web_client.get("/login")
    assert resp.status_code == 200
    assert "email" in resp.text.lower()
    assert "password" in resp.text.lower()


def test_login_success_sets_cookie_and_redirects(
    web_client: TestClient, make_user: Callable[..., User]
) -> None:
    make_user(email="op@example.com", password="secret", role=Role.OPERATOR)
    resp = web_client.post("/login", data={"email": "op@example.com", "password": "secret"})
    assert resp.status_code == 302
    assert resp.headers["location"] == "/dashboard"
    assert "plume_session" in resp.cookies


def test_login_bad_credentials_rerenders_with_error(
    web_client: TestClient, make_user: Callable[..., User]
) -> None:
    make_user(email="op@example.com", password="secret", role=Role.OPERATOR)
    resp = web_client.post("/login", data={"email": "op@example.com", "password": "wrong"})
    assert resp.status_code == 200
    assert "invalid" in resp.text.lower()
    assert "plume_session" not in resp.cookies


def test_logout_clears_cookie(web_client: TestClient) -> None:
    resp = web_client.get("/logout")
    assert resp.status_code == 302
    assert resp.headers["location"] == "/login"


def test_dashboard_without_cookie_redirects_to_login(web_client: TestClient) -> None:
    resp = web_client.get("/dashboard")
    assert resp.status_code == 302
    assert resp.headers["location"] == "/login"


def test_dashboard_with_member_cookie_redirects_to_login(
    web_client: TestClient, make_user: Callable[..., User]
) -> None:
    member_user = make_user(email="stylist@example.com", role=Role.MEMBER)
    token = create_access_token(member_user)
    web_client.cookies.set("plume_session", token)
    resp = web_client.get("/dashboard")
    assert resp.status_code == 302
    assert resp.headers["location"] == "/login"


def test_dashboard_with_bad_cookie_redirects_to_login(web_client: TestClient) -> None:
    web_client.cookies.set("plume_session", "not-a-real-jwt")
    resp = web_client.get("/dashboard")
    assert resp.status_code == 302
    assert resp.headers["location"] == "/login"


# --- F2: operator dashboard -------------------------------------------------


def test_dashboard_renders_seeded_data(
    web_client: TestClient,
    make_user: Callable[..., User],
    make_member: Callable[..., Member],
    make_station: Callable[..., Station],
    make_suite: Callable[..., Suite],
) -> None:
    operator = make_user(email="op@example.com", role=Role.OPERATOR)
    make_member(name="Alice Stylist", email="alice@example.com", status=Status.ACTIVE)
    make_station(name="Chair Alpha")
    make_suite(name="Suite Beta")
    token = create_access_token(operator)
    web_client.cookies.set("plume_session", token)

    resp = web_client.get("/dashboard")
    assert resp.status_code == 200
    assert "Alice Stylist" in resp.text
    assert "Chair Alpha" in resp.text
    assert "Suite Beta" in resp.text


def test_dashboard_shows_suite_occupancy(
    web_client: TestClient,
    make_user: Callable[..., User],
    make_member: Callable[..., Member],
    make_suite: Callable[..., Suite],
    session: Session,
) -> None:
    operator = make_user(email="op@example.com", role=Role.OPERATOR)
    member = make_member(name="Occupant One", email="occ@example.com")
    assert member.id is not None
    suite = make_suite(name="Occupied Suite")
    suite.occupant_member_id = member.id
    session.add(suite)
    session.commit()
    token = create_access_token(operator)
    web_client.cookies.set("plume_session", token)

    resp = web_client.get("/dashboard")
    assert resp.status_code == 200
    assert "Occupant One" in resp.text


def test_run_billing_creates_invoices(
    web_client: TestClient,
    make_user: Callable[..., User],
    make_member: Callable[..., Member],
    make_suite: Callable[..., Suite],
    session: Session,
) -> None:
    operator = make_user(email="op@example.com", role=Role.OPERATOR)
    member = make_member(name="Renter", email="renter@example.com")
    assert member.id is not None
    suite = make_suite(name="Rented Suite", monthly_rate=1500.0)
    suite.occupant_member_id = member.id
    session.add(suite)
    session.commit()
    token = create_access_token(operator)
    web_client.cookies.set("plume_session", token)

    resp = web_client.post("/dashboard/run-billing", data={"period": "2026-09"})
    assert resp.status_code == 200
    assert "2026-09" in resp.text
    assert "1500" in resp.text


def test_run_billing_without_cookie_redirects(web_client: TestClient) -> None:
    resp = web_client.post("/dashboard/run-billing", data={"period": "2026-09"})
    assert resp.status_code == 302
    assert resp.headers["location"] == "/login"


# --- F3: stylist booking view -----------------------------------------------


def test_book_page_lists_available_stations(
    web_client: TestClient, make_station: Callable[..., Station]
) -> None:
    make_station(name="Free Chair")
    on_date = (date.today() + timedelta(days=3)).isoformat()
    resp = web_client.get("/book", params={"date": on_date})
    assert resp.status_code == 200
    assert "Free Chair" in resp.text


def test_book_page_no_auth_required(web_client: TestClient) -> None:
    on_date = (date.today() + timedelta(days=1)).isoformat()
    resp = web_client.get("/book", params={"date": on_date})
    assert resp.status_code == 200


def test_book_creates_reservation_and_drops_station(
    web_client: TestClient,
    make_member: Callable[..., Member],
    make_station: Callable[..., Station],
    session: Session,
) -> None:
    member = make_member(name="Booker", email="booker@example.com", status=Status.ACTIVE)
    station = make_station(name="Bookable Chair")
    assert member.id is not None
    assert station.id is not None
    on_date = (date.today() + timedelta(days=2)).isoformat()

    resp = web_client.post(
        "/book",
        data={"member_id": member.id, "station_id": station.id, "date": on_date},
    )
    assert resp.status_code == 200
    # The reservation exists.
    reservations = list_reservations(session, station_id=station.id)
    assert len(reservations) == 1
    # The station no longer appears in availability for that date.
    assert "Bookable Chair" not in resp.text


def test_book_conflict_shows_error(
    web_client: TestClient,
    make_member: Callable[..., Member],
    make_station: Callable[..., Station],
    session: Session,
) -> None:
    member = make_member(name="Booker", email="booker@example.com", status=Status.ACTIVE)
    station = make_station(name="Contested Chair")
    assert member.id is not None
    assert station.id is not None
    on_date = (date.today() + timedelta(days=2)).isoformat()

    # First booking succeeds.
    web_client.post(
        "/book",
        data={"member_id": member.id, "station_id": station.id, "date": on_date},
    )
    # Second booking of the same station+date conflicts.
    resp = web_client.post(
        "/book",
        data={"member_id": member.id, "station_id": station.id, "date": on_date},
    )
    assert resp.status_code == 200
    assert "unavailable" in resp.text.lower() or "already" in resp.text.lower()
