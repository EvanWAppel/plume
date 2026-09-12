"""Space inventory business rules (Group B).

Errors are raised, never swallowed — the API layer translates them to HTTP
status codes at the boundary. Logging marks each decision point.
"""

from __future__ import annotations

import logging

from sqlmodel import Session, select

from plume.spaces.models import Station, Suite

logger = logging.getLogger(__name__)


class SpaceNotFoundError(Exception):
    """A station or suite id does not resolve to a row."""


class SuiteOccupiedError(Exception):
    """A suite already has an occupant and cannot be assigned again."""


# --- stations ---------------------------------------------------------------


def add_station(session: Session, name: str, *, notes: str | None = None) -> Station:
    station = Station(name=name, notes=notes)
    session.add(station)
    session.commit()
    session.refresh(station)
    logger.info("station added: id=%s name=%s", station.id, name)
    return station


def deactivate_station(session: Session, station_id: int) -> Station:
    station = session.get(Station, station_id)
    if station is None:
        logger.info("deactivate_station miss: id=%s", station_id)
        raise SpaceNotFoundError(f"station {station_id} not found")
    station.active = False
    session.add(station)
    session.commit()
    session.refresh(station)
    logger.info("station deactivated: id=%s", station_id)
    return station


def list_stations(session: Session, active: bool | None = None) -> list[Station]:
    statement = select(Station)
    if active is not None:
        statement = statement.where(Station.active == active)
    return list(session.exec(statement).all())


# --- suites -----------------------------------------------------------------


def add_suite(
    session: Session,
    name: str,
    monthly_rate: float,
    *,
    notes: str | None = None,
) -> Suite:
    suite = Suite(name=name, monthly_rate=monthly_rate, notes=notes)
    session.add(suite)
    session.commit()
    session.refresh(suite)
    logger.info("suite added: id=%s name=%s rate=%s", suite.id, name, monthly_rate)
    return suite


def deactivate_suite(session: Session, suite_id: int) -> Suite:
    suite = _get_suite(session, suite_id)
    suite.active = False
    session.add(suite)
    session.commit()
    session.refresh(suite)
    logger.info("suite deactivated: id=%s", suite_id)
    return suite


def list_suites(session: Session, vacant: bool | None = None) -> list[Suite]:
    statement = select(Suite)
    if vacant is True:
        statement = statement.where(Suite.occupant_member_id == None)  # noqa: E711
    elif vacant is False:
        statement = statement.where(Suite.occupant_member_id != None)  # noqa: E711
    return list(session.exec(statement).all())


def assign_suite(session: Session, suite_id: int, member_id: int) -> Suite:
    suite = _get_suite(session, suite_id)
    if suite.occupant_member_id is not None:
        logger.info(
            "suite occupied: id=%s current=%s requested=%s",
            suite_id,
            suite.occupant_member_id,
            member_id,
        )
        raise SuiteOccupiedError(
            f"suite {suite_id} already occupied by member {suite.occupant_member_id}"
        )
    suite.occupant_member_id = member_id
    session.add(suite)
    session.commit()
    session.refresh(suite)
    logger.info("suite assigned: id=%s member=%s", suite_id, member_id)
    return suite


def vacate_suite(session: Session, suite_id: int) -> Suite:
    suite = _get_suite(session, suite_id)
    suite.occupant_member_id = None
    session.add(suite)
    session.commit()
    session.refresh(suite)
    logger.info("suite vacated: id=%s", suite_id)
    return suite


def _get_suite(session: Session, suite_id: int) -> Suite:
    suite = session.get(Suite, suite_id)
    if suite is None:
        logger.info("suite miss: id=%s", suite_id)
        raise SpaceNotFoundError(f"suite {suite_id} not found")
    return suite
