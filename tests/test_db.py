"""S3 — init_db creates tables and a row round-trips."""

from __future__ import annotations

from sqlalchemy.engine import Engine
from sqlmodel import Session, select

from plume.spaces.models import Station


def test_init_db_creates_tables_and_roundtrips(engine: Engine) -> None:
    with Session(engine) as session:
        station = Station(name="Chair A")
        session.add(station)
        session.commit()
        session.refresh(station)
        assert station.id is not None

        loaded = session.exec(select(Station).where(Station.id == station.id)).one()
        assert loaded.name == "Chair A"
        assert loaded.active is True
