"""Integration tests over the fully wired global app (post-integration pass).

Exercises real auth (E4): the write endpoints require an operator token, reads
and the reservation flow stay open. Uses the shared ``client`` fixture (global
app) plus ``operator_token``/``member_token`` from conftest.
"""

from __future__ import annotations

from collections.abc import Callable

from fastapi.testclient import TestClient

from plume.auth.models import User


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_health_ok(client: TestClient) -> None:
    assert client.get("/health").status_code == 200


def test_login_returns_token(client: TestClient, make_user: Callable[..., User]) -> None:
    make_user(email="login@example.com", password="secret")
    resp = client.post("/auth/login", json={"email": "login@example.com", "password": "secret"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["access_token"]
    assert body["token_type"].lower() == "bearer"


def test_login_bad_password_rejected(client: TestClient, make_user: Callable[..., User]) -> None:
    make_user(email="login2@example.com", password="secret")
    resp = client.post("/auth/login", json={"email": "login2@example.com", "password": "wrong"})
    assert resp.status_code == 401


# --- E4: member writes are operator-only, reads are open --------------------


def test_create_member_requires_auth(client: TestClient) -> None:
    resp = client.post("/members", json={"name": "New", "email": "new@example.com"})
    assert resp.status_code == 401


def test_create_member_forbidden_for_member_role(client: TestClient, member_token: str) -> None:
    resp = client.post(
        "/members",
        json={"name": "New", "email": "new@example.com"},
        headers=_bearer(member_token),
    )
    assert resp.status_code == 403


def test_create_member_allowed_for_operator(client: TestClient, operator_token: str) -> None:
    resp = client.post(
        "/members",
        json={"name": "New", "email": "new@example.com"},
        headers=_bearer(operator_token),
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["email"] == "new@example.com"


def test_list_members_is_open(client: TestClient) -> None:
    # Reads are not guarded.
    assert client.get("/members").status_code == 200


# --- E4: space writes are operator-only -------------------------------------


def test_create_station_requires_operator(client: TestClient, member_token: str) -> None:
    assert client.post("/stations", json={"name": "Chair X"}).status_code == 401
    assert (
        client.post(
            "/stations", json={"name": "Chair X"}, headers=_bearer(member_token)
        ).status_code
        == 403
    )


def test_create_station_allowed_for_operator(client: TestClient, operator_token: str) -> None:
    resp = client.post("/stations", json={"name": "Chair X"}, headers=_bearer(operator_token))
    assert resp.status_code == 201, resp.text


# --- reservation flow + availability stay open (Group C adds booking auth) --


def test_reservation_flow_still_open(client: TestClient, make_member, make_station) -> None:
    member = make_member()
    station = make_station()
    payload = {"member_id": member.id, "station_id": station.id, "date": "2026-10-01"}
    assert client.post("/reservations", json=payload).status_code == 201
    assert client.post("/reservations", json=payload).status_code == 409
    avail = client.get("/stations/available", params={"date": "2026-10-01"})
    assert avail.status_code == 200
