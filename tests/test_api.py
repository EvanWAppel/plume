"""S7 — end-to-end HTTP: health, reserve, conflict, availability."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_health(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_reserve_endpoint_and_conflict(client: TestClient, make_member, make_station) -> None:
    member = make_member()
    station = make_station()
    payload = {"member_id": member.id, "station_id": station.id, "date": "2099-10-01"}

    created = client.post("/reservations", json=payload)
    assert created.status_code == 201, created.text
    assert created.json()["id"] is not None

    duplicate = client.post("/reservations", json=payload)
    assert duplicate.status_code == 409


def test_available_endpoint(client: TestClient, make_member, make_station) -> None:
    member = make_member()
    booked = make_station(name="C1")
    free = make_station(name="C2")
    client.post(
        "/reservations",
        json={"member_id": member.id, "station_id": booked.id, "date": "2099-10-01"},
    )

    response = client.get("/stations/available", params={"date": "2099-10-01"})
    assert response.status_code == 200
    ids = {s["id"] for s in response.json()}
    assert free.id in ids
    assert booked.id not in ids
