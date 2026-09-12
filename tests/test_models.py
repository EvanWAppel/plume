"""S5 — core models persist and relate."""

from __future__ import annotations

from datetime import date

from sqlmodel import Session

from plume.reservations.models import Reservation


def test_reservation_links_member_and_station(session: Session, make_member, make_station) -> None:
    member = make_member()
    station = make_station()
    assert member.id is not None
    assert station.id is not None

    reservation = Reservation(member_id=member.id, station_id=station.id, date=date(2026, 10, 1))
    session.add(reservation)
    session.commit()
    session.refresh(reservation)

    assert reservation.id is not None
    assert reservation.member_id == member.id
    assert reservation.station_id == station.id
