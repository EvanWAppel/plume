"""Auth API (E5): login + operator-gated register.

Bootstrap rule: when NO users exist yet, ``POST /auth/register`` creates the
first OPERATOR without authentication. Once any user exists, registration is
gated behind ``require_operator``.

``/auth/me`` and ``/auth/operator-only`` exercise the E3 dependencies and are
handy probes for the eventual UI (Group F).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlmodel import Session, select

from plume.auth.models import Role, User
from plume.auth.service import (
    authenticate,
    create_access_token,
    get_current_user,
    get_optional_user,
    hash_password,
    require_operator,
)
from plume.db import get_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    email: str
    password: str


class RegisterRequest(BaseModel):
    email: str
    password: str
    role: Role = Role.MEMBER
    member_id: int | None = None


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserPublic(BaseModel):
    id: int
    email: str
    role: Role
    member_id: int | None = None


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, session: Session = Depends(get_session)) -> TokenResponse:
    user = authenticate(session, str(payload.email), payload.password)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return TokenResponse(access_token=create_access_token(user))


def _users_exist(session: Session) -> bool:
    return session.exec(select(User)).first() is not None


@router.post("/register", response_model=UserPublic, status_code=status.HTTP_201_CREATED)
def register(
    payload: RegisterRequest,
    session: Session = Depends(get_session),
    caller: User | None = Depends(get_optional_user),
) -> User:
    """Create a user.

    - Bootstrap: if no users exist, create the first OPERATOR unauthenticated.
    - Otherwise: require an authenticated operator. A missing token yields 401
      (via ``require_operator`` -> ``get_current_user``); a non-operator yields
      403.
    """
    if not _users_exist(session):
        # Bootstrap the very first account as an operator regardless of the
        # requested role — someone has to be able to administer the system.
        logger.info("register: bootstrapping first operator email=%s", payload.email)
        role = Role.OPERATOR
    else:
        # Users already exist: enforce operator-gating. Reuse the same
        # dependencies so behavior matches the guarded routes exactly.
        require_operator(get_current_user(caller))
        if session.exec(select(User).where(User.email == str(payload.email))).first() is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="email already registered",
            )
        logger.info(
            "register: operator creating user email=%s role=%s", payload.email, payload.role
        )
        role = payload.role
    user = User(
        email=str(payload.email),
        hashed_password=hash_password(payload.password),
        role=role,
        member_id=payload.member_id,
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


@router.get("/me", response_model=UserPublic)
def me(current_user: User = Depends(get_current_user)) -> User:
    return current_user


@router.get("/operator-only", response_model=UserPublic)
def operator_only(current_user: User = Depends(require_operator)) -> User:
    return current_user
