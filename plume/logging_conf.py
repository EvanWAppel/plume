"""Logging configuration (S2).

Idempotent stdlib logging setup so re-imports/app restarts don't stack handlers.
Level comes from the ``PLUME_LOG_LEVEL`` env var (default INFO) unless overridden.
"""

from __future__ import annotations

import logging
import os

_CONFIGURED = False
_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def configure_logging(level: str | None = None) -> None:
    """Configure root logging. Safe to call many times (idempotent handler-wise)."""
    global _CONFIGURED
    resolved = (level or os.getenv("PLUME_LOG_LEVEL", "INFO")).upper()
    root = logging.getLogger()
    root.setLevel(resolved)
    if not _CONFIGURED:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter(_FORMAT))
        root.addHandler(handler)
        _CONFIGURED = True
