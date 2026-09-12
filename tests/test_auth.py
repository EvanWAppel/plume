"""Tests for Group E — Auth & roles (E1, E2, E3, E5).

TDD: these are written before the implementation. A local FastAPI app mounts
the auth router (the global app does not include it), per the collision rules.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterator

import jwt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from plume.auth.models import Role, User
from plume.auth.router import router
from plume.auth.service import (
    ALGORITHM,
    authenticate,
    create_access_token,
    get_secret_key,
    hash_password,
    verify_password,
)
from plume.db import get_session


@pytest.fixture
def auth_client(session: Session) -> Iterator[TestClient]:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_session] = lambda: session
    with TestClient(app) as c:
        yield c


def _make_user(
    session: Session,
    email: str = "op@example.com",
    password: str = "s3cret-pw",
    role: Role = Role.OPERATOR,
) -> User:
    user = User(email=email, hashed_password=hash_password(password), role=role)
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


# --- E1: User model, password never stored plaintext ---------------------


def test_user_model_persists_and_password_is_hashed(session: Session) -> None:
    raw = "plaintext-password"
    user = User(email="rory@example.com", hashed_password=hash_password(raw), role=Role.OPERATOR)
    session.add(user)
    session.commit()
    session.refresh(user)

    reloaded = session.exec(select(User).where(User.email == "rory@example.com")).one()
    assert reloaded.id is not None
    assert reloaded.hashed_password != raw
    assert reloaded.role == Role.OPERATOR
    assert reloaded.member_id is None


def test_user_email_is_unique(session: Session) -> None:
    _make_user(session, email="dupe@example.com")
    with pytest.raises(Exception):  # noqa: B017 - integrity error surfaces on commit
        _make_user(session, email="dupe@example.com")


def test_user_can_link_to_member(session: Session, make_member) -> None:  # noqa: ANN001
    member = make_member()
    user = User(
        email="member@example.com",
        hashed_password=hash_password("pw"),
        role=Role.MEMBER,
        member_id=member.id,
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    assert user.member_id == member.id


# --- E2: hashing + authenticate ------------------------------------------


def test_verify_password_correct_and_wrong() -> None:
    hashed = hash_password("correct-horse")
    assert verify_password("correct-horse", hashed) is True
    assert verify_password("wrong-horse", hashed) is False


def test_authenticate_correct_credentials(session: Session) -> None:
    _make_user(session, email="auth@example.com", password="right-pw")
    user = authenticate(session, "auth@example.com", "right-pw")
    assert user is not None
    assert user.email == "auth@example.com"


def test_authenticate_wrong_password_returns_none(session: Session) -> None:
    _make_user(session, email="auth2@example.com", password="right-pw")
    assert authenticate(session, "auth2@example.com", "wrong-pw") is None


def test_authenticate_unknown_email_returns_none(session: Session) -> None:
    assert authenticate(session, "nobody@example.com", "whatever") is None


# --- E3: tokens + get_current_user + require_operator --------------------


def test_create_access_token_encodes_sub_role_and_expiry(session: Session) -> None:
    user = _make_user(session, email="tok@example.com", role=Role.OPERATOR)
    token = create_access_token(user)
    payload = jwt.decode(token, get_secret_key(), algorithms=[ALGORITHM])
    assert payload["sub"] == str(user.id)
    assert payload["role"] == Role.OPERATOR.value
    assert "exp" in payload


def test_valid_token_resolves_to_user(auth_client: TestClient, session: Session) -> None:
    user = _make_user(session, email="whoami@example.com", role=Role.OPERATOR)
    token = create_access_token(user)
    resp = auth_client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json()["email"] == "whoami@example.com"


def test_missing_token_is_401(auth_client: TestClient) -> None:
    resp = auth_client.get("/auth/me")
    assert resp.status_code == 401


def test_tampered_token_is_401(auth_client: TestClient, session: Session) -> None:
    user = _make_user(session, email="tamper@example.com")
    token = create_access_token(user)
    tampered = token[:-3] + ("abc" if not token.endswith("abc") else "xyz")
    resp = auth_client.get("/auth/me", headers={"Authorization": f"Bearer {tampered}"})
    assert resp.status_code == 401


def test_expired_token_is_401(auth_client: TestClient, session: Session) -> None:
    user = _make_user(session, email="expired@example.com")
    expired_payload = {
        "sub": str(user.id),
        "role": user.role.value,
        "exp": dt.datetime.now(dt.UTC) - dt.timedelta(minutes=5),
    }
    expired = jwt.encode(expired_payload, get_secret_key(), algorithm=ALGORITHM)
    resp = auth_client.get("/auth/me", headers={"Authorization": f"Bearer {expired}"})
    assert resp.status_code == 401


def test_require_operator_allows_operator(auth_client: TestClient, session: Session) -> None:
    user = _make_user(session, email="op-only@example.com", role=Role.OPERATOR)
    token = create_access_token(user)
    resp = auth_client.get("/auth/operator-only", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200


def test_require_operator_rejects_member_with_403(
    auth_client: TestClient, session: Session
) -> None:
    user = _make_user(session, email="mem-only@example.com", role=Role.MEMBER)
    token = create_access_token(user)
    resp = auth_client.get("/auth/operator-only", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403


# --- E5: login + register (bootstrap + operator-gated) -------------------


def test_login_returns_token(auth_client: TestClient, session: Session) -> None:
    _make_user(session, email="login@example.com", password="my-password")
    resp = auth_client.post(
        "/auth/login", json={"email": "login@example.com", "password": "my-password"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    payload = jwt.decode(body["access_token"], get_secret_key(), algorithms=[ALGORITHM])
    assert payload["role"] == Role.OPERATOR.value


def test_login_bad_credentials_is_401(auth_client: TestClient, session: Session) -> None:
    _make_user(session, email="login2@example.com", password="my-password")
    resp = auth_client.post("/auth/login", json={"email": "login2@example.com", "password": "nope"})
    assert resp.status_code == 401


def test_bootstrap_register_creates_first_operator(
    auth_client: TestClient, session: Session
) -> None:
    resp = auth_client.post(
        "/auth/register",
        json={"email": "first@example.com", "password": "pw", "role": "OPERATOR"},
    )
    assert resp.status_code == 201
    created = session.exec(select(User).where(User.email == "first@example.com")).one()
    assert created.role == Role.OPERATOR
    assert created.hashed_password != "pw"


def test_second_register_without_operator_token_is_rejected(
    auth_client: TestClient, session: Session
) -> None:
    # bootstrap the first operator
    _make_user(session, email="boss@example.com", role=Role.OPERATOR)
    # a second, unauthenticated register must be rejected (users already exist)
    resp = auth_client.post(
        "/auth/register",
        json={"email": "sneaky@example.com", "password": "pw", "role": "MEMBER"},
    )
    assert resp.status_code in (401, 403)


def test_operator_can_register_new_user(auth_client: TestClient, session: Session) -> None:
    operator = _make_user(session, email="boss2@example.com", role=Role.OPERATOR)
    token = create_access_token(operator)
    resp = auth_client.post(
        "/auth/register",
        json={"email": "hired@example.com", "password": "pw", "role": "MEMBER"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201
    created = session.exec(select(User).where(User.email == "hired@example.com")).one()
    assert created.role == Role.MEMBER
