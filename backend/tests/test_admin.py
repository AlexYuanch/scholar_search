from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from auth import hash_password
from main import app
from repository import InMemoryRepository


PASSWORD = "correct horse battery staple"


def _client_for(monkeypatch, repository: InMemoryRepository, username: str) -> TestClient:
    import main

    monkeypatch.setattr(main, "repository", repository)
    monkeypatch.setattr(app.state, "repository", repository)
    monkeypatch.setenv("COOKIE_SECURE", "false")
    client = TestClient(app)
    login = client.post(
        "/api/auth/login",
        json={"username": username, "password": PASSWORD},
    )
    assert login.status_code == 200
    return client


def test_admin_dashboard_rejects_regular_user(monkeypatch):
    repository = InMemoryRepository()
    repository.create_password_user("member", hash_password(PASSWORD))
    client = _client_for(monkeypatch, repository, "member")

    response = client.get("/api/admin/dashboard?range=7d")

    assert response.status_code == 403


def test_super_admin_can_view_dashboard_and_manage_admins(monkeypatch):
    repository = InMemoryRepository()
    repository.create_password_user(
        "admin",
        hash_password(PASSWORD),
        role="super_admin",
    )
    target = repository.create_password_user("researcher", hash_password(PASSWORD))
    client = _client_for(monkeypatch, repository, "admin")

    dashboard = client.get("/api/admin/dashboard?range=24h")
    users = client.get("/api/admin/users")
    promoted = client.patch(
        f"/api/admin/users/{target['id']}/role",
        json={"role": "admin"},
    )

    assert dashboard.status_code == 200
    assert dashboard.json()["summary"]["total_users"] == 2
    assert users.status_code == 200
    assert promoted.status_code == 200
    assert promoted.json()["role"] == "admin"


def test_delegated_admin_cannot_manage_roles(monkeypatch):
    repository = InMemoryRepository()
    delegated = repository.create_password_user(
        "reviewer",
        hash_password(PASSWORD),
        role="admin",
    )
    target = repository.create_password_user("researcher", hash_password(PASSWORD))
    client = _client_for(monkeypatch, repository, delegated["username"])

    assert client.get("/api/admin/dashboard").status_code == 200
    assert client.get("/api/admin/users").status_code == 403
    assert client.patch(
        f"/api/admin/users/{target['id']}/role",
        json={"role": "admin"},
    ).status_code == 403


def test_super_admin_role_cannot_be_revoked(monkeypatch):
    repository = InMemoryRepository()
    super_admin = repository.create_password_user(
        "admin",
        hash_password(PASSWORD),
        role="super_admin",
    )
    client = _client_for(monkeypatch, repository, "admin")

    response = client.patch(
        f"/api/admin/users/{super_admin['id']}/role",
        json={"role": "user"},
    )

    assert response.status_code == 409


def test_anonymous_visit_uses_hash_without_storing_ip(monkeypatch):
    repository = InMemoryRepository()
    import main

    monkeypatch.setattr(main, "repository", repository)
    monkeypatch.setattr(app.state, "repository", repository)
    monkeypatch.setenv("COOKIE_SECURE", "false")

    response = TestClient(app).post("/api/analytics/visit")

    assert response.status_code == 204
    assert len(repository.analytics_events) == 1
    event = repository.analytics_events[0]
    assert event["event_type"] == "page_view"
    assert len(event["visitor_hash"]) == 64
    assert "request_ip" not in event
    assert "ip" not in event["metadata"]


def test_parallel_public_requests_do_not_create_extra_visitors(monkeypatch):
    repository = InMemoryRepository()
    import main

    monkeypatch.setattr(main, "repository", repository)
    monkeypatch.setattr(app.state, "repository", repository)
    monkeypatch.setenv("COOKIE_SECURE", "false")
    client = TestClient(app)

    assert client.get("/api/auth/me").status_code == 200
    assert repository.analytics_visitors == {}
    assert client.post("/api/analytics/visit").status_code == 204
    assert len(repository.analytics_visitors) == 1


def test_online_window_and_analytics_retention(monkeypatch):
    repository = InMemoryRepository()
    admin = repository.create_password_user(
        "admin",
        hash_password(PASSWORD),
        role="super_admin",
    )
    member = repository.create_password_user("member", hash_password(PASSWORD))
    now = datetime.now(timezone.utc)
    repository.analytics_visitors = {
        "a" * 64: {
            "visitor_hash": "a" * 64,
            "user_id": member["id"],
            "first_seen_at": now,
            "last_seen_at": now,
        },
        "b" * 64: {
            "visitor_hash": "b" * 64,
            "user_id": None,
            "first_seen_at": now,
            "last_seen_at": now - timedelta(minutes=6),
        },
    }
    repository.analytics_events = [
        {
            "event_type": "page_view",
            "visitor_hash": "a" * 64,
            "user_id": member["id"],
            "scholar_id": None,
            "metadata": {},
            "created_at": now - timedelta(days=31),
        }
    ]
    client = _client_for(monkeypatch, repository, admin["username"])

    dashboard = client.get("/api/admin/dashboard").json()
    maintenance = repository.run_maintenance()

    assert dashboard["summary"]["online_authenticated"] >= 1
    assert dashboard["summary"]["online_anonymous"] == 0
    assert maintenance["deleted"] == 1
    assert all(
        event["created_at"] >= now - timedelta(days=30)
        for event in repository.analytics_events
    )
