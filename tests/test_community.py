"""Group G — community events and consignment gallery."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import Session

from plume.auth.models import Role, User
from plume.auth.service import require_operator
from plume.community.models import ArtStatus
from plume.community.router import router as community_router
from plume.community.service import (
    ArtAlreadySoldError,
    EventAtCapacityError,
    create_art_piece,
    create_event,
    list_current_gallery,
    list_upcoming_events,
    rsvp_to_event,
    sell_art_piece,
)
from plume.db import get_session


@pytest.fixture
def community_client(session: Session) -> Iterator[TestClient]:
    app = FastAPI()
    app.include_router(community_router)

    def override_get_session() -> Iterator[Session]:
        yield session

    app.dependency_overrides[get_session] = override_get_session
    app.dependency_overrides[require_operator] = lambda: User(
        email="op@test", hashed_password="x", role=Role.OPERATOR
    )
    with TestClient(app) as test_client:
        yield test_client


def test_event_capacity_cap_is_enforced(session: Session) -> None:
    event = create_event(
        session,
        title="First Friday",
        datetime=datetime(2027, 1, 8, 18, 0),
        capacity=1,
    )
    assert event.id is not None

    rsvp_to_event(session, event.id, name="Alex", email="alex@example.com")
    with pytest.raises(EventAtCapacityError):
        rsvp_to_event(session, event.id, name="Blair", email="blair@example.com")

    session.refresh(event)
    assert [rsvp.email for rsvp in event.rsvps] == ["alex@example.com"]


def test_upcoming_events_excludes_past_and_orders_soonest(session: Session) -> None:
    now = datetime(2027, 1, 1, 12, 0)
    create_event(session, title="Later", datetime=now + timedelta(days=2), capacity=10)
    create_event(session, title="Past", datetime=now - timedelta(seconds=1), capacity=10)
    create_event(session, title="Soon", datetime=now + timedelta(hours=1), capacity=10)

    assert [event.title for event in list_upcoming_events(session, now=now)] == ["Soon", "Later"]


def test_selling_art_computes_and_persists_split(session: Session) -> None:
    piece = create_art_piece(
        session,
        artist="Mina Lee",
        title="Desert Light",
        price=500.0,
        commission_percent=30.0,
    )
    assert piece.id is not None

    sold = sell_art_piece(session, piece.id)

    assert sold.status is ArtStatus.SOLD
    assert sold.salon_commission == pytest.approx(150.0)
    assert sold.artist_payout == pytest.approx(350.0)
    with pytest.raises(ArtAlreadySoldError):
        sell_art_piece(session, piece.id)


def test_current_gallery_only_includes_on_display(session: Session) -> None:
    available = create_art_piece(
        session, artist="A", title="Available", price=100.0, commission_percent=20.0
    )
    sold = create_art_piece(session, artist="B", title="Gone", price=200.0, commission_percent=25.0)
    assert sold.id is not None
    sell_art_piece(session, sold.id)

    assert list_current_gallery(session) == [available]


def test_public_event_and_gallery_endpoints(community_client: TestClient) -> None:
    future = datetime.now() + timedelta(days=30)
    event_response = community_client.post(
        "/events", json={"title": "Opening", "datetime": future.isoformat(), "capacity": 2}
    )
    assert event_response.status_code == 201, event_response.text
    event_id = event_response.json()["id"]

    rsvp = community_client.post(
        f"/events/{event_id}/rsvps", json={"name": "Cam", "email": "cam@example.com"}
    )
    assert rsvp.status_code == 201, rsvp.text
    assert rsvp.json()["email"] == "cam@example.com"

    art_response = community_client.post(
        "/art-pieces",
        json={
            "artist": "Drew",
            "title": "Cadence",
            "price": 250.0,
            "commission_percent": 20.0,
        },
    )
    assert art_response.status_code == 201, art_response.text

    upcoming = community_client.get("/events/upcoming")
    gallery = community_client.get("/gallery")
    assert upcoming.status_code == 200
    assert [event["title"] for event in upcoming.json()] == ["Opening"]
    assert gallery.status_code == 200
    assert [piece["title"] for piece in gallery.json()] == ["Cadence"]


def test_event_crud_endpoints(community_client: TestClient) -> None:
    created = community_client.post(
        "/events",
        json={"title": "Draft title", "datetime": "2027-03-01T18:00:00", "capacity": 5},
    )
    event_id = created.json()["id"]

    fetched = community_client.get(f"/events/{event_id}")
    assert fetched.status_code == 200
    assert fetched.json()["title"] == "Draft title"

    updated = community_client.patch(f"/events/{event_id}", json={"title": "Final title"})
    assert updated.status_code == 200
    assert updated.json()["title"] == "Final title"

    deleted = community_client.delete(f"/events/{event_id}")
    assert deleted.status_code == 204
    assert community_client.get(f"/events/{event_id}").status_code == 404


def test_art_piece_crud_and_sale_endpoints(community_client: TestClient) -> None:
    created = community_client.post(
        "/art-pieces",
        json={"artist": "Eli", "title": "Sky", "price": 80.0, "commission_percent": 25.0},
    )
    assert created.status_code == 201
    piece_id = created.json()["id"]

    updated = community_client.patch(f"/art-pieces/{piece_id}", json={"price": 120.0})
    assert updated.status_code == 200
    assert updated.json()["price"] == 120.0

    sold = community_client.post(f"/art-pieces/{piece_id}/sell")
    assert sold.status_code == 200
    assert sold.json()["salon_commission"] == pytest.approx(30.0)
    assert sold.json()["artist_payout"] == pytest.approx(90.0)

    deleted = community_client.delete(f"/art-pieces/{piece_id}")
    assert deleted.status_code == 204
    assert community_client.get(f"/art-pieces/{piece_id}").status_code == 404


def test_community_write_requires_operator(session: Session) -> None:
    app = FastAPI()
    app.include_router(community_router)
    app.dependency_overrides[get_session] = lambda: session
    with TestClient(app) as client:
        response = client.post(
            "/events",
            json={"title": "Private write", "datetime": "2027-03-01T18:00:00", "capacity": 5},
        )
    assert response.status_code in (401, 403)
