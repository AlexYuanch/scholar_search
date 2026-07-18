"""Opaque, server-side session authentication for the self-hosted API."""
from __future__ import annotations

import hashlib
import os
import secrets
from dataclasses import dataclass

from fastapi import Cookie, Depends, HTTPException, Request, status


SESSION_COOKIE_NAME = os.getenv("SESSION_COOKIE_NAME", "scholar_session")


def generate_token() -> str:
    """Return a high-entropy token suitable for login links or sessions."""
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    """Hash bearer material before storing or querying it."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class AuthUser:
    id: str
    email: str


def optional_user(
    request: Request,
    session_token: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> AuthUser | None:
    if not session_token:
        return None
    repository = request.app.state.repository
    user = repository.get_user_by_session(hash_token(session_token))
    if not user:
        return None
    return AuthUser(id=str(user["id"]), email=str(user["email"]))


def require_user(user: AuthUser | None = Depends(optional_user)) -> AuthUser:
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )
    return user
