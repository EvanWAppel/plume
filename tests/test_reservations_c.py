"""Group C — reservations hardening (C1, C2, C4, C5).

TDD tests for the hardened service and the new endpoints. Router tests build a
LOCAL FastAPI app so they exercise only the reservations router with the shared
in-memory ``session`` overridden in.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import date, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import Session

from plume.db import get_session
from plume.members.models import Member, Status
from plume.reservations.router import router
from plume.reservations.service import (
    MemberInactiveError,
    PastDateError,
    ReservationNotFoundError,
    StationInactiveError,
    StationUnavailableError,
    cancel_reservation,
    list_reservations,
    reserve_recurring,
    reserve_station,
)
from plume.spaces.models import Station

FUTURE = date(2026, 10, 1)


@pytest.fixture
def res_client(session: Session) -> Iterator[TestClient]:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_session] = lambda: session
    with TestClient(app) as c:
        yield c


# --- C1: hardening reserve_station -----------------------------------------


def test_reserve_rejects_inactive_station(
    session: Session, make_member: Callable[..., Member], make_station: Callable[..., Station]
) -> None:
    member = make_member()
    station = make_station(name="Dead", active=False)
    assert member.id is not None
    assert station.id is not None

    with pytest.raises(StationInactiveError):
        reserve_station(session, member.id, station.id, FUTURE)


def test_reserve_rejects_inactive_member(
    session: Session, make_member: Callable[..., Member], make_station: Callable[..., Station]
) -> None:
    member = make_member(status=Status.INACTIVE)
    station = make_station()
    assert member.id is not None
    assert station.id is not None

    with pytest.raises(MemberInactiveError):
        reserve_station(session, member.id, station.id, FUTURE)


def test_reserve_rejects_past_date(
    session: Session, make_member: Callable[..., Member], make_station: Callable[..., Station]
) -> None:
    member = make_member()
    station = make_station()
    assert member.id is not None
    assert station.id is not None
    yesterday = date.today() - timedelta(days=1)

    with pytest.raises(PastDateError):
        reserve_station(session, member.id, station.id, yesterday)


def test_reserve_allows_prospect_and_active(
    session: Session, make_member: Callable[..., Member], make_station: Callable[..., Station]
) -> None:
    prospect = make_member(email="p@example.com", status=Status.PROSPECT)
    active = make_member(email="a@example.com", status=Status.ACTIVE)
    s1 = make_station(name="S1")
    s2 = make_station(name="S2")
    assert prospect.id is not None and active.id is not None
    assert s1.id is not None and s2.id is not None

    r1 = reserve_station(session, prospect.id, s1.id, FUTURE)
    r2 = reserve_station(session, active.id, s2.id, FUTURE)
    assert r1.id is not None
    assert r2.id is not None


def test_reserve_allows_today(
    session: Session, make_member: Callable[..., Member], make_station: Callable[..., Station]
) -> None:
    member = make_member()
    station = make_station()
    assert member.id is not None
    assert station.id is not None

    # today is not "past" — the boundary is inclusive.
    r = reserve_station(session, member.id, station.id, date.today())
    assert r.id is not None


# --- C2: cancel + list ------------------------------------------------------


def test_cancel_frees_the_slot(
    session: Session, make_member: Callable[..., Member], make_station: Callable[..., Station]
) -> None:
    member = make_member()
    station = make_station()
    assert member.id is not None
    assert station.id is not None

    first = reserve_station(session, member.id, station.id, FUTURE)
    assert first.id is not None

    # Re-reserving the same station+date must conflict while it is held.
    with pytest.raises(StationUnavailableError):
        reserve_station(session, member.id, station.id, FUTURE)

    cancel_reservation(session, first.id)

    # After cancel the slot is free again.
    second = reserve_station(session, member.id, station.id, FUTURE)
    assert second.id is not None


def test_cancel_missing_raises(session: Session) -> None:
    with pytest.raises(ReservationNotFoundError):
        cancel_reservation(session, 999999)


def test_list_reservations_filters_combine(
    session: Session, make_member: Callable[..., Member], make_station: Callable[..., Station]
) -> None:
    m1 = make_member(email="m1@example.com")
    m2 = make_member(email="m2@example.com")
    s1 = make_station(name="S1")
    s2 = make_station(name="S2")
    assert m1.id is not None and m2.id is not None
    assert s1.id is not None and s2.id is not None
    d1 = date(2026, 10, 1)
    d2 = date(2026, 10, 2)

    reserve_station(session, m1.id, s1.id, d1)
    reserve_station(session, m1.id, s2.id, d2)
    reserve_station(session, m2.id, s1.id, d2)

    assert len(list_reservations(session)) == 3
    assert len(list_reservations(session, on_date=d1)) == 1
    assert len(list_reservations(session, member_id=m1.id)) == 2
    assert len(list_reservations(session, station_id=s1.id)) == 2

    # Combined filters intersect.
    combined = list_reservations(session, on_date=d2, member_id=m2.id, station_id=s1.id)
    assert len(combined) == 1
    assert combined[0].member_id == m2.id


# --- C4: recurring holds ----------------------------------------------------


def test_reserve_recurring_expands_by_weekday(
    session: Session, make_member: Callable[..., Member], make_station: Callable[..., Station]
) -> None:
    member = make_member()
    station = make_station()
    assert member.id is not None
    assert station.id is not None

    # 2026-10-06 is a Tuesday; range covers Oct 6, 13, 20, 27 -> 4 Tuesdays.
    start = date(2026, 10, 6)
    end = date(2026, 10, 31)
    tuesday = start.weekday()  # 1

    created = reserve_recurring(session, member.id, station.id, tuesday, start, end)
    assert len(created) == 4
    assert {r.date for r in created} == {
        date(2026, 10, 6),
        date(2026, 10, 13),
        date(2026, 10, 20),
        date(2026, 10, 27),
    }
    assert all(r.id is not None for r in created)


def test_reserve_recurring_skips_conflicts(
    session: Session, make_member: Callable[..., Member], make_station: Callable[..., Station]
) -> None:
    member = make_member()
    station = make_station()
    assert member.id is not None
    assert station.id is not None

    # Pre-book one of the Tuesdays; recurring should skip it and return the rest.
    reserve_station(session, member.id, station.id, date(2026, 10, 13))

    start = date(2026, 10, 6)
    end = date(2026, 10, 31)
    created = reserve_recurring(session, member.id, station.id, start.weekday(), start, end)

    # 4 Tuesdays minus the one already held == 3 newly created.
    assert len(created) == 3
    assert date(2026, 10, 13) not in {r.date for r in created}


# --- C5: endpoints ----------------------------------------------------------


def test_delete_reservation_endpoint(
    res_client: TestClient,
    make_member: Callable[..., Member],
    make_station: Callable[..., Station],
) -> None:
    member = make_member()
    station = make_station()
    assert member.id is not None
    assert station.id is not None
    payload = {"member_id": member.id, "station_id": station.id, "date": FUTURE.isoformat()}

    created = res_client.post("/reservations", json=payload)
    assert created.status_code == 201, created.text
    res_id = created.json()["id"]

    deleted = res_client.delete(f"/reservations/{res_id}")
    assert deleted.status_code == 204, deleted.text

    # Slot is free again.
    reagain = res_client.post("/reservations", json=payload)
    assert reagain.status_code == 201


def test_delete_missing_reservation_404(res_client: TestClient) -> None:
    resp = res_client.delete("/reservations/999999")
    assert resp.status_code == 404


def test_list_reservations_endpoint_filters(
    res_client: TestClient,
    make_member: Callable[..., Member],
    make_station: Callable[..., Station],
) -> None:
    m1 = make_member(email="m1@example.com")
    m2 = make_member(email="m2@example.com")
    s1 = make_station(name="S1")
    s2 = make_station(name="S2")
    assert m1.id is not None and m2.id is not None
    assert s1.id is not None and s2.id is not None

    res_client.post(
        "/reservations",
        json={"member_id": m1.id, "station_id": s1.id, "date": "2026-10-01"},
    )
    res_client.post(
        "/reservations",
        json={"member_id": m2.id, "station_id": s2.id, "date": "2026-10-02"},
    )

    all_resp = res_client.get("/reservations")
    assert all_resp.status_code == 200
    assert len(all_resp.json()) == 2

    by_date = res_client.get("/reservations", params={"date": "2026-10-01"})
    assert len(by_date.json()) == 1

    by_member = res_client.get("/reservations", params={"member_id": m1.id})
    assert len(by_member.json()) == 1

    by_station = res_client.get("/reservations", params={"station_id": s2.id})
    assert len(by_station.json()) == 1


def test_endpoint_rejects_inactive_station_409(
    res_client: TestClient,
    make_member: Callable[..., Member],
    make_station: Callable[..., Station],
) -> None:
    member = make_member()
    station = make_station(active=False)
    assert member.id is not None
    assert station.id is not None

    resp = res_client.post(
        "/reservations",
        json={"member_id": member.id, "station_id": station.id, "date": FUTURE.isoformat()},
    )
    assert resp.status_code == 409, resp.text


def test_endpoint_rejects_past_date_422(
    res_client: TestClient,
    make_member: Callable[..., Member],
    make_station: Callable[..., Station],
) -> None:
    member = make_member()
    station = make_station()
    assert member.id is not None
    assert station.id is not None
    yesterday = (date.today() - timedelta(days=1)).isoformat()

    resp = res_client.post(
        "/reservations",
        json={"member_id": member.id, "station_id": station.id, "date": yesterday},
    )
    assert resp.status_code == 422, resp.text
