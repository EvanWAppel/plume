"""Reservation business rules (S6 + Group C hardening).

Errors are raised, never swallowed — the API layer (S7/C5) translates them to
HTTP status codes at the boundary.

Group C additions:
- C1: ``reserve_station`` rejects inactive stations (``StationInactiveError``),
  ``INACTIVE`` members (``MemberInactiveError``), and past dates
  (``PastDateError``). PROSPECT and ACTIVE members are allowed; ``today`` is not
  considered past (inclusive boundary).
- C2: ``cancel_reservation`` (raises ``ReservationNotFoundError`` when missing)
  and ``list_reservations`` with combinable filters.
- C4: ``reserve_recurring`` expands a weekly hold into individual reservations.
"""

from __future__ import annotations

import logging
from datetime import date as date_type
from datetime import timedelta

from sqlmodel import Session, select

from plume.members.models import Member, Status
from plume.reservations.models import Reservation
from plume.spaces.models import Station

logger = logging.getLogger(__name__)


class StationUnavailableError(Exception):
    """A station is already reserved for the requested date."""


class StationInactiveError(Exception):
    """The station is not active and cannot be reserved."""


class MemberInactiveError(Exception):
    """The member is INACTIVE and cannot hold reservations."""


class PastDateError(Exception):
    """The requested date is in the past relative to today."""


class ReservationNotFoundError(Exception):
    """No reservation exists for the given id."""


def reserve_station(
    session: Session, member_id: int, station_id: int, on_date: date_type
) -> Reservation:
    # C1: reject past dates (today is allowed — the boundary is inclusive).
    if on_date < date_type.today():
        logger.info("reservation rejected (past date): date=%s", on_date)
        raise PastDateError(f"cannot reserve a past date: {on_date.isoformat()}")

    # C1: the station must exist and be active.
    station = session.get(Station, station_id)
    if station is None or not station.active:
        logger.info("reservation rejected (inactive station): station=%s", station_id)
        raise StationInactiveError(f"station {station_id} is inactive or missing")

    # C1: an INACTIVE member cannot book; PROSPECT/ACTIVE are allowed.
    member = session.get(Member, member_id)
    if member is None or member.status is Status.INACTIVE:
        logger.info("reservation rejected (inactive member): member=%s", member_id)
        raise MemberInactiveError(f"member {member_id} is inactive or missing")

    existing = session.exec(
        select(Reservation).where(
            Reservation.station_id == station_id,
            Reservation.date == on_date,
        )
    ).first()
    if existing is not None:
        logger.info("reservation conflict: station=%s date=%s", station_id, on_date)
        raise StationUnavailableError(
            f"station {station_id} is already reserved on {on_date.isoformat()}"
        )
    reservation = Reservation(member_id=member_id, station_id=station_id, date=on_date)
    session.add(reservation)
    session.commit()
    session.refresh(reservation)
    logger.info(
        "reserved: id=%s station=%s date=%s member=%s",
        reservation.id,
        station_id,
        on_date,
        member_id,
    )
    return reservation


def cancel_reservation(session: Session, reservation_id: int) -> None:
    """Delete a reservation, freeing the station+date slot.

    Raises ``ReservationNotFoundError`` if no such reservation exists.
    """
    reservation = session.get(Reservation, reservation_id)
    if reservation is None:
        logger.info("cancel rejected (not found): id=%s", reservation_id)
        raise ReservationNotFoundError(f"reservation {reservation_id} not found")
    session.delete(reservation)
    session.commit()
    logger.info("cancelled reservation: id=%s", reservation_id)


def list_reservations(
    session: Session,
    *,
    on_date: date_type | None = None,
    member_id: int | None = None,
    station_id: int | None = None,
) -> list[Reservation]:
    """List reservations, optionally narrowed by any combination of filters."""
    statement = select(Reservation)
    if on_date is not None:
        statement = statement.where(Reservation.date == on_date)
    if member_id is not None:
        statement = statement.where(Reservation.member_id == member_id)
    if station_id is not None:
        statement = statement.where(Reservation.station_id == station_id)
    return list(session.exec(statement).all())


def reserve_recurring(
    session: Session,
    member_id: int,
    station_id: int,
    weekday: int,
    start: date_type,
    end: date_type,
) -> list[Reservation]:
    """Expand a weekly hold into individual reservations.

    Books ``station_id`` for ``member_id`` on every ``weekday`` (0=Mon..6=Sun)
    between ``start`` and ``end`` inclusive.

    Partial-conflict decision (C4): dates that are already reserved for this
    station are **skipped** — they do not abort the whole run — and only the
    reservations actually created are returned. Non-conflict validation errors
    (past date, inactive station/member) still propagate, since those apply to
    the whole request rather than a single occurrence.
    """
    if weekday < 0 or weekday > 6:
        raise ValueError(f"weekday must be 0..6, got {weekday}")

    # Advance to the first matching weekday on or after ``start``.
    current = start + timedelta(days=(weekday - start.weekday()) % 7)

    created: list[Reservation] = []
    skipped: list[date_type] = []
    while current <= end:
        try:
            created.append(reserve_station(session, member_id, station_id, current))
        except StationUnavailableError:
            skipped.append(current)
        current += timedelta(days=7)

    logger.info(
        "recurring hold: station=%s member=%s weekday=%s created=%d skipped=%d",
        station_id,
        member_id,
        weekday,
        len(created),
        len(skipped),
    )
    return created


def available_stations(session: Session, on_date: date_type) -> list[Station]:
    reserved_ids = {
        r.station_id
        for r in session.exec(select(Reservation).where(Reservation.date == on_date)).all()
    }
    stations = session.exec(select(Station)).all()
    return [s for s in stations if s.active and s.id not in reserved_ids]
