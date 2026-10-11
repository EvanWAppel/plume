"""Group B — Spaces / inventory (stations + suites).

Model persistence (B1), service filters + occupancy (B2/B3), and the extended
router (B4) with 409 on suite conflicts. Uses the shared ``session`` /
``make_member`` / ``make_station`` fixtures from conftest; router endpoints are
exercised via a LOCAL app to stay isolated from other in-flight agents.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import Session

from plume.auth.models import Role, User
from plume.auth.service import require_operator
from plume.db import get_session
from plume.spaces.models import Station, Suite
from plume.spaces.router import router
from plume.spaces.service import (
    SuiteOccupiedError,
    add_station,
    add_suite,
    assign_suite,
    deactivate_station,
    deactivate_suite,
    list_stations,
    list_suites,
    vacate_suite,
)


@pytest.fixture
def spaces_client(session: Session) -> Iterator[TestClient]:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_session] = lambda: session
    # Focused endpoint tests; bypass the operator guard (auth is exercised
    # end-to-end in tests/test_integration.py).
    app.dependency_overrides[require_operator] = lambda: User(
        email="op@test", hashed_password="x", role=Role.OPERATOR
    )
    with TestClient(app) as c:
        yield c


# --- B1: models persist -----------------------------------------------------


def test_station_still_constructible_name_active(session: Session) -> None:
    """Backward compatibility: Station(name=..., active=...) must still work."""
    station = Station(name="Chair 9", active=True)
    session.add(station)
    session.commit()
    session.refresh(station)
    assert station.id is not None
    assert station.notes is None


def test_suite_persists_with_vacant_default(session: Session) -> None:
    suite = Suite(name="Suite A", monthly_rate=1200.0)
    session.add(suite)
    session.commit()
    session.refresh(suite)
    assert suite.id is not None
    assert suite.active is True
    assert suite.notes is None
    assert suite.occupant_member_id is None


# --- B2: service list filters ----------------------------------------------


def test_list_stations_filters_by_active(session: Session) -> None:
    add_station(session, name="On")
    off = add_station(session, name="Off")
    deactivate_station(session, off.id)

    assert len(list_stations(session)) == 2
    assert [s.name for s in list_stations(session, active=True)] == ["On"]
    assert [s.name for s in list_stations(session, active=False)] == ["Off"]


def test_list_suites_filters_by_vacancy(session: Session, make_member) -> None:
    member = make_member()
    vacant = add_suite(session, name="V", monthly_rate=1000.0)
    occupied = add_suite(session, name="O", monthly_rate=1500.0)
    assign_suite(session, occupied.id, member.id)

    assert len(list_suites(session)) == 2
    assert [s.name for s in list_suites(session, vacant=True)] == ["V"]
    assert [s.name for s in list_suites(session, vacant=False)] == ["O"]
    assert vacant.id is not None


def test_deactivate_suite(session: Session) -> None:
    suite = add_suite(session, name="Dead", monthly_rate=900.0)
    deactivate_suite(session, suite.id)
    session.refresh(suite)
    assert suite.active is False


# --- B3: assign / vacate occupancy -----------------------------------------


def test_assign_and_vacate_suite(session: Session, make_member) -> None:
    member = make_member()
    suite = add_suite(session, name="S1", monthly_rate=1100.0)

    assigned = assign_suite(session, suite.id, member.id)
    assert assigned.occupant_member_id == member.id

    vacate_suite(session, suite.id)
    session.refresh(suite)
    assert suite.occupant_member_id is None


def test_double_assign_raises(session: Session, make_member) -> None:
    first = make_member(name="A", email="a@example.com")
    second = make_member(name="B", email="b@example.com")
    suite = add_suite(session, name="S2", monthly_rate=1100.0)

    assign_suite(session, suite.id, first.id)
    with pytest.raises(SuiteOccupiedError):
        assign_suite(session, suite.id, second.id)


# --- B4: router endpoints ---------------------------------------------------


def test_stations_available_still_works(spaces_client: TestClient, make_station) -> None:
    """The pre-existing endpoint must survive the router extension."""
    free = make_station(name="Avail")
    response = spaces_client.get("/stations/available", params={"date": "2099-10-01"})
    assert response.status_code == 200
    assert free.id in {s["id"] for s in response.json()}


def test_post_and_list_stations(spaces_client: TestClient) -> None:
    created = spaces_client.post("/stations", json={"name": "New Chair"})
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["name"] == "New Chair"
    assert body["active"] is True

    listed = spaces_client.get("/stations")
    assert listed.status_code == 200
    assert "New Chair" in {s["name"] for s in listed.json()}


def test_get_stations_active_filter(spaces_client: TestClient) -> None:
    spaces_client.post("/stations", json={"name": "Keep"})
    off = spaces_client.post("/stations", json={"name": "Drop", "active": False}).json()
    assert off["active"] is False

    active_only = spaces_client.get("/stations", params={"active": True}).json()
    assert {s["name"] for s in active_only} == {"Keep"}


def test_post_and_list_suites(spaces_client: TestClient) -> None:
    created = spaces_client.post("/suites", json={"name": "Suite 1", "monthly_rate": 1200.0})
    assert created.status_code == 201, created.text
    assert created.json()["occupant_member_id"] is None

    listed = spaces_client.get("/suites").json()
    assert "Suite 1" in {s["name"] for s in listed}


def test_get_suites_vacant_filter(spaces_client: TestClient, make_member) -> None:
    member = make_member()
    spaces_client.post("/suites", json={"name": "Empty", "monthly_rate": 1000.0})
    occupied = spaces_client.post("/suites", json={"name": "Full", "monthly_rate": 1000.0}).json()
    spaces_client.post(f"/suites/{occupied['id']}/assign", json={"member_id": member.id})

    vacant = spaces_client.get("/suites", params={"vacant": True}).json()
    assert {s["name"] for s in vacant} == {"Empty"}


def test_assign_and_vacate_endpoints(spaces_client: TestClient, make_member) -> None:
    member = make_member()
    suite = spaces_client.post(
        "/suites", json={"name": "Assignable", "monthly_rate": 1000.0}
    ).json()

    assigned = spaces_client.post(f"/suites/{suite['id']}/assign", json={"member_id": member.id})
    assert assigned.status_code == 200, assigned.text
    assert assigned.json()["occupant_member_id"] == member.id

    vacated = spaces_client.post(f"/suites/{suite['id']}/vacate")
    assert vacated.status_code == 200
    assert vacated.json()["occupant_member_id"] is None


def test_double_assign_returns_409(spaces_client: TestClient, make_member) -> None:
    first = make_member(name="A", email="a@example.com")
    second = make_member(name="B", email="b@example.com")
    suite = spaces_client.post("/suites", json={"name": "Contested", "monthly_rate": 1000.0}).json()

    spaces_client.post(f"/suites/{suite['id']}/assign", json={"member_id": first.id})
    conflict = spaces_client.post(f"/suites/{suite['id']}/assign", json={"member_id": second.id})
    assert conflict.status_code == 409, conflict.text
