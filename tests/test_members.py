"""Group A — Members / stylists: model, service, and router tests (TDD-first)."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, date, datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import Session

from plume.auth.models import Role, User
from plume.auth.service import require_operator
from plume.db import get_session
from plume.members.models import Member, Status, Tier
from plume.members.router import router
from plume.members.service import (
    MemberNotFoundError,
    OnboardingIncompleteError,
    deactivate_member,
    list_members,
    onboard_member,
    update_member,
)


@pytest.fixture
def members_client(session: Session) -> Iterator[TestClient]:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_session] = lambda: session
    # These are focused endpoint tests; bypass the operator guard (auth is
    # exercised end-to-end in tests/test_integration.py).
    app.dependency_overrides[require_operator] = lambda: User(
        email="op@test", hashed_password="x", role=Role.OPERATOR
    )
    with TestClient(app) as c:
        yield c


# --- A1: model ---------------------------------------------------------------


def test_member_backward_compatible_construction(session: Session) -> None:
    """The pre-existing call sites (conftest, other groups) still work."""
    member = Member(name="Rory", email="rory@example.com")
    session.add(member)
    session.commit()
    session.refresh(member)
    assert member.id is not None
    assert member.name == "Rory"
    assert member.email == "rory@example.com"


def test_member_defaults(session: Session) -> None:
    member = Member(name="Rory", email="rory@example.com")
    session.add(member)
    session.commit()
    session.refresh(member)

    assert member.phone is None
    assert member.license_number is None
    assert member.license_expiry is None
    assert member.insurance_on_file is False
    assert member.tier == Tier.OPEN_STUDIO
    assert member.status == Status.PROSPECT
    assert member.created_at is not None
    # timezone-aware
    assert member.created_at.tzinfo is not None


def test_member_accepts_all_fields(session: Session) -> None:
    member = Member(
        name="Ada",
        email="ada@example.com",
        phone="555-0100",
        license_number="COS-123",
        license_expiry=date(2027, 1, 1),
        insurance_on_file=True,
        tier=Tier.PRIVATE_STUDIO,
        status=Status.ACTIVE,
    )
    session.add(member)
    session.commit()
    session.refresh(member)
    assert member.tier == Tier.PRIVATE_STUDIO
    assert member.status == Status.ACTIVE
    assert member.license_expiry == date(2027, 1, 1)


def test_tier_and_status_enum_values() -> None:
    assert Tier.OPEN_STUDIO == "OPEN_STUDIO"
    assert Tier.PRIVATE_STUDIO == "PRIVATE_STUDIO"
    assert Status.PROSPECT == "PROSPECT"
    assert Status.ACTIVE == "ACTIVE"
    assert Status.INACTIVE == "INACTIVE"


# --- A2: service -------------------------------------------------------------


def test_onboard_member_persists(session: Session) -> None:
    member = onboard_member(session, name="Rory", email="rory@example.com")
    assert member.id is not None
    assert member.status == Status.PROSPECT
    assert member.tier == Tier.OPEN_STUDIO


def test_onboard_member_with_optional_fields(session: Session) -> None:
    member = onboard_member(
        session,
        name="Ada",
        email="ada@example.com",
        phone="555-0100",
        license_number="COS-9",
        tier=Tier.PRIVATE_STUDIO,
    )
    assert member.phone == "555-0100"
    assert member.license_number == "COS-9"
    assert member.tier == Tier.PRIVATE_STUDIO


def test_update_member_changes_fields(session: Session) -> None:
    member = onboard_member(session, name="Rory", email="rory@example.com")
    updated = update_member(session, member.id, phone="555-0199")
    assert updated.phone == "555-0199"


def test_update_member_missing_raises(session: Session) -> None:
    with pytest.raises(MemberNotFoundError):
        update_member(session, 9999, phone="x")


def test_deactivate_flips_status(session: Session) -> None:
    member = onboard_member(session, name="Rory", email="rory@example.com")
    result = deactivate_member(session, member.id)
    assert result.status == Status.INACTIVE


def test_deactivate_missing_raises(session: Session) -> None:
    with pytest.raises(MemberNotFoundError):
        deactivate_member(session, 9999)


def test_list_members_filters_by_status(session: Session) -> None:
    active = onboard_member(
        session,
        name="Ada",
        email="ada@example.com",
        license_number="COS-9",
        insurance_on_file=True,
        status=Status.ACTIVE,
    )
    prospect = onboard_member(session, name="Rory", email="rory@example.com")

    all_members = list_members(session)
    assert {m.id for m in all_members} == {active.id, prospect.id}

    only_active = list_members(session, status=Status.ACTIVE)
    assert {m.id for m in only_active} == {active.id}

    only_prospect = list_members(session, status=Status.PROSPECT)
    assert {m.id for m in only_prospect} == {prospect.id}


# --- A3: onboarding rule -----------------------------------------------------


def test_cannot_activate_without_license_or_insurance(session: Session) -> None:
    with pytest.raises(OnboardingIncompleteError):
        onboard_member(session, name="Rory", email="rory@example.com", status=Status.ACTIVE)


def test_cannot_activate_without_insurance(session: Session) -> None:
    with pytest.raises(OnboardingIncompleteError):
        onboard_member(
            session,
            name="Rory",
            email="rory@example.com",
            license_number="COS-9",
            status=Status.ACTIVE,
        )


def test_cannot_activate_without_license(session: Session) -> None:
    with pytest.raises(OnboardingIncompleteError):
        onboard_member(
            session,
            name="Rory",
            email="rory@example.com",
            insurance_on_file=True,
            status=Status.ACTIVE,
        )


def test_can_activate_with_license_and_insurance(session: Session) -> None:
    member = onboard_member(
        session,
        name="Rory",
        email="rory@example.com",
        license_number="COS-9",
        insurance_on_file=True,
        status=Status.ACTIVE,
    )
    assert member.status == Status.ACTIVE


def test_update_to_active_enforces_rule(session: Session) -> None:
    member = onboard_member(session, name="Rory", email="rory@example.com")
    with pytest.raises(OnboardingIncompleteError):
        update_member(session, member.id, status=Status.ACTIVE)

    updated = update_member(
        session,
        member.id,
        license_number="COS-9",
        insurance_on_file=True,
        status=Status.ACTIVE,
    )
    assert updated.status == Status.ACTIVE


# --- A4: router --------------------------------------------------------------


def test_create_member_endpoint(members_client: TestClient) -> None:
    response = members_client.post("/members", json={"name": "Rory", "email": "rory@example.com"})
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["id"] is not None
    assert body["status"] == "PROSPECT"
    assert body["tier"] == "OPEN_STUDIO"


def test_create_member_invalid_input_422(members_client: TestClient) -> None:
    response = members_client.post("/members", json={"name": "Rory"})
    assert response.status_code == 422


def test_create_member_activation_rule_returns_422(members_client: TestClient) -> None:
    response = members_client.post(
        "/members",
        json={"name": "Rory", "email": "rory@example.com", "status": "ACTIVE"},
    )
    assert response.status_code == 422, response.text


def test_list_members_endpoint(members_client: TestClient) -> None:
    members_client.post("/members", json={"name": "Rory", "email": "rory@example.com"})
    members_client.post(
        "/members",
        json={
            "name": "Ada",
            "email": "ada@example.com",
            "license_number": "COS-9",
            "insurance_on_file": True,
            "status": "ACTIVE",
        },
    )

    all_resp = members_client.get("/members")
    assert all_resp.status_code == 200
    assert len(all_resp.json()) == 2

    active_resp = members_client.get("/members", params={"status": "ACTIVE"})
    assert active_resp.status_code == 200
    body = active_resp.json()
    assert len(body) == 1
    assert body[0]["name"] == "Ada"


def test_get_member_endpoint(members_client: TestClient) -> None:
    created = members_client.post(
        "/members", json={"name": "Rory", "email": "rory@example.com"}
    ).json()
    response = members_client.get(f"/members/{created['id']}")
    assert response.status_code == 200
    assert response.json()["email"] == "rory@example.com"


def test_get_member_missing_404(members_client: TestClient) -> None:
    response = members_client.get("/members/9999")
    assert response.status_code == 404


def test_patch_member_endpoint(members_client: TestClient) -> None:
    created = members_client.post(
        "/members", json={"name": "Rory", "email": "rory@example.com"}
    ).json()
    response = members_client.patch(f"/members/{created['id']}", json={"phone": "555-0199"})
    assert response.status_code == 200
    assert response.json()["phone"] == "555-0199"


def test_patch_member_missing_404(members_client: TestClient) -> None:
    response = members_client.patch("/members/9999", json={"phone": "x"})
    assert response.status_code == 404


def test_patch_member_activation_rule_422(members_client: TestClient) -> None:
    created = members_client.post(
        "/members", json={"name": "Rory", "email": "rory@example.com"}
    ).json()
    response = members_client.patch(f"/members/{created['id']}", json={"status": "ACTIVE"})
    assert response.status_code == 422


def test_created_at_is_utc(session: Session) -> None:
    member = onboard_member(session, name="Rory", email="rory@example.com")
    assert member.created_at.tzinfo is not None
    # Compare to now in UTC to ensure it's a sane recent timestamp.
    now = datetime.now(UTC)
    assert (now - member.created_at).total_seconds() < 60
