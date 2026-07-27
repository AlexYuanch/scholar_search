from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from auth import (
    AuthUser,
    generate_token,
    hash_password,
    hash_token,
    optional_user,
    require_user,
    verify_password,
)
from credentials import encrypt_secret
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


def test_password_hash_round_trip_and_uses_random_salt():
    first = hash_password("correct horse battery staple")
    second = hash_password("correct horse battery staple")

    assert first != second
    assert verify_password("correct horse battery staple", first)
    assert not verify_password("wrong password", first)
    assert not verify_password("password", "scrypt$16384$8$1$not-base64$also-invalid")


def test_opaque_session_cookie_returns_user():
    local_app = FastAPI()
    repository = InMemoryRepository()
    local_app.state.repository = repository
    raw_session = generate_token()
    user = repository.create_password_user("alice", hash_password("a secure password"))
    repository.sessions[hash_token(raw_session)] = {
        "user_id": user["id"],
        "expires_at": datetime.now(timezone.utc) + timedelta(days=1),
        "revoked_at": None,
    }

    @local_app.get("/private")
    def private(user: AuthUser = Depends(require_user)):
        return {"user": user.id, "username": user.username}

    response = TestClient(local_app).get(
        "/private",
        cookies={"scholar_session": raw_session},
    )

    assert response.status_code == 200
    assert response.json() == {"user": user["id"], "username": "alice"}


def test_password_login_creates_revocable_session(monkeypatch):
    import main

    repository = InMemoryRepository()
    repository.create_password_user("Research.Admin", hash_password("correct horse battery staple"))
    monkeypatch.setattr(main, "repository", repository)
    monkeypatch.setattr(app.state, "repository", repository)
    monkeypatch.setenv("COOKIE_SECURE", "false")

    with TestClient(app) as client:
        login = client.post(
            "/api/auth/login",
            json={"username": "research.admin", "password": "correct horse battery staple"},
        )
        assert login.status_code == 200
        assert login.json()["user"]["username"] == "Research.Admin"

        me = client.get("/api/auth/me")
        assert me.json() == {
            "authenticated": True,
            "user": {"id": login.json()["user"]["id"], "username": "Research.Admin"},
        }

        assert client.post("/api/auth/logout").status_code == 200
        assert client.get("/api/auth/me").json()["authenticated"] is False


def test_public_registration_creates_user_and_authenticated_session(monkeypatch):
    import main

    repository = InMemoryRepository()
    monkeypatch.setattr(main, "repository", repository)
    monkeypatch.setattr(app.state, "repository", repository)
    monkeypatch.setenv("COOKIE_SECURE", "false")

    with TestClient(app) as client:
        response = client.post(
            "/api/auth/register",
            json={"username": "new.user", "password": "correct horse battery staple"},
        )

        assert response.status_code == 201
        assert response.json()["user"]["username"] == "new.user"
        assert verify_password(
            "correct horse battery staple",
            repository.get_user_for_login("NEW.USER")["password_hash"],
        )
        assert client.get("/api/auth/me").json()["authenticated"] is True


def test_public_registration_rejects_duplicate_username(monkeypatch):
    import main

    repository = InMemoryRepository()
    repository.create_password_user("Alice", hash_password("correct horse battery staple"))
    monkeypatch.setattr(main, "repository", repository)
    monkeypatch.setattr(app.state, "repository", repository)

    response = TestClient(app).post(
        "/api/auth/register",
        json={"username": "alice", "password": "another secure password"},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "Username is already registered"


def test_public_registration_is_rate_limited_by_ip(monkeypatch):
    import main

    repository = InMemoryRepository()
    for _ in range(10):
        repository.record_registration_attempt("testclient", True)
    monkeypatch.setattr(main, "repository", repository)
    monkeypatch.setattr(app.state, "repository", repository)

    response = TestClient(app).post(
        "/api/auth/register",
        json={"username": "new-user", "password": "correct horse battery staple"},
    )

    assert response.status_code == 429


def test_password_login_rejects_invalid_credentials(monkeypatch):
    import main

    repository = InMemoryRepository()
    repository.create_password_user("alice", hash_password("correct horse battery staple"))
    monkeypatch.setattr(main, "repository", repository)
    monkeypatch.setattr(app.state, "repository", repository)

    response = TestClient(app).post(
        "/api/auth/login",
        json={"username": "alice", "password": "not the right password"},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid username or password"


def test_password_login_rate_limits_repeated_failures(monkeypatch):
    import main

    repository = InMemoryRepository()
    repository.create_password_user("alice", hash_password("correct horse battery staple"))
    monkeypatch.setattr(main, "repository", repository)
    monkeypatch.setattr(app.state, "repository", repository)
    client = TestClient(app)

    for _ in range(5):
        response = client.post(
            "/api/auth/login",
            json={"username": "alice", "password": "incorrect password"},
        )
        assert response.status_code == 401

    response = client.post(
        "/api/auth/login",
        json={"username": "alice", "password": "incorrect password"},
    )
    assert response.status_code == 429


def test_email_magic_link_routes_are_removed():
    client = TestClient(app)

    assert client.post("/api/auth/magic-link", json={"email": "user@example.com"}).status_code == 404
    assert client.get("/api/auth/callback?token=" + "x" * 40).status_code == 404


def test_all_scholar_query_routes_require_authentication():
    client = TestClient(app)
    scholar_id = str(uuid4())

    requests = [
        client.get("/api/search?name=Ada"),
        client.post("/api/profile", json={"author_id": "A1"}),
        client.post("/api/profile/stream", json={"author_id": "A1"}),
        client.get("/api/authors/A1/works"),
        client.get(f"/api/profiles/{scholar_id}/events"),
        client.post("/api/tracking/A1/refresh"),
        client.get("/api/authors/A1/research-graph"),
        client.get("/api/authors/A1/intelligence"),
        client.post(
            "/api/authors/A1/research-graph/refresh",
            json={"force_rebuild": False},
        ),
        client.get(f"/api/research-graph/objects/paper/{scholar_id}"),
        client.get("/api/intelligence/field?author_id=A1"),
        client.post(
            "/api/intelligence/compare",
            json={"author_ids": ["A1", "A2"], "mode": "scholar"},
        ),
        client.post(
            "/api/intelligence/feedback",
            json={
                "target_author_id": "A1",
                "analysis_key": "academic_quality",
                "verdict": "helpful",
            },
        ),
    ]

    assert [response.status_code for response in requests] == [
        401, 401, 401, 401, 401, 401, 401, 401, 401, 401, 401, 401, 401,
    ]


def test_search_rate_limit_returns_friendly_error(monkeypatch):
    import main

    repository = InMemoryRepository()
    user = repository.create_password_user("alice", hash_password("correct horse battery staple"))
    raw_session = generate_token()
    repository.create_user_session(
        user["id"],
        hash_token(raw_session),
        datetime.now(timezone.utc) + timedelta(days=1),
    )
    repository.save_user_api_credential(
        user["id"],
        "openalex",
        encrypt_secret("test-openalex-key"),
        "••••-key",
    )
    monkeypatch.setattr(main, "repository", repository)
    monkeypatch.setattr(app.state, "repository", repository)
    monkeypatch.setattr(main, "SEARCH_RATE_LIMIT_PER_USER", 1)
    monkeypatch.setattr(main, "search_authors", lambda _name, **_kwargs: [])

    client = TestClient(app)
    client.cookies.set("scholar_session", raw_session)
    assert client.get("/api/search?name=Ada").status_code == 200

    response = client.get("/api/search?name=Ada")

    assert response.status_code == 429
    assert response.json()["detail"] == "操作过于频繁，请稍后再试。"


def test_token_hash_is_stable_and_does_not_store_raw_token():
    token = generate_token()

    assert len(token) >= 32
    assert hash_token(token) == hash_token(token)
    assert token not in hash_token(token)
