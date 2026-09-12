"""Business rules for Group G's events and consignment gallery."""

from __future__ import annotations

import logging
from datetime import UTC
from datetime import datetime as datetime_type

from sqlmodel import Session, col, select

from plume.community.models import ArtPiece, ArtStatus, Event, EventRSVP

logger = logging.getLogger(__name__)


class EventNotFoundError(Exception):
    """No event exists with the requested id."""


class EventAtCapacityError(Exception):
    """An event cannot accept another RSVP."""


class DuplicateRSVPError(Exception):
    """The email already has an RSVP for this event."""


class EventCapacityTooSmallError(Exception):
    """Capacity cannot be reduced below the current RSVP count."""


class ArtPieceNotFoundError(Exception):
    """No art piece exists with the requested id."""


class ArtAlreadySoldError(Exception):
    """A sold art piece cannot be sold again."""


def _naive_utc(value: datetime_type) -> datetime_type:
    """Normalize aware datetimes to SQLite-friendly naive UTC values."""
    if value.tzinfo is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)


def _get_event(session: Session, event_id: int) -> Event:
    event = session.get(Event, event_id)
    if event is None:
        logger.info("event not found: id=%s", event_id)
        raise EventNotFoundError(f"event {event_id} not found")
    return event


def create_event(session: Session, *, title: str, datetime: datetime_type, capacity: int) -> Event:
    event = Event(title=title, datetime=_naive_utc(datetime), capacity=capacity)
    session.add(event)
    session.commit()
    session.refresh(event)
    logger.info("created event: id=%s capacity=%s", event.id, capacity)
    return event


def list_events(session: Session) -> list[Event]:
    return list(session.exec(select(Event).order_by(col(Event.datetime))).all())


def list_upcoming_events(session: Session, *, now: datetime_type | None = None) -> list[Event]:
    boundary = _naive_utc(now or datetime_type.now(UTC))
    return list(
        session.exec(
            select(Event).where(col(Event.datetime) >= boundary).order_by(col(Event.datetime))
        ).all()
    )


def get_event(session: Session, event_id: int) -> Event:
    return _get_event(session, event_id)


def update_event(
    session: Session,
    event_id: int,
    *,
    title: str | None = None,
    datetime: datetime_type | None = None,
    capacity: int | None = None,
) -> Event:
    event = _get_event(session, event_id)
    if capacity is not None and capacity < len(event.rsvps):
        logger.info(
            "event capacity reduction rejected: id=%s capacity=%s rsvps=%s",
            event_id,
            capacity,
            len(event.rsvps),
        )
        raise EventCapacityTooSmallError("capacity cannot be lower than the current RSVP count")
    if title is not None:
        event.title = title
    if datetime is not None:
        event.datetime = _naive_utc(datetime)
    if capacity is not None:
        event.capacity = capacity
    session.add(event)
    session.commit()
    session.refresh(event)
    logger.info("updated event: id=%s", event_id)
    return event


def delete_event(session: Session, event_id: int) -> None:
    event = _get_event(session, event_id)
    session.delete(event)
    session.commit()
    logger.info("deleted event: id=%s", event_id)


def rsvp_to_event(session: Session, event_id: int, *, name: str, email: str) -> EventRSVP:
    event = _get_event(session, event_id)
    normalized_email = email.strip().lower()
    existing = session.exec(
        select(EventRSVP)
        .where(EventRSVP.event_id == event_id)
        .where(EventRSVP.email == normalized_email)
    ).first()
    if existing is not None:
        logger.info("duplicate RSVP rejected: event=%s email=%s", event_id, normalized_email)
        raise DuplicateRSVPError(f"{normalized_email} already has an RSVP for event {event_id}")
    if len(event.rsvps) >= event.capacity:
        logger.info("event at capacity: id=%s capacity=%s", event_id, event.capacity)
        raise EventAtCapacityError(f"event {event_id} is at capacity")

    rsvp = EventRSVP(event_id=event_id, name=name, email=normalized_email)
    session.add(rsvp)
    session.commit()
    session.refresh(rsvp)
    logger.info("created RSVP: event=%s rsvp=%s", event_id, rsvp.id)
    return rsvp


def _get_art_piece(session: Session, piece_id: int) -> ArtPiece:
    piece = session.get(ArtPiece, piece_id)
    if piece is None:
        logger.info("art piece not found: id=%s", piece_id)
        raise ArtPieceNotFoundError(f"art piece {piece_id} not found")
    return piece


def create_art_piece(
    session: Session,
    *,
    artist: str,
    title: str,
    price: float,
    commission_percent: float,
) -> ArtPiece:
    piece = ArtPiece(
        artist=artist,
        title=title,
        price=price,
        commission_percent=commission_percent,
    )
    session.add(piece)
    session.commit()
    session.refresh(piece)
    logger.info("created art piece: id=%s", piece.id)
    return piece


def list_art_pieces(session: Session) -> list[ArtPiece]:
    return list(session.exec(select(ArtPiece).order_by(col(ArtPiece.id))).all())


def list_current_gallery(session: Session) -> list[ArtPiece]:
    return list(
        session.exec(
            select(ArtPiece)
            .where(ArtPiece.status == ArtStatus.ON_DISPLAY)
            .order_by(col(ArtPiece.id))
        ).all()
    )


def get_art_piece(session: Session, piece_id: int) -> ArtPiece:
    return _get_art_piece(session, piece_id)


def update_art_piece(
    session: Session,
    piece_id: int,
    *,
    artist: str | None = None,
    title: str | None = None,
    price: float | None = None,
    commission_percent: float | None = None,
) -> ArtPiece:
    piece = _get_art_piece(session, piece_id)
    if artist is not None:
        piece.artist = artist
    if title is not None:
        piece.title = title
    if price is not None:
        piece.price = price
    if commission_percent is not None:
        piece.commission_percent = commission_percent
    session.add(piece)
    session.commit()
    session.refresh(piece)
    logger.info("updated art piece: id=%s", piece_id)
    return piece


def delete_art_piece(session: Session, piece_id: int) -> None:
    piece = _get_art_piece(session, piece_id)
    session.delete(piece)
    session.commit()
    logger.info("deleted art piece: id=%s", piece_id)


def sell_art_piece(session: Session, piece_id: int) -> ArtPiece:
    piece = _get_art_piece(session, piece_id)
    if piece.status is ArtStatus.SOLD:
        logger.info("repeat art sale rejected: id=%s", piece_id)
        raise ArtAlreadySoldError(f"art piece {piece_id} is already sold")
    commission = round(piece.price * piece.commission_percent / 100, 2)
    piece.status = ArtStatus.SOLD
    piece.salon_commission = commission
    piece.artist_payout = round(piece.price - commission, 2)
    session.add(piece)
    session.commit()
    session.refresh(piece)
    logger.info(
        "sold art piece: id=%s commission=%s payout=%s",
        piece_id,
        piece.salon_commission,
        piece.artist_payout,
    )
    return piece
