"""Opaque, server-side session authentication for the self-hosted API."""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from base64 import urlsafe_b64decode, urlsafe_b64encode
from binascii import Error as Base64Error
from dataclasses import dataclass

from fastapi import Cookie, Depends, HTTPException, Request, status


SESSION_COOKIE_NAME = os.getenv("SESSION_COOKIE_NAME", "scholar_session")
PASSWORD_SCHEME = "scrypt"
PASSWORD_N = 2 ** 14
PASSWORD_R = 8
PASSWORD_P = 1
PASSWORD_KEY_LENGTH = 32


def generate_token() -> str:
    """Return a high-entropy token suitable for login links or sessions."""
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    """Hash bearer material before storing or querying it."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    derived = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=PASSWORD_N,
        r=PASSWORD_R,
        p=PASSWORD_P,
        dklen=PASSWORD_KEY_LENGTH,
    )
    return "$".join((
        PASSWORD_SCHEME,
        str(PASSWORD_N),
        str(PASSWORD_R),
        str(PASSWORD_P),
        urlsafe_b64encode(salt).decode("ascii"),
        urlsafe_b64encode(derived).decode("ascii"),
    ))


def verify_password(password: str, encoded: str) -> bool:
    try:
        scheme, n, r, p, salt, expected = encoded.split("$", 5)
        if scheme != PASSWORD_SCHEME:
            return False
        derived = hashlib.scrypt(
            password.encode("utf-8"),
            salt=urlsafe_b64decode(salt.encode("ascii")),
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(urlsafe_b64decode(expected.encode("ascii"))),
        )
        return hmac.compare_digest(
            derived,
            urlsafe_b64decode(expected.encode("ascii")),
        )
    except (Base64Error, TypeError, ValueError):
        return False


@dataclass(frozen=True)
class AuthUser:
    id: str
    username: str
    role: str = "user"

    @property
    def can_view_admin(self) -> bool:
        return self.role in {"admin", "super_admin"}

    @property
    def can_manage_admins(self) -> bool:
        return self.role == "super_admin"


def optional_user(
    request: Request,
    session_token: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> AuthUser | None:
    if not session_token:
        return None
    repository = request.app.state.repository
    user = repository.get_user_by_session(hash_token(session_token))
    if not user:
        request.state.auth_user = None
        return None
    auth_user = AuthUser(
        id=str(user["id"]),
        username=str(user["username"]),
        role=str(user.get("role") or "user"),
    )
    request.state.auth_user = auth_user
    return auth_user


def require_user(user: AuthUser | None = Depends(optional_user)) -> AuthUser:
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )
    return user


def require_admin(user: AuthUser = Depends(require_user)) -> AuthUser:
    if not user.can_view_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrator access required",
        )
    return user


def require_super_admin(user: AuthUser = Depends(require_user)) -> AuthUser:
    if not user.can_manage_admins:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Super administrator access required",
        )
    return user
