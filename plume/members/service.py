"""Member business rules (Group A — A2/A3).

Errors are raised, never swallowed — the router (A4) translates them to HTTP
status codes at the boundary.
"""

from __future__ import annotations

import logging
from datetime import date as date_type

from sqlmodel import Session, select

from plume.members.models import Member, Status, Tier

logger = logging.getLogger(__name__)


class MemberNotFoundError(Exception):
    """No member exists with the requested id."""


class OnboardingIncompleteError(Exception):
    """A member cannot be ACTIVE without a license number and insurance on file."""


def _assert_active_allowed(member: Member) -> None:
    """A3: activation requires both a license number and insurance on file."""
    if member.status != Status.ACTIVE:
        return
    missing = []
    if not member.license_number:
        missing.append("license_number")
    if not member.insurance_on_file:
        missing.append("insurance_on_file")
    if missing:
        logger.info("onboarding incomplete: member=%s missing=%s", member.id, missing)
        raise OnboardingIncompleteError("cannot set member ACTIVE without: " + ", ".join(missing))


def _get_or_raise(session: Session, member_id: int) -> Member:
    member = session.get(Member, member_id)
    if member is None:
        logger.info("member not found: id=%s", member_id)
        raise MemberNotFoundError(f"member {member_id} not found")
    return member


def onboard_member(
    session: Session,
    *,
    name: str,
    email: str,
    phone: str | None = None,
    license_number: str | None = None,
    license_expiry: date_type | None = None,
    insurance_on_file: bool = False,
    tier: Tier = Tier.OPEN_STUDIO,
    status: Status = Status.PROSPECT,
) -> Member:
    member = Member(
        name=name,
        email=email,
        phone=phone,
        license_number=license_number,
        license_expiry=license_expiry,
        insurance_on_file=insurance_on_file,
        tier=tier,
        status=status,
    )
    _assert_active_allowed(member)
    session.add(member)
    session.commit()
    session.refresh(member)
    logger.info("onboarded member: id=%s status=%s tier=%s", member.id, member.status, member.tier)
    return member


def update_member(
    session: Session,
    member_id: int,
    *,
    name: str | None = None,
    email: str | None = None,
    phone: str | None = None,
    license_number: str | None = None,
    license_expiry: date_type | None = None,
    insurance_on_file: bool | None = None,
    tier: Tier | None = None,
    status: Status | None = None,
) -> Member:
    member = _get_or_raise(session, member_id)

    if name is not None:
        member.name = name
    if email is not None:
        member.email = email
    if phone is not None:
        member.phone = phone
    if license_number is not None:
        member.license_number = license_number
    if license_expiry is not None:
        member.license_expiry = license_expiry
    if insurance_on_file is not None:
        member.insurance_on_file = insurance_on_file
    if tier is not None:
        member.tier = tier
    if status is not None:
        member.status = status

    _assert_active_allowed(member)
    session.add(member)
    session.commit()
    session.refresh(member)
    logger.info("updated member: id=%s status=%s", member.id, member.status)
    return member


def deactivate_member(session: Session, member_id: int) -> Member:
    member = _get_or_raise(session, member_id)
    member.status = Status.INACTIVE
    session.add(member)
    session.commit()
    session.refresh(member)
    logger.info("deactivated member: id=%s", member.id)
    return member


def list_members(session: Session, status: Status | None = None) -> list[Member]:
    statement = select(Member)
    if status is not None:
        statement = statement.where(Member.status == status)
    return list(session.exec(statement).all())
