"""Member API (Group A — A4).

Domain errors from the service are translated to HTTP status codes here at the
boundary — messages preserved, causes chained, nothing swallowed.
"""

from __future__ import annotations

import logging
from datetime import date as date_type

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session

from plume.auth.models import User
from plume.auth.service import require_operator
from plume.db import get_session
from plume.members.models import Member, Status, Tier
from plume.members.service import (
    MemberNotFoundError,
    OnboardingIncompleteError,
    list_members,
    onboard_member,
    update_member,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/members", tags=["members"])


class MemberCreate(BaseModel):
    name: str
    email: str
    phone: str | None = None
    license_number: str | None = None
    license_expiry: date_type | None = None
    insurance_on_file: bool = False
    tier: Tier = Tier.OPEN_STUDIO
    status: Status = Status.PROSPECT


class MemberUpdate(BaseModel):
    name: str | None = None
    email: str | None = None
    phone: str | None = None
    license_number: str | None = None
    license_expiry: date_type | None = None
    insurance_on_file: bool | None = None
    tier: Tier | None = None
    status: Status | None = None


@router.post("", status_code=201)
def create_member(
    payload: MemberCreate,
    session: Session = Depends(get_session),
    _op: User = Depends(require_operator),
) -> Member:
    try:
        return onboard_member(
            session,
            name=payload.name,
            email=payload.email,
            phone=payload.phone,
            license_number=payload.license_number,
            license_expiry=payload.license_expiry,
            insurance_on_file=payload.insurance_on_file,
            tier=payload.tier,
            status=payload.status,
        )
    except OnboardingIncompleteError as exc:
        # Invalid combination of inputs → 422 (unprocessable entity).
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("")
def get_members(
    status: Status | None = None, session: Session = Depends(get_session)
) -> list[Member]:
    return list_members(session, status=status)


@router.get("/{member_id}")
def get_member(member_id: int, session: Session = Depends(get_session)) -> Member:
    member = session.get(Member, member_id)
    if member is None:
        raise HTTPException(status_code=404, detail=f"member {member_id} not found")
    return member


@router.patch("/{member_id}")
def patch_member(
    member_id: int,
    payload: MemberUpdate,
    session: Session = Depends(get_session),
    _op: User = Depends(require_operator),
) -> Member:
    try:
        return update_member(
            session,
            member_id,
            name=payload.name,
            email=payload.email,
            phone=payload.phone,
            license_number=payload.license_number,
            license_expiry=payload.license_expiry,
            insurance_on_file=payload.insurance_on_file,
            tier=payload.tier,
            status=payload.status,
        )
    except MemberNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except OnboardingIncompleteError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
