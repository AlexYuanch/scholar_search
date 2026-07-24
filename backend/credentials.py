"""Encrypted storage helpers for user-owned upstream API credentials."""
from __future__ import annotations

import os

from cryptography.fernet import Fernet, InvalidToken


class CredentialConfigurationError(RuntimeError):
    """Raised when the server cannot safely encrypt user credentials."""


class CredentialDecryptionError(RuntimeError):
    """Raised when a stored credential cannot be decrypted."""


# Development-only key. Production startup/deployment validation rejects using it.
DEVELOPMENT_CREDENTIAL_ENCRYPTION_KEY = (
    "KpR3gIpJbT8J76mKjJf0k0ZnmuwFh89fV4E7LMA5GVQ="
)


def _configured_key() -> str:
    value = os.getenv("CREDENTIAL_ENCRYPTION_KEY", "").strip()
    app_env = os.getenv("APP_ENV", "development").strip().casefold()
    if value:
        if app_env == "production" and value == DEVELOPMENT_CREDENTIAL_ENCRYPTION_KEY:
            raise CredentialConfigurationError(
                "CREDENTIAL_ENCRYPTION_KEY must be unique in production"
            )
        return value
    if app_env in {"development", "test"}:
        return DEVELOPMENT_CREDENTIAL_ENCRYPTION_KEY
    raise CredentialConfigurationError(
        "CREDENTIAL_ENCRYPTION_KEY is required in production"
    )


def _fernet() -> Fernet:
    try:
        return Fernet(_configured_key().encode("ascii"))
    except (TypeError, ValueError) as exc:
        raise CredentialConfigurationError(
            "CREDENTIAL_ENCRYPTION_KEY must be a valid Fernet key"
        ) from exc


def encrypt_secret(secret: str) -> str:
    value = secret.strip()
    if not value:
        raise ValueError("Credential cannot be empty")
    return _fernet().encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_secret(encrypted_secret: str) -> str:
    try:
        return _fernet().decrypt(encrypted_secret.encode("ascii")).decode("utf-8")
    except (InvalidToken, UnicodeError, ValueError) as exc:
        raise CredentialDecryptionError(
            "Stored credential cannot be decrypted with the configured key"
        ) from exc


def secret_hint(secret: str) -> str:
    value = secret.strip()
    return f"••••{value[-4:]}" if value else ""


def validate_credential_configuration() -> None:
    _fernet()
