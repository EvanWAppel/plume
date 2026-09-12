"""Spaces API.

S7 gave us the available-stations query; Group B (B4) extends this same router
with station/suite CRUD-lite and suite occupancy. The pre-existing
``GET /stations/available`` endpoint is preserved verbatim — several tests
depend on it.
"""

from __future__ import annotations

import logging
from datetime import date as date_type

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlmodel import Session

from plume.auth.models import User
from plume.auth.service import require_operator
from plume.db import get_session
from plume.reservations.service import available_stations
from plume.spaces.models import Station, Suite
from plume.spaces.service import (
    SpaceNotFoundError,
    SuiteOccupiedError,
    add_station,
    add_suite,
    assign_suite,
    list_stations,
    list_suites,
    vacate_suite,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["spaces"])


# --- request schemas --------------------------------------------------------


class StationCreate(BaseModel):
    name: str
    active: bool = True
    notes: str | None = None


class SuiteCreate(BaseModel):
    name: str
    monthly_rate: float
    notes: str | None = None


class SuiteAssign(BaseModel):
    member_id: int


# --- pre-existing endpoint (S7) — keep intact -------------------------------


@router.get("/stations/available")
def get_available_stations(
    date: date_type = Query(...), session: Session = Depends(get_session)
) -> list[Station]:
    return available_stations(session, date)


# --- stations (B4) ----------------------------------------------------------


@router.post("/stations", status_code=status.HTTP_201_CREATED)
def create_station(
    payload: StationCreate,
    session: Session = Depends(get_session),
    _op: User = Depends(require_operator),
) -> Station:
    station = add_station(session, name=payload.name, notes=payload.notes)
    if not payload.active:
        station.active = False
        session.add(station)
        session.commit()
        session.refresh(station)
    return station


@router.get("/stations")
def get_stations(
    active: bool | None = Query(default=None),
    session: Session = Depends(get_session),
) -> list[Station]:
    return list_stations(session, active=active)


# --- suites (B4) ------------------------------------------------------------


@router.post("/suites", status_code=status.HTTP_201_CREATED)
def create_suite(
    payload: SuiteCreate,
    session: Session = Depends(get_session),
    _op: User = Depends(require_operator),
) -> Suite:
    return add_suite(
        session,
        name=payload.name,
        monthly_rate=payload.monthly_rate,
        notes=payload.notes,
    )


@router.get("/suites")
def get_suites(
    vacant: bool | None = Query(default=None),
    session: Session = Depends(get_session),
) -> list[Suite]:
    return list_suites(session, vacant=vacant)


@router.post("/suites/{suite_id}/assign")
def post_assign_suite(
    suite_id: int,
    payload: SuiteAssign,
    session: Session = Depends(get_session),
    _op: User = Depends(require_operator),
) -> Suite:
    try:
        return assign_suite(session, suite_id, payload.member_id)
    except SuiteOccupiedError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except SpaceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/suites/{suite_id}/vacate")
def post_vacate_suite(
    suite_id: int,
    session: Session = Depends(get_session),
    _op: User = Depends(require_operator),
) -> Suite:
    try:
        return vacate_suite(session, suite_id)
    except SpaceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
