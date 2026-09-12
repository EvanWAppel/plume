"""Database engine + session management (S3).

Uses SQLModel over SQLite. Tests inject an in-memory engine via the
``get_session`` dependency override, so the module-level file engine is only
created lazily on first real use.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

from sqlalchemy.engine import Engine
from sqlmodel import Session, SQLModel, create_engine

DEFAULT_URL = "sqlite:///plume.db"


def database_url() -> str:
    """SQLAlchemy URL. ``PLUME_DATABASE_URL`` overrides the local SQLite file."""
    return os.getenv("PLUME_DATABASE_URL", DEFAULT_URL)


def _import_models() -> None:
    """Import model modules so their tables register on SQLModel.metadata."""
    from plume.auth import models as _auth  # noqa: F401
    from plume.billing import models as _billing  # noqa: F401
    from plume.community import models as _community  # noqa: F401
    from plume.members import models as _members  # noqa: F401
    from plume.reservations import models as _reservations  # noqa: F401
    from plume.spaces import models as _spaces  # noqa: F401


def make_engine(url: str = DEFAULT_URL, *, echo: bool = False) -> Engine:
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    return create_engine(url, echo=echo, connect_args=connect_args)


def init_db(engine: Engine) -> None:
    """Create all tables. Imports models first so metadata is populated."""
    _import_models()
    SQLModel.metadata.create_all(engine)


_engine: Engine | None = None


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = make_engine(database_url())
        init_db(_engine)
    return _engine


def reset_engine() -> None:
    """Dispose the cached engine. Tests call this when ``PLUME_DATABASE_URL`` changes."""
    global _engine
    if _engine is not None:
        _engine.dispose()
        _engine = None


def get_session() -> Iterator[Session]:
    """FastAPI dependency yielding a DB session (overridden in tests)."""
    with Session(get_engine()) as session:
        yield session
