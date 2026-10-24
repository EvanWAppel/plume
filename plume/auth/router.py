"""Auth API (E5): login + operator-gated register.

``POST /auth/register`` always requires an operator's token, even when no users
exist (PLAT-SEC-02). There is no unauthenticated bootstrap: the first operator
comes from the seed (``PLUME_SEED_OPERATOR_PASSWORD``) or from
``python -m plume.auth.cli create-operator`` run on the host.

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
    login_configured,
    login_not_configured_exc,
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
    if not login_configured():
        logger.error("login: refused, signing secret not configured")
        raise login_not_configured_exc()
    user = authenticate(session, str(payload.email), payload.password)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return TokenResponse(access_token=create_access_token(user))


@router.post("/register", response_model=UserPublic, status_code=status.HTTP_201_CREATED)
def register(
    payload: RegisterRequest,
    session: Session = Depends(get_session),
    caller: User | None = Depends(get_optional_user),
) -> User:
    """Create a user. Operator only, always.

    A missing token yields 401 (via ``require_operator`` -> ``get_current_user``);
    a non-operator yields 403. An empty users table changes nothing: no request
    can create the first operator (PLAT-SEC-02).
    """
    if caller is None and session.exec(select(User)).first() is None:
        logger.warning(
            "register: refused unauthenticated request on an empty users table; create the "
            "first operator with `python -m plume.auth.cli create-operator` or the seed"
        )
    operator = require_operator(get_current_user(caller))
    if session.exec(select(User).where(User.email == str(payload.email))).first() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="email already registered",
        )
    logger.info(
        "register: operator id=%s creating user email=%s role=%s",
        operator.id,
        payload.email,
        payload.role,
    )
    user = User(
        email=str(payload.email),
        hashed_password=hash_password(payload.password),
        role=payload.role,
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
