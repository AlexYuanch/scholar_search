from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from auth import AuthUser, generate_token, hash_token, optional_user, require_user
from main import app
from repository import InMemoryRepository


def test_optional_auth_allows_anonymous_request():
    local_app = FastAPI()
    local_app.state.repository = InMemoryRepository()

    @local_app.get("/public")
    def public(user=Depends(optional_user)):
        return {"user": user.id if user else None}

    response = TestClient(local_app).get("/public")

    assert response.status_code == 200
    assert response.json() == {"user": None}


def test_required_auth_rejects_anonymous_request():
    local_app = FastAPI()
    local_app.state.repository = InMemoryRepository()

    @local_app.get("/private")
    def private(user: AuthUser = Depends(require_user)):
        return {"user": user.id}

    response = TestClient(local_app).get("/private")

    assert response.status_code == 401


def test_opaque_session_cookie_returns_user():
    local_app = FastAPI()
    repository = InMemoryRepository()
    local_app.state.repository = repository
    raw_session = generate_token()
    repository.users["a@example.com"] = {
        "id": "user-1",
        "email": "a@example.com",
        "normalized_email": "a@example.com",
        "is_active": True,
    }
    repository.sessions[hash_token(raw_session)] = {
        "user_id": "user-1",
        "expires_at": datetime.now(timezone.utc) + timedelta(days=1),
        "revoked_at": None,
    }

    @local_app.get("/private")
    def private(user: AuthUser = Depends(require_user)):
        return {"user": user.id, "email": user.email}

    response = TestClient(local_app).get(
        "/private",
        cookies={"scholar_session": raw_session},
    )

    assert response.status_code == 200
    assert response.json() == {"user": "user-1", "email": "a@example.com"}


def test_magic_link_is_one_time_and_creates_revocable_session(monkeypatch):
    import main

    repository = InMemoryRepository()
    monkeypatch.setattr(main, "repository", repository)
    monkeypatch.setattr(app.state, "repository", repository)
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("AUTH_DEV_RETURN_MAGIC_LINK", "true")
    monkeypatch.setenv("COOKIE_SECURE", "false")
    monkeypatch.setenv("PUBLIC_APP_URL", "http://localhost:5173")

    with TestClient(app) as client:
        requested = client.post("/api/auth/magic-link", json={"email": "User@Example.com"})
        assert requested.status_code == 200
        magic_link = requested.json()["dev_magic_link"]
        callback_path = urlparse(magic_link).path + "?" + urlparse(magic_link).query

        callback = client.get(callback_path, follow_redirects=False)
        assert callback.status_code == 303
        assert callback.headers["location"].endswith("/?login=success")

        me = client.get("/api/auth/me")
        assert me.json()["authenticated"] is True
        assert me.json()["user"]["email"] == "User@example.com"

        replay = client.get(callback_path, follow_redirects=False)
        assert replay.status_code == 400

        assert client.post("/api/auth/logout").status_code == 200
        assert client.get("/api/auth/me").json()["authenticated"] is False


def test_token_hash_is_stable_and_does_not_store_raw_token():
    token = generate_token()

    assert len(token) >= 32
    assert hash_token(token) == hash_token(token)
    assert token not in hash_token(token)
