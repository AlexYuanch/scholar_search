from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from auth import AuthUser, generate_token, hash_token, optional_user, require_user
from main import app
from repository import InMemoryRepository


class RecordingMailer:
    configured = True

    def __init__(self):
        self.messages = []

    def send_magic_link(self, email: str, magic_link: str) -> None:
        self.messages.append((email, magic_link))


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

    with TestClient(app, base_url="http://localhost:5173") as client:
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


def test_public_request_rejects_localhost_magic_link_configuration(monkeypatch):
    import main

    repository = InMemoryRepository()
    mailer = RecordingMailer()
    monkeypatch.setattr(main, "repository", repository)
    monkeypatch.setattr(app.state, "repository", repository)
    monkeypatch.setattr(main, "mailer", mailer)
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("AUTH_DEV_RETURN_MAGIC_LINK", "true")
    monkeypatch.setenv("PUBLIC_APP_URL", "http://localhost")

    with TestClient(app, base_url="http://203.0.113.10") as client:
        response = client.post("/api/auth/magic-link", json={"email": "user@example.com"})

    assert response.status_code == 503
    assert "PUBLIC_APP_URL" in response.json()["detail"]
    assert mailer.messages == []


def test_production_magic_link_requires_public_app_url(monkeypatch):
    import main

    repository = InMemoryRepository()
    mailer = RecordingMailer()
    monkeypatch.setattr(main, "repository", repository)
    monkeypatch.setattr(app.state, "repository", repository)
    monkeypatch.setattr(main, "mailer", mailer)
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("PUBLIC_APP_URL", raising=False)

    with TestClient(app, base_url="https://scholar.example.com") as client:
        response = client.post("/api/auth/magic-link", json={"email": "user@example.com"})

    assert response.status_code == 503
    assert "PUBLIC_APP_URL" in response.json()["detail"]
    assert mailer.messages == []


def test_production_magic_link_uses_configured_public_origin(monkeypatch):
    import main

    repository = InMemoryRepository()
    mailer = RecordingMailer()
    monkeypatch.setattr(main, "repository", repository)
    monkeypatch.setattr(app.state, "repository", repository)
    monkeypatch.setattr(main, "mailer", mailer)
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("AUTH_DEV_RETURN_MAGIC_LINK", "true")
    monkeypatch.setenv("PUBLIC_APP_URL", "https://scholar.example.com/")

    with TestClient(app, base_url="https://scholar.example.com") as client:
        response = client.post("/api/auth/magic-link", json={"email": "user@example.com"})

    assert response.status_code == 200
    assert "dev_magic_link" not in response.json()
    assert len(mailer.messages) == 1
    assert mailer.messages[0][1].startswith(
        "https://scholar.example.com/api/auth/callback?token="
    )


def test_token_hash_is_stable_and_does_not_store_raw_token():
    token = generate_token()

    assert len(token) >= 32
    assert hash_token(token) == hash_token(token)
    assert token not in hash_token(token)
