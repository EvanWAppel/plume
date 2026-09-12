"""FastAPI app factory + router wiring (S7)."""

from __future__ import annotations

from fastapi import FastAPI

from plume.auth.router import router as auth_router
from plume.billing.router import router as billing_router
from plume.community.router import router as community_router
from plume.logging_conf import configure_logging
from plume.members.router import router as members_router
from plume.reservations.router import router as reservations_router
from plume.spaces.router import router as spaces_router
from plume.web.router import web_router


def create_app() -> FastAPI:
    configure_logging()
    app = FastAPI(title="plume")
    app.include_router(auth_router)
    app.include_router(billing_router)
    app.include_router(community_router)
    app.include_router(members_router)
    app.include_router(reservations_router)
    app.include_router(spaces_router)
    app.include_router(web_router)

    @app.get("/health", tags=["health"])
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
