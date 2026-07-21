from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from auth import AuthUser, require_user
from main import app
from repository import InMemoryRepository


def _state(author_id="A1", name="Ada Lovelace"):
    work = {
        "id": "W1",
        "title": "Analytical Engine",
        "publication_year": 1843,
        "cited_by_count": 10,
        "authorships": [{"author": {"id": author_id, "display_name": name}}],
    }
    return {
        "target_author_id": author_id,
        "target_author_profile": {"id": author_id, "display_name": name, "works_count": 1},
        "deduped_works": [work],
        "works_complete": True,
        "web_payload": {"name": name, "totalPapers": 1, "profileEvidence": []},
        "warnings": [],
        "errors": [],
    }


@pytest.fixture
def authenticated_client():
    app.dependency_overrides[require_user] = lambda: AuthUser(id="test-user", username="tester")
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def test_health_returns_ok():
    response = TestClient(app).get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_profile_returns_latest_payload_without_running_graph(monkeypatch, authenticated_client):
    import main

    repository = InMemoryRepository()
    repository.publish_profile(_state(), query_name="Ada Lovelace")

    def fail_invoke(_state):
        raise AssertionError("graph should not run when a profile exists")

    monkeypatch.setattr(main, "repository", repository)
    monkeypatch.setattr(main.graph, "invoke", fail_invoke)

    response = authenticated_client.post("/api/profile", json={"author_id": "A1"})

    assert response.status_code == 200
    assert response.json()["source"] == "cache"
    assert response.json()["data"]["name"] == "Ada Lovelace"
    assert response.json()["data"]["profileVersion"] == 1


def test_stale_profile_is_returned_and_queued_instead_of_blocking(monkeypatch, authenticated_client):
    import main

    repository = InMemoryRepository()
    repository.publish_profile(_state(), query_name="Ada Lovelace")
    repository.profiles["A1"]["updated_at"] = (
        datetime.now(timezone.utc) - timedelta(days=8)
    ).isoformat()
    monkeypatch.setattr(main, "repository", repository)

    response = authenticated_client.post("/api/profile", json={"author_id": "A1"})

    assert response.status_code == 200
    assert response.json()["refresh_status"] == "queued"
    assert len(repository.jobs) == 1


def test_cold_profile_publishes_valid_workflow_result(monkeypatch, authenticated_client):
    import main

    repository = InMemoryRepository()
    monkeypatch.setattr(main, "repository", repository)
    monkeypatch.setattr(main.graph, "invoke", lambda _input: _state())

    response = authenticated_client.post("/api/profile", json={"author_id": "A1"})

    assert response.status_code == 200
    assert response.json()["source"] == "live"
    assert repository.get_profile("A1")["profile_version"] == 1


def test_profile_stream_refreshes_cached_profile(monkeypatch, authenticated_client):
    import main

    repository = InMemoryRepository()
    repository.publish_profile(_state(), query_name="Ada Lovelace")
    monkeypatch.setattr(main, "repository", repository)

    refreshed = _state(name="Ada Byron")

    class RefreshGraph:
        def stream(self, _state, stream_mode="values"):
            yield refreshed

    monkeypatch.setattr(main, "graph", RefreshGraph())

    response = authenticated_client.post("/api/profile/stream", json={"author_id": "A1"})
    body = response.text

    assert response.status_code == 200
    assert '"type": "cache_hit"' not in body
    assert '"profile_version": 2' in body
    assert '"name": "Ada Byron"' in body


def test_profile_stream_reports_workflow_error(monkeypatch, authenticated_client):
    import main

    class BrokenGraph:
        def stream(self, _state, stream_mode="values"):
            raise RuntimeError("workflow exploded")

    monkeypatch.setattr(main, "repository", InMemoryRepository())
    monkeypatch.setattr(main, "graph", BrokenGraph())

    response = authenticated_client.post("/api/profile/stream", json={"author_id": "A1"})

    assert response.status_code == 200
    assert '"type": "error"' in response.text
    assert "workflow exploded" in response.text
