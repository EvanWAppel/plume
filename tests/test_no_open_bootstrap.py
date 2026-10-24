"""PLAT-SEC-02: no unauthenticated path may create an operator.

``POST /auth/register`` used to make the first user an OPERATOR, unauthenticated,
whenever the users table was empty. The Railway service has no volume, so every
deploy boots with an empty SQLite DB and whoever registered first owned it.

Now registration always needs an operator's token. The first operator comes only
from a trusted channel: seed-on-start (``PLUME_SEED_OPERATOR_PASSWORD``) or the
``create-operator`` CLI run in a shell on the host (e.g. ``railway ssh``).
"""

from __future__ import annotations

from collections.abc import Callable, Iterator

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from plume.auth import cli
from plume.auth.models import Role, User
from plume.auth.service import (
    EmptyPasswordError,
    UserExistsError,
    authenticate,
    create_access_token,
    create_operator,
)
from plume.db import get_engine, init_db, reset_engine


def _users(session: Session) -> list[User]:
    return list(session.exec(select(User)).all())


# --- the hole: register against an empty DB -------------------------------


@pytest.mark.parametrize("role", ["OPERATOR", "MEMBER", None])
def test_register_against_empty_db_cannot_yield_an_operator(
    client: TestClient, session: Session, role: str | None
) -> None:
    """The full app, empty users table, no token: nobody gets created, least of all an operator."""
    assert _users(session) == []
    body: dict[str, str] = {"email": "first@example.com", "password": "pw"}
    if role is not None:
        body["role"] = role

    resp = client.post("/auth/register", json=body)

    assert resp.status_code == 401
    assert _users(session) == []
    # and there is no operator to sign in as
    assert authenticate(session, "first@example.com", "pw") is None


def test_register_against_empty_db_with_garbage_token_is_refused(
    client: TestClient, session: Session
) -> None:
    resp = client.post(
        "/auth/register",
        json={"email": "first@example.com", "password": "pw", "role": "OPERATOR"},
        headers={"Authorization": "Bearer not-a-token"},
    )
    assert resp.status_code == 401
    assert _users(session) == []


def test_member_cannot_register_anyone(
    client: TestClient, session: Session, make_user: Callable[..., User]
) -> None:
    member = make_user(email="stylist@example.com", role=Role.MEMBER)
    resp = client.post(
        "/auth/register",
        json={"email": "promoted@example.com", "password": "pw", "role": "OPERATOR"},
        headers={"Authorization": f"Bearer {create_access_token(member)}"},
    )
    assert resp.status_code == 403
    assert session.exec(select(User).where(User.email == "promoted@example.com")).first() is None


def test_operator_can_still_register_an_operator(
    client: TestClient, session: Session, operator_token: str
) -> None:
    resp = client.post(
        "/auth/register",
        json={"email": "co-owner@example.com", "password": "pw", "role": "OPERATOR"},
        headers={"Authorization": f"Bearer {operator_token}"},
    )
    assert resp.status_code == 201
    created = session.exec(select(User).where(User.email == "co-owner@example.com")).one()
    assert created.role == Role.OPERATOR


def test_operator_register_duplicate_email_is_409(client: TestClient, operator_token: str) -> None:
    resp = client.post(
        "/auth/register",
        json={"email": "operator@example.com", "password": "pw"},
        headers={"Authorization": f"Bearer {operator_token}"},
    )
    assert resp.status_code == 409


# --- trusted channel: create_operator service -----------------------------


def test_create_operator_makes_an_operator_with_a_hashed_password(session: Session) -> None:
    user = create_operator(session, email="owner@example.com", password="s3cret-pass")
    assert user.id is not None
    assert user.role == Role.OPERATOR
    assert user.hashed_password != "s3cret-pass"
    assert authenticate(session, "owner@example.com", "s3cret-pass") == user


@pytest.mark.parametrize("password", ["", "   "])
def test_create_operator_refuses_an_empty_password(session: Session, password: str) -> None:
    with pytest.raises(EmptyPasswordError):
        create_operator(session, email="owner@example.com", password=password)
    assert _users(session) == []


def test_create_operator_refuses_an_empty_email(session: Session) -> None:
    with pytest.raises(ValueError):
        create_operator(session, email="  ", password="s3cret-pass")
    assert _users(session) == []


def test_create_operator_refuses_an_existing_email(
    session: Session, make_user: Callable[..., User]
) -> None:
    make_user(email="taken@example.com", role=Role.MEMBER)
    with pytest.raises(UserExistsError):
        create_operator(session, email="taken@example.com", password="s3cret-pass")
    taken = session.exec(select(User).where(User.email == "taken@example.com")).one()
    assert taken.role == Role.MEMBER


# --- trusted channel: the CLI ---------------------------------------------


@pytest.fixture
def cli_db(tmp_path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Session]:
    """Point the CLI's real engine at a temp SQLite file; yield a session on it."""
    monkeypatch.setenv("PLUME_DATABASE_URL", f"sqlite:///{tmp_path / 'cli.db'}")
    reset_engine()
    engine = get_engine()
    init_db(engine)
    with Session(engine) as session:
        yield session
    reset_engine()


def _prompts(*answers: str) -> Callable[[str], str]:
    it = iter(answers)
    return lambda _prompt: next(it)


def test_cli_create_operator_creates_the_first_operator(
    cli_db: Session, capsys: pytest.CaptureFixture[str]
) -> None:
    code = cli.main(
        ["create-operator", "--email", "owner@example.com"],
        read_password=_prompts("s3cret-pass", "s3cret-pass"),
    )
    assert code == 0
    user = cli_db.exec(select(User).where(User.email == "owner@example.com")).one()
    assert user.role == Role.OPERATOR
    out = capsys.readouterr().out
    assert "owner@example.com" in out
    assert "s3cret-pass" not in out


def test_cli_refuses_mismatched_passwords(cli_db: Session) -> None:
    code = cli.main(
        ["create-operator", "--email", "owner@example.com"],
        read_password=_prompts("s3cret-pass", "typo-pass"),
    )
    assert code != 0
    assert _users(cli_db) == []


def test_cli_refuses_an_empty_password(cli_db: Session) -> None:
    code = cli.main(
        ["create-operator", "--email", "owner@example.com"],
        read_password=_prompts("", ""),
    )
    assert code != 0
    assert _users(cli_db) == []


def test_cli_refuses_an_existing_email(cli_db: Session) -> None:
    create_operator(cli_db, email="owner@example.com", password="first-pass")
    code = cli.main(
        ["create-operator", "--email", "owner@example.com"],
        read_password=_prompts("other-pass", "other-pass"),
    )
    assert code != 0
    assert len(_users(cli_db)) == 1


def test_cli_requires_a_command() -> None:
    with pytest.raises(SystemExit) as exc:
        cli.main([])
    assert exc.value.code != 0
