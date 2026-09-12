"""S6 — reservation service: booking, conflict, availability."""

from __future__ import annotations

from datetime import date

import pytest
from sqlmodel import Session

from plume.reservations.service import (
    StationUnavailableError,
    available_stations,
    reserve_station,
)


def test_reserve_then_conflict(session: Session, make_member, make_station) -> None:
    member = make_member()
    station = make_station()
    assert member.id is not None
    assert station.id is not None
    when = date(2026, 10, 1)

    reservation = reserve_station(session, member.id, station.id, when)
    assert reservation.id is not None

    with pytest.raises(StationUnavailableError):
        reserve_station(session, member.id, station.id, when)


def test_same_station_other_date_is_ok(session: Session, make_member, make_station) -> None:
    member = make_member()
    station = make_station()
    assert member.id is not None
    assert station.id is not None

    reserve_station(session, member.id, station.id, date(2026, 10, 1))
    second = reserve_station(session, member.id, station.id, date(2026, 10, 2))
    assert second.id is not None


def test_available_excludes_reserved_and_inactive(
    session: Session, make_member, make_station
) -> None:
    member = make_member()
    free_station = make_station(name="C1")
    booked_station = make_station(name="C2")
    inactive_station = make_station(name="C3", active=False)
    assert member.id is not None
    assert booked_station.id is not None
    when = date(2026, 10, 1)

    reserve_station(session, member.id, booked_station.id, when)

    available_ids = {s.id for s in available_stations(session, when)}
    assert free_station.id in available_ids
    assert booked_station.id not in available_ids
    assert inactive_station.id not in available_ids
