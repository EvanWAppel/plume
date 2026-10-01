"""Railway/host entrypoint: root ``main:app``, DB URL env, seed-on-start."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from sqlmodel import Session, select

import main as root_main
from plume.auth.models import User
from plume.db import database_url, get_engine, reset_engine
from plume.main import app as plume_app
from plume.main import create_app
from plume.seed import OPERATOR_EMAIL


def test_root_main_reexports_app() -> None:
    assert root_main.app is plume_app


def test_database_url_defaults_and_env(monkeypatch) -> None:
    monkeypatch.delenv("PLUME_DATABASE_URL", raising=False)
    assert database_url() == "sqlite:///plume.db"

    monkeypatch.setenv("PLUME_DATABASE_URL", "sqlite:////data/plume.db")
    assert database_url() == "sqlite:////data/plume.db"


def test_seed_on_start_loads_demo_operator(monkeypatch, tmp_path: Path) -> None:
    db_file = tmp_path / "preview.db"
    monkeypatch.setenv("PLUME_SEED_ON_START", "1")
    monkeypatch.setenv("PLUME_DATABASE_URL", f"sqlite:///{db_file.as_posix()}")
    reset_engine()
    try:
        with TestClient(create_app()) as client:
            assert client.get("/health").json() == {"status": "ok"}
        with Session(get_engine()) as session:
            operator = session.exec(select(User).where(User.email == OPERATOR_EMAIL)).one()
            assert operator.email == OPERATOR_EMAIL
    finally:
        reset_engine()


def test_seed_on_start_off_does_not_touch_file_db(monkeypatch, tmp_path: Path) -> None:
    db_file = tmp_path / "untouched.db"
    monkeypatch.setenv("PLUME_SEED_ON_START", "0")
    monkeypatch.setenv("PLUME_DATABASE_URL", f"sqlite:///{db_file.as_posix()}")
    reset_engine()
    try:
        with TestClient(create_app()) as client:
            assert client.get("/health").status_code == 200
        assert not db_file.exists()
    finally:
        reset_engine()
