"""Group F — minimal server-rendered web UI (HTMX + Jinja).

This package owns the human-facing pages. It calls the existing service
functions directly via ``Depends(get_session)`` and renders Jinja templates.
Page routes live on ``web_router`` under paths that do NOT collide with the
JSON API (``/``, ``/login``, ``/logout``, ``/dashboard``, ``/book``).
"""

from __future__ import annotations

from plume.web.router import web_router

__all__ = ["web_router"]
