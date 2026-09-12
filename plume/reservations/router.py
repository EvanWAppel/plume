"""Reservation API (S7 + Group C5).

Endpoints stay open (no auth) by design — booking auth is a deliberate later
step. Domain errors are translated to HTTP status codes at this boundary:
- ``StationUnavailableError`` / ``StationInactiveError`` -> 409 (conflict)
- ``PastDateError`` / ``MemberInactiveError`` -> 422 (unprocessable request)
- ``ReservationNotFoundError`` -> 404
"""

from __future__ import annotations

from datetime import date as date_type

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel
from sqlmodel import Session

from plume.db import get_session
from plume.reservations.models import Reservation
from plume.reservations.service import (
    MemberInactiveError,
    PastDateError,
    ReservationNotFoundError,
    StationInactiveError,
    StationUnavailableError,
    cancel_reservation,
    list_reservations,
    reserve_station,
)

router = APIRouter(prefix="/reservations", tags=["reservations"])


class ReservationCreate(BaseModel):
    member_id: int
    station_id: int
    date: date_type


@router.post("", status_code=201)
def create_reservation(
    payload: ReservationCreate, session: Session = Depends(get_session)
) -> Reservation:
    try:
        return reserve_station(session, payload.member_id, payload.station_id, payload.date)
    except (StationUnavailableError, StationInactiveError) as exc:
        # Conflict with the resource's current state (already held / inactive).
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (PastDateError, MemberInactiveError) as exc:
        # The request is well-formed but semantically unprocessable.
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("")
def get_reservations(
    date: date_type | None = Query(default=None),
    member_id: int | None = Query(default=None),
    station_id: int | None = Query(default=None),
    session: Session = Depends(get_session),
) -> list[Reservation]:
    return list_reservations(session, on_date=date, member_id=member_id, station_id=station_id)


@router.delete("/{reservation_id}", status_code=204)
def delete_reservation(reservation_id: int, session: Session = Depends(get_session)) -> Response:
    try:
        cancel_reservation(session, reservation_id)
    except ReservationNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return Response(status_code=204)
