"""Auth business logic (E2 + E3).

- Password hashing/verification with ``bcrypt`` (never log or store plaintext).
- ``authenticate`` resolves a user by email + password.
- JWT issuance (``create_access_token``) and decoding.
- FastAPI dependencies ``get_current_user`` and ``require_operator`` that the
  orchestrator applies to other routers in E4.

Errors are raised at the boundary as ``HTTPException`` (401/403); nothing is
swallowed. The signing secret comes from ``PLUME_SECRET_KEY`` with a dev
default that MUST be overridden in production.
"""

from __future__ import annotations

import datetime as dt
import logging
import os

import bcrypt
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlmodel import Session, select

from plume.auth.models import Role, User
from plume.db import get_session

logger = logging.getLogger(__name__)

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60
# Dev-only default; MUST be overridden via PLUME_SECRET_KEY in production.
# (HS256 emits an InsecureKeyLengthWarning for this short dev key — expected in
# dev; production keys from PLUME_SECRET_KEY should be >=32 bytes.)
_DEV_SECRET = "dev-secret-change-me"

# tokenUrl points at the login route so OpenAPI's "Authorize" flow works.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login", auto_error=False)


def get_secret_key() -> str:
    """Signing secret from env with a dev default (override in production)."""
    return os.getenv("PLUME_SECRET_KEY", _DEV_SECRET)


# --- E2: password hashing + authentication -------------------------------


def hash_password(raw: str) -> str:
    """Return a bcrypt hash of ``raw``. Never logs or stores the plaintext."""
    hashed = bcrypt.hashpw(raw.encode("utf-8"), bcrypt.gensalt())
    return hashed.decode("utf-8")


def verify_password(raw: str, hashed: str) -> bool:
    """True iff ``raw`` matches the stored bcrypt ``hashed`` value."""
    return bcrypt.checkpw(raw.encode("utf-8"), hashed.encode("utf-8"))


def authenticate(session: Session, email: str, password: str) -> User | None:
    """Return the user if email exists and the password verifies, else None."""
    user = session.exec(select(User).where(User.email == email)).first()
    if user is None:
        logger.info("authenticate: no user for email=%s", email)
        return None
    if not verify_password(password, user.hashed_password):
        logger.info("authenticate: bad password for email=%s", email)
        return None
    logger.info("authenticate: success for email=%s", email)
    return user


# --- E3: JWT issuance + dependencies -------------------------------------


def create_access_token(user: User, *, expires_minutes: int = ACCESS_TOKEN_EXPIRE_MINUTES) -> str:
    """Encode a signed JWT carrying the user id (``sub``), role, and expiry."""
    if user.id is None:
        raise ValueError("cannot issue a token for an unsaved user (id is None)")
    now = dt.datetime.now(dt.UTC)
    payload = {
        "sub": str(user.id),
        "role": user.role.value,
        "exp": now + dt.timedelta(minutes=expires_minutes),
        "iat": now,
    }
    return jwt.encode(payload, get_secret_key(), algorithm=ALGORITHM)


_CREDENTIALS_EXC = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Could not validate credentials",
    headers={"WWW-Authenticate": "Bearer"},
)


def get_optional_user(
    token: str | None = Depends(oauth2_scheme),
    session: Session = Depends(get_session),
) -> User | None:
    """Resolve the bearer token to a ``User`` or ``None``.

    Returns ``None`` for a missing token; raises ``HTTPException(401)`` for a
    malformed, tampered, or expired token, or a ``sub`` that no longer maps to a
    user. Used by endpoints (like register) that must distinguish "no caller"
    from "invalid caller".
    """
    if not token:
        return None
    try:
        payload = jwt.decode(token, get_secret_key(), algorithms=[ALGORITHM])
    except jwt.PyJWTError as exc:
        logger.info("get_optional_user: token decode failed: %s", exc)
        raise _CREDENTIALS_EXC from exc
    sub = payload.get("sub")
    if sub is None:
        logger.info("get_optional_user: token missing sub")
        raise _CREDENTIALS_EXC
    user = session.get(User, int(sub))
    if user is None:
        logger.info("get_optional_user: no user for sub=%s", sub)
        raise _CREDENTIALS_EXC
    return user


def get_current_user(user: User | None = Depends(get_optional_user)) -> User:
    """Decode the bearer token and load the ``User``.

    Raises ``HTTPException(401)`` on a missing, malformed, tampered, or expired
    token, or when the referenced user no longer exists.
    """
    if user is None:
        logger.info("get_current_user: missing bearer token")
        raise _CREDENTIALS_EXC
    return user


def require_operator(current_user: User = Depends(get_current_user)) -> User:
    """Dependency that permits only OPERATOR users; raises 403 otherwise.

    Applied to write endpoints on other routers by the orchestrator (E4).
    """
    if current_user.role != Role.OPERATOR:
        logger.info(
            "require_operator: forbidden for user=%s role=%s", current_user.id, current_user.role
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Operator role required",
        )
    return current_user
