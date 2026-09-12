"""ASGI entrypoint for hosts that look for ``main:app`` at the repo root.

Railway's Railpack builder detects FastAPI and starts
``uvicorn main:app --host 0.0.0.0 --port $PORT``. The real app factory lives
in ``plume.main``; this module re-exports it so we don't have to maintain a
separate start command in the dashboard.
"""

from plume.main import app

__all__ = ["app"]
