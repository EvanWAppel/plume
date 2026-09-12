"""HTTP API for community events and the consignment gallery."""

from __future__ import annotations

from datetime import datetime as datetime_type

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlmodel import Session

from plume.auth.models import User
from plume.auth.service import require_operator
from plume.community.models import ArtPiece, Event, EventRSVP
from plume.community.service import (
    ArtAlreadySoldError,
    ArtPieceNotFoundError,
    DuplicateRSVPError,
    EventAtCapacityError,
    EventCapacityTooSmallError,
    EventNotFoundError,
    create_art_piece,
    create_event,
    delete_art_piece,
    delete_event,
    get_art_piece,
    get_event,
    list_art_pieces,
    list_current_gallery,
    list_events,
    list_upcoming_events,
    rsvp_to_event,
    sell_art_piece,
    update_art_piece,
    update_event,
)
from plume.db import get_session

router = APIRouter(tags=["community"])


class EventCreate(BaseModel):
    title: str = Field(min_length=1)
    datetime: datetime_type
    capacity: int = Field(gt=0)


class EventUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1)
    datetime: datetime_type | None = None
    capacity: int | None = Field(default=None, gt=0)


class RSVPCreate(BaseModel):
    name: str = Field(min_length=1)
    email: str = Field(min_length=3)


class RSVPRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    event_id: int
    name: str
    email: str


class EventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    datetime: datetime_type
    capacity: int
    rsvps: list[RSVPRead]


class ArtPieceCreate(BaseModel):
    artist: str = Field(min_length=1)
    title: str = Field(min_length=1)
    price: float = Field(ge=0)
    commission_percent: float = Field(ge=0, le=100)


class ArtPieceUpdate(BaseModel):
    artist: str | None = Field(default=None, min_length=1)
    title: str | None = Field(default=None, min_length=1)
    price: float | None = Field(default=None, ge=0)
    commission_percent: float | None = Field(default=None, ge=0, le=100)


def _event_error(exc: EventNotFoundError | EventCapacityTooSmallError) -> HTTPException:
    code = status.HTTP_404_NOT_FOUND if isinstance(exc, EventNotFoundError) else 409
    return HTTPException(status_code=code, detail=str(exc))


@router.get("/events/upcoming", response_model=list[EventRead])
def upcoming_events(session: Session = Depends(get_session)) -> list[Event]:
    return list_upcoming_events(session)


@router.get("/gallery")
def current_gallery(session: Session = Depends(get_session)) -> list[ArtPiece]:
    return list_current_gallery(session)


@router.post("/events", status_code=status.HTTP_201_CREATED, response_model=EventRead)
def post_event(
    payload: EventCreate,
    session: Session = Depends(get_session),
    _op: User = Depends(require_operator),
) -> Event:
    return create_event(
        session, title=payload.title, datetime=payload.datetime, capacity=payload.capacity
    )


@router.get("/events", response_model=list[EventRead])
def get_events(session: Session = Depends(get_session)) -> list[Event]:
    return list_events(session)


@router.get("/events/{event_id}", response_model=EventRead)
def get_event_endpoint(event_id: int, session: Session = Depends(get_session)) -> Event:
    try:
        return get_event(session, event_id)
    except EventNotFoundError as exc:
        raise _event_error(exc) from exc


@router.patch("/events/{event_id}", response_model=EventRead)
def patch_event(
    event_id: int,
    payload: EventUpdate,
    session: Session = Depends(get_session),
    _op: User = Depends(require_operator),
) -> Event:
    try:
        return update_event(
            session,
            event_id,
            title=payload.title,
            datetime=payload.datetime,
            capacity=payload.capacity,
        )
    except (EventNotFoundError, EventCapacityTooSmallError) as exc:
        raise _event_error(exc) from exc


@router.delete("/events/{event_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_event(
    event_id: int,
    session: Session = Depends(get_session),
    _op: User = Depends(require_operator),
) -> Response:
    try:
        delete_event(session, event_id)
    except EventNotFoundError as exc:
        raise _event_error(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/events/{event_id}/rsvps",
    status_code=status.HTTP_201_CREATED,
    response_model=RSVPRead,
)
def post_rsvp(
    event_id: int, payload: RSVPCreate, session: Session = Depends(get_session)
) -> EventRSVP:
    try:
        return rsvp_to_event(session, event_id, name=payload.name, email=payload.email)
    except EventNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (EventAtCapacityError, DuplicateRSVPError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/art-pieces", status_code=status.HTTP_201_CREATED)
def post_art_piece(
    payload: ArtPieceCreate,
    session: Session = Depends(get_session),
    _op: User = Depends(require_operator),
) -> ArtPiece:
    return create_art_piece(
        session,
        artist=payload.artist,
        title=payload.title,
        price=payload.price,
        commission_percent=payload.commission_percent,
    )


@router.get("/art-pieces")
def get_art_pieces(session: Session = Depends(get_session)) -> list[ArtPiece]:
    return list_art_pieces(session)


@router.get("/art-pieces/{piece_id}")
def get_art_piece_endpoint(piece_id: int, session: Session = Depends(get_session)) -> ArtPiece:
    try:
        return get_art_piece(session, piece_id)
    except ArtPieceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.patch("/art-pieces/{piece_id}")
def patch_art_piece(
    piece_id: int,
    payload: ArtPieceUpdate,
    session: Session = Depends(get_session),
    _op: User = Depends(require_operator),
) -> ArtPiece:
    try:
        return update_art_piece(
            session,
            piece_id,
            artist=payload.artist,
            title=payload.title,
            price=payload.price,
            commission_percent=payload.commission_percent,
        )
    except ArtPieceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/art-pieces/{piece_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_art_piece(
    piece_id: int,
    session: Session = Depends(get_session),
    _op: User = Depends(require_operator),
) -> Response:
    try:
        delete_art_piece(session, piece_id)
    except ArtPieceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/art-pieces/{piece_id}/sell")
def sell_art_piece_endpoint(
    piece_id: int,
    session: Session = Depends(get_session),
    _op: User = Depends(require_operator),
) -> ArtPiece:
    try:
        return sell_art_piece(session, piece_id)
    except ArtPieceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ArtAlreadySoldError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
