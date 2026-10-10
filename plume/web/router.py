"""Group F — web UI router (server-rendered HTMX + Jinja pages).

Design notes
------------
- Pages call the existing SERVICE functions directly via ``Depends(get_session)``
  rather than round-tripping through the JSON API.
- Auth uses an **HttpOnly cookie** ``plume_session`` holding the same JWT the
  JSON API issues. ``current_operator_from_cookie`` decodes it, loads the
  ``User``, and requires ``Role.OPERATOR`` — redirecting to ``/login`` (302)
  on any missing / invalid / non-operator case.
- Errors are surfaced, never swallowed: domain errors from the reservation
  service are caught only to re-render the page with a visible message (the
  cause is chained), and unexpected errors propagate.
- HTMX is loaded from a CDN in the base template — no StaticFiles mount.

Page paths (``/``, ``/login``, ``/logout``, ``/dashboard``, ``/book``) are
deliberately disjoint from the JSON API prefixes (``/members``, ``/stations``,
``/suites``, ``/reservations``, ``/invoices``, ``/billing``, ``/auth``,
``/health``) so mounting this router alongside the API causes no collisions.
"""

from __future__ import annotations

import logging
from datetime import date as date_type
from pathlib import Path
from typing import Annotated

import jwt
from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session

from plume.auth.models import Role, User
from plume.auth.service import (
    ALGORITHM,
    authenticate,
    create_access_token,
    get_secret_key,
)
from plume.billing.service import generate_monthly_invoices, list_invoices
from plume.db import get_session
from plume.members.service import list_members
from plume.reservations.service import (
    MemberInactiveError,
    PastDateError,
    StationInactiveError,
    StationUnavailableError,
    available_stations,
    reserve_station,
)
from plume.spaces.service import list_stations, list_suites

logger = logging.getLogger(__name__)

COOKIE_NAME = "plume_session"

_TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

web_router = APIRouter(tags=["web"])


# --- auth: cookie-based operator dependency ---------------------------------


class _RedirectToLogin(Exception):
    """Sentinel used to convert a failed cookie check into a 302 redirect.

    Raised inside ``current_operator_from_cookie`` and translated by the
    ``operator_or_redirect`` dependency into a ``RedirectResponse``. This keeps
    the "who is the operator" logic in one place while still letting FastAPI
    short-circuit the request with a redirect response.
    """


def _load_operator_from_cookie(request: Request, session: Session) -> User | None:
    """Decode the ``plume_session`` cookie and return the OPERATOR user, or None.

    Returns ``None`` (rather than raising) for every failure mode — missing
    cookie, malformed / tampered / expired JWT, unknown subject, or a
    non-operator role — so the caller can uniformly redirect to ``/login``.
    """
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        logger.info("web auth: no %s cookie", COOKIE_NAME)
        return None
    try:
        payload = jwt.decode(token, get_secret_key(), algorithms=[ALGORITHM])
    except jwt.PyJWTError as exc:
        logger.info("web auth: cookie decode failed: %s", exc)
        return None
    sub = payload.get("sub")
    if sub is None:
        logger.info("web auth: cookie missing sub")
        return None
    user = session.get(User, int(sub))
    if user is None:
        logger.info("web auth: no user for sub=%s", sub)
        return None
    if user.role != Role.OPERATOR:
        logger.info("web auth: user=%s role=%s is not operator", user.id, user.role)
        return None
    return user


def current_operator_from_cookie(request: Request, session: Session = Depends(get_session)) -> User:
    """Dependency: require an OPERATOR from the session cookie.

    On any failure it raises ``_RedirectToLogin``, which the route's
    ``RedirectResponse`` handling turns into a 302 to ``/login``.
    """
    user = _load_operator_from_cookie(request, session)
    if user is None:
        raise _RedirectToLogin
    return user


def _login_redirect() -> RedirectResponse:
    return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)


# --- F1: landing page -------------------------------------------------------


@web_router.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "index.html", {})


# --- favicon ----------------------------------------------------------------


@web_router.get("/favicon.svg", include_in_schema=False)
def favicon_svg() -> FileResponse:
    return FileResponse(_TEMPLATES_DIR / "favicon.svg", media_type="image/svg+xml")


@web_router.get("/favicon.ico", include_in_schema=False)
def favicon_ico() -> RedirectResponse:
    """Browsers probe ``/favicon.ico`` regardless of the ``<link>``; point them at the SVG.

    Temporary (307) on purpose: browsers cache a 301 indefinitely, so adding a
    real ``.ico`` later would never reach returning visitors.
    """
    return RedirectResponse(url="/favicon.svg", status_code=status.HTTP_307_TEMPORARY_REDIRECT)


# --- F4: auth ---------------------------------------------------------------


@web_router.get("/login", response_class=HTMLResponse)
def login_form(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "login.html", {"error": None})


@web_router.post("/login", response_model=None)
def login_submit(
    request: Request,
    email: Annotated[str, Form()],
    password: Annotated[str, Form()],
    session: Session = Depends(get_session),
) -> HTMLResponse | RedirectResponse:
    user = authenticate(session, email, password)
    if user is None:
        logger.info("web login failed for email=%s", email)
        return templates.TemplateResponse(
            request,
            "login.html",
            {"error": "Invalid email or password."},
            status_code=status.HTTP_200_OK,
        )
    token = create_access_token(user)
    logger.info("web login success for user=%s", user.id)
    response = RedirectResponse(url="/dashboard", status_code=status.HTTP_302_FOUND)
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        httponly=True,
        samesite="lax",
    )
    return response


@web_router.get("/logout")
def logout() -> RedirectResponse:
    response = RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    response.delete_cookie(key=COOKIE_NAME)
    logger.info("web logout: cleared %s cookie", COOKIE_NAME)
    return response


# --- F2: operator dashboard -------------------------------------------------


def _render_dashboard(
    request: Request, session: Session, *, billing_message: str | None = None
) -> HTMLResponse:
    """Assemble members, stations, suites (with occupancy), and invoices."""
    members = list_members(session)
    stations = list_stations(session)
    suites = list_suites(session)
    # Map suite occupant ids to member names so the template can show occupancy.
    member_names = {m.id: m.name for m in members}
    suite_rows = [
        {
            "suite": suite,
            "occupant_name": member_names.get(suite.occupant_member_id)
            if suite.occupant_member_id is not None
            else None,
        }
        for suite in suites
    ]
    invoices = list_invoices(session)
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "members": members,
            "stations": stations,
            "suite_rows": suite_rows,
            "invoices": invoices,
            "billing_message": billing_message,
        },
    )


@web_router.get("/dashboard", response_class=HTMLResponse, response_model=None)
def dashboard(
    request: Request,
    session: Session = Depends(get_session),
) -> HTMLResponse | RedirectResponse:
    try:
        current_operator_from_cookie(request, session)
    except _RedirectToLogin:
        return _login_redirect()
    return _render_dashboard(request, session)


@web_router.post("/dashboard/run-billing", response_model=None)
def run_billing(
    request: Request,
    period: Annotated[str, Form()],
    session: Session = Depends(get_session),
) -> HTMLResponse | RedirectResponse:
    try:
        current_operator_from_cookie(request, session)
    except _RedirectToLogin:
        return _login_redirect()
    created = generate_monthly_invoices(session, period)
    logger.info("web run-billing: period=%s created=%d", period, len(created))
    message = f"Generated {len(created)} invoice(s) for {period}."
    return _render_dashboard(request, session, billing_message=message)


# --- F3: stylist booking view -----------------------------------------------


def _render_book(
    request: Request,
    session: Session,
    on_date: date_type,
    *,
    error: str | None = None,
    notice: str | None = None,
) -> HTMLResponse:
    stations = available_stations(session, on_date)
    members = list_members(session)
    return templates.TemplateResponse(
        request,
        "book.html",
        {
            "stations": stations,
            "members": members,
            "on_date": on_date.isoformat(),
            "error": error,
            "notice": notice,
        },
    )


@web_router.get("/book", response_class=HTMLResponse)
def book_page(
    request: Request,
    date: date_type | None = None,
    session: Session = Depends(get_session),
) -> HTMLResponse:
    on_date = date if date is not None else date_type.today()
    return _render_book(request, session, on_date)


@web_router.post("/book", response_class=HTMLResponse)
def book_submit(
    request: Request,
    member_id: Annotated[int, Form()],
    station_id: Annotated[int, Form()],
    date: Annotated[date_type, Form()],
    session: Session = Depends(get_session),
) -> HTMLResponse:
    try:
        reserve_station(session, member_id, station_id, date)
    except StationUnavailableError as exc:
        logger.info("web book conflict: %s", exc)
        return _render_book(request, session, date, error=str(exc))
    except (StationInactiveError, MemberInactiveError, PastDateError) as exc:
        logger.info("web book rejected: %s", exc)
        return _render_book(request, session, date, error=str(exc))
    logger.info("web book ok: member=%s station=%s date=%s", member_id, station_id, date)
    return _render_book(request, session, date, notice="Reservation created.")
