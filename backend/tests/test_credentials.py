import pytest
from cryptography.fernet import Fernet

from credentials import (
    CredentialConfigurationError,
    CredentialDecryptionError,
    decrypt_secret,
    encrypt_secret,
    secret_hint,
)


def test_credential_round_trip_and_hint_do_not_reveal_secret(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv(
        "CREDENTIAL_ENCRYPTION_KEY",
        Fernet.generate_key().decode("ascii"),
    )
    secret = "openalex-user-owned-secret"

    encrypted = encrypt_secret(secret)

    assert encrypted != secret
    assert secret not in encrypted
    assert decrypt_secret(encrypted) == secret
    assert secret_hint(secret) == "••••cret"


def test_credential_cannot_be_decrypted_with_another_server_key(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv(
        "CREDENTIAL_ENCRYPTION_KEY",
        Fernet.generate_key().decode("ascii"),
    )
    encrypted = encrypt_secret("openalex-secret")
    monkeypatch.setenv(
        "CREDENTIAL_ENCRYPTION_KEY",
        Fernet.generate_key().decode("ascii"),
    )

    with pytest.raises(CredentialDecryptionError):
        decrypt_secret(encrypted)


def test_production_requires_explicit_encryption_key(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("CREDENTIAL_ENCRYPTION_KEY", raising=False)

    with pytest.raises(CredentialConfigurationError):
        encrypt_secret("openalex-secret")
