"""S2 — logging configuration is idempotent and honors the level."""

from __future__ import annotations

import logging

from plume.logging_conf import configure_logging


def test_configure_logging_sets_level_and_is_idempotent() -> None:
    configure_logging("DEBUG")
    root = logging.getLogger()
    assert root.level == logging.DEBUG

    handler_count = len(root.handlers)
    configure_logging("INFO")
    assert root.level == logging.INFO
    # No duplicate handlers added on re-configure.
    assert len(root.handlers) == handler_count
