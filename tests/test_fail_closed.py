"""PLAT-SEC-01: sign-in fails closed when ``PLUME_SECRET_KEY`` is unset or empty.

There is no dev-default signing secret. Without a configured key the app still
serves ``/health`` and public pages, but it refuses every sign-in (API and web)
and every presented token, and says "Login not configured" instead.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path

import jwt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import Session, select

import plume.auth.service as auth_service
from plume.auth.models import Role, User
from plume.auth.service import (
    ALGORITHM,
    LoginNotConfiguredError,
    create_access_token,
    get_secret_key,
    login_configured,
)
from plume.db import get_engine, get_session, reset_engine
from plume.main import create_app
from plume.seed import OPERATOR_EMAIL, OPERATOR_PASSWORD
from plume.web.router import COOKIE_NAME, web_router

SECRET_ENV = "PLUME_SECRET_KEY"
# The old hardcoded dev default; it must never sign or verify anything again.
OLD_DEV_SECRET = "dev-secret-change-me"
UNCONFIGURED = [pytest.param(None, id="unset"), pytest.param("", id="empty")]
# Forging with the 20-byte old default trips PyJWT's short-key warning on purpose.
_forging_old_default = pytest.mark.filterwarnings("ignore::jwt.warnings.InsecureKeyLengthWarning")


def _configure(monkeypatch: pytest.MonkeyPatch, value: str | None) -> None:
    if value is None:
        monkeypatch.delenv(SECRET_ENV, raising=False)
    else:
        monkeypatch.setenv(SECRET_ENV, value)


@pytest.fixture
def web_client(session: Session) -> Iterator[TestClient]:
    app = FastAPI()
    app.include_router(web_router)

    def override_get_session() -> Iterator[Session]:
        yield session

    app.dependency_overrides[get_session] = override_get_session
    with TestClient(app, follow_redirects=False) as client:
        yield client
    app.dependency_overrides.clear()


def test_no_dev_default_secret_remains() -> None:
    assert not hasattr(auth_service, "_DEV_SECRET")
    assert OLD_DEV_SECRET not in Path(auth_service.__file__).read_text()


@pytest.mark.parametrize("value", UNCONFIGURED)
def test_unconfigured_secret_is_none(monkeypatch: pytest.MonkeyPatch, value: str | None) -> None:
    _configure(monkeypatch, value)
    assert get_secret_key() is None
    assert login_configured() is False


def test_configured_secret_is_returned(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(SECRET_ENV, "x" * 40)
    assert get_secret_key() == "x" * 40
    assert login_configured() is True


@pytest.mark.parametrize("value", UNCONFIGURED)
def test_token_issuance_refused(
    monkeypatch: pytest.MonkeyPatch, value: str | None, make_user: Callable[..., User]
) -> None:
    user = make_user()
    _configure(monkeypatch, value)
    with pytest.raises(LoginNotConfiguredError):
        create_access_token(user)


@pytest.mark.parametrize("value", UNCONFIGURED)
def test_api_login_refused_with_503(
    monkeypatch: pytest.MonkeyPatch,
    value: str | None,
    client: TestClient,
    make_user: Callable[..., User],
) -> None:
    make_user(email="op@example.com", password="pw")
    _configure(monkeypatch, value)
    resp = client.post("/auth/login", json={"email": "op@example.com", "password": "pw"})
    assert resp.status_code == 503
    assert "Login not configured" in resp.json()["detail"]
    assert "access_token" not in resp.text


@_forging_old_default
@pytest.mark.parametrize("value", UNCONFIGURED)
def test_api_rejects_tokens_signed_with_old_dev_default(
    monkeypatch: pytest.MonkeyPatch,
    value: str | None,
    client: TestClient,
    make_user: Callable[..., User],
) -> None:
    user = make_user(role=Role.OPERATOR)
    forged = jwt.encode(
        {"sub": str(user.id), "role": "operator"}, OLD_DEV_SECRET, algorithm=ALGORITHM
    )
    _configure(monkeypatch, value)
    resp = client.get("/auth/me", headers={"Authorization": f"Bearer {forged}"})
    assert resp.status_code == 503
    assert "Login not configured" in resp.json()["detail"]


@pytest.mark.parametrize("value", UNCONFIGURED)
def test_api_rejects_previously_valid_token(
    monkeypatch: pytest.MonkeyPatch,
    value: str | None,
    client: TestClient,
    operator_token: str,
) -> None:
    """A token issued while configured stops working once the key is removed."""
    _configure(monkeypatch, value)
    resp = client.get("/auth/me", headers={"Authorization": f"Bearer {operator_token}"})
    assert resp.status_code == 503


@pytest.mark.parametrize("value", UNCONFIGURED)
def test_web_login_page_shows_notice_not_form(
    monkeypatch: pytest.MonkeyPatch, value: str | None, web_client: TestClient
) -> None:
    _configure(monkeypatch, value)
    resp = web_client.get("/login")
    assert resp.status_code == 503
    assert "Login not configured" in resp.text
    assert 'name="password"' not in resp.text


@pytest.mark.parametrize("value", UNCONFIGURED)
def test_web_login_submit_refused(
    monkeypatch: pytest.MonkeyPatch,
    value: str | None,
    web_client: TestClient,
    make_user: Callable[..., User],
) -> None:
    make_user(email="op@example.com", password="pw", role=Role.OPERATOR)
    _configure(monkeypatch, value)
    resp = web_client.post("/login", data={"email": "op@example.com", "password": "pw"})
    assert resp.status_code == 503
    assert "Login not configured" in resp.text
    assert COOKIE_NAME not in resp.cookies


@_forging_old_default
@pytest.mark.parametrize("value", UNCONFIGURED)
def test_web_dashboard_with_old_cookie_redirects(
    monkeypatch: pytest.MonkeyPatch,
    value: str | None,
    web_client: TestClient,
    make_user: Callable[..., User],
) -> None:
    user = make_user(role=Role.OPERATOR)
    for token in (
        create_access_token(user),
        jwt.encode({"sub": str(user.id)}, OLD_DEV_SECRET, algorithm=ALGORITHM),
    ):
        _configure(monkeypatch, value)
        web_client.cookies.set(COOKIE_NAME, token)
        resp = web_client.get("/dashboard")
        assert resp.status_code == 302
        assert resp.headers["location"] == "/login"
        monkeypatch.setenv(SECRET_ENV, "k" * 40)


@pytest.mark.parametrize("value", UNCONFIGURED)
def test_health_still_serves(
    monkeypatch: pytest.MonkeyPatch, value: str | None, client: TestClient
) -> None:
    _configure(monkeypatch, value)
    assert client.get("/health").json() == {"status": "ok"}


# --- demo seed on deploy: no published operator password ---------------------


def _seed_on_start(monkeypatch: pytest.MonkeyPatch, db_file: Path) -> User | None:
    monkeypatch.setenv("PLUME_SEED_ON_START", "1")
    monkeypatch.setenv("PLUME_DATABASE_URL", f"sqlite:///{db_file.as_posix()}")
    reset_engine()
    try:
        with TestClient(create_app()) as client:
            assert client.get("/health").json() == {"status": "ok"}
        if not db_file.exists():
            return None
        with Session(get_engine()) as session:
            return session.exec(select(User).where(User.email == OPERATOR_EMAIL)).first()
    finally:
        reset_engine()


@pytest.mark.parametrize("value", [None, ""], ids=["unset", "empty"])
def test_seed_on_start_without_operator_password_skips_seed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, value: str | None
) -> None:
    """Never seed the README's public demo password into a deployed database."""
    if value is None:
        monkeypatch.delenv("PLUME_SEED_OPERATOR_PASSWORD", raising=False)
    else:
        monkeypatch.setenv("PLUME_SEED_OPERATOR_PASSWORD", value)
    assert _seed_on_start(monkeypatch, tmp_path / "preview.db") is None


def test_seed_on_start_uses_operator_password_from_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from plume.auth.service import verify_password

    monkeypatch.setenv("PLUME_SEED_OPERATOR_PASSWORD", "a-private-demo-password")
    operator = _seed_on_start(monkeypatch, tmp_path / "preview.db")
    assert operator is not None
    assert verify_password("a-private-demo-password", operator.hashed_password)
    assert not verify_password(OPERATOR_PASSWORD, operator.hashed_password)
