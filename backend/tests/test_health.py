from datetime import datetime, timedelta, timezone
from urllib.parse import quote

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


def test_search_exposes_identity_confirmation_evidence(monkeypatch, authenticated_client):
    import main

    monkeypatch.setattr(main, "repository", InMemoryRepository())
    author = {
        "id": "A1",
        "display_name": "Ada Lovelace",
        "orcid": "https://orcid.org/0000-0000-0000-0001",
        "works_count": 2,
        "cited_by_count": 10,
        "summary_stats": {"h_index": 2},
        "last_known_institutions": [{"display_name": "Current Institute"}],
        "affiliations": [
            {"institution": {"display_name": "Current Institute"}, "years": [2025]},
            {"institution": {"display_name": "Previous Institute"}, "years": [2020]},
        ],
        "identity_fingerprint": {
            "sampled_works": 2,
            "coauthor_ids": ["C1"],
            "topic_ids": ["T1"],
        },
    }
    monkeypatch.setattr(main, "search_authors", lambda _name: [author])
    monkeypatch.setattr(main, "enrich_authors_for_disambiguation", lambda candidates: candidates)

    response = authenticated_client.get("/api/search?name=Ada")
    candidate = response.json()["candidates"][0]

    assert response.status_code == 200
    assert candidate["identity_confidence"] == "single"
    assert candidate["current_institution"] == "Current Institute"
    assert candidate["historical_institutions"] == ["Previous Institute"]
    assert candidate["orcid"].endswith("0001")
    assert {item["type"] for item in candidate["identity_evidence"]} == {
        "orcid",
        "current_institution",
        "independent_profile",
    }


def test_search_maps_openalex_rate_limit_to_retryable_response(monkeypatch, authenticated_client):
    import main
    from openalex import OpenAlexError

    monkeypatch.setattr(main, "repository", InMemoryRepository())

    def rate_limited(_name):
        raise OpenAlexError("upstream rejected request", status_code=429, retry_after="17")

    monkeypatch.setattr(main, "search_authors", rate_limited)

    response = authenticated_client.get("/api/search?name=Yunfan%20Gao")

    assert response.status_code == 429
    assert response.headers["Retry-After"] == "17"
    assert response.json()["detail"] == "OpenAlex 额度已用完，17 秒后恢复。"


def test_search_maps_other_openalex_failures_without_leaking_details(
    monkeypatch, authenticated_client
):
    import main
    from openalex import OpenAlexError

    monkeypatch.setattr(main, "repository", InMemoryRepository())

    def unavailable(_name):
        raise OpenAlexError("secret upstream URL", status_code=503)

    monkeypatch.setattr(main, "search_authors", unavailable)

    response = authenticated_client.get("/api/search?name=Yunfan%20Gao")

    assert response.status_code == 502
    assert response.json()["detail"] == "学术数据源暂时不可用，请稍后重试。"
    assert "secret upstream URL" not in response.text


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


def test_author_works_filters_timeline_topic_and_year(monkeypatch, authenticated_client):
    import main

    repository = InMemoryRepository()
    state = _state()
    state["deduped_works"] = [
        {
            "id": "W1",
            "title": "Knowledge Graph Construction",
            "publication_year": 2025,
            "cited_by_count": 10,
            "authorships": [{"author": {"id": "A1", "display_name": "Ada Lovelace"}}],
        },
        {
            "id": "W2",
            "title": "Unrelated Paper",
            "publication_year": 2025,
            "cited_by_count": 5,
            "authorships": [{"author": {"id": "A1", "display_name": "Ada Lovelace"}}],
        },
        {
            "id": "W3",
            "title": "Earlier Knowledge Graph Study",
            "publication_year": 2024,
            "cited_by_count": 7,
            "authorships": [{"author": {"id": "A1", "display_name": "Ada Lovelace"}}],
        },
    ]
    state["topic_clusters"] = [{
        "topic": "Knowledge graph",
        "paper_indices": [0, 2],
    }]
    repository.publish_profile(state, query_name="Ada Lovelace")
    monkeypatch.setattr(main, "repository", repository)

    response = authenticated_client.get(
        "/api/authors/A1/works?year=2025&topic=Knowledge%20graph"
    )

    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert [item["id"] for item in response.json()["items"]] == ["W1"]
    assert response.json()["items"][0]["topics"] == ["Knowledge graph"]


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
    assert '"stages": ["verify_identity", "aggregate_outputs", "analyze_trajectory", "verify_evidence"]' in body
    assert '"核验身份"' in body
    assert '"node": "fetch_profile"' not in body
    assert '"profile_version": 2' in body
    assert '"name": "Ada Byron"' in body


def test_mark_favorite_seen_clears_tracking_updates(monkeypatch, authenticated_client):
    import main

    repository = InMemoryRepository()
    repository.publish_profile(_state(), query_name="Ada Lovelace")
    repository.add_favorite("test-user", "A1")
    updated = _state()
    updated["web_payload"]["totalPapers"] = 2
    saved = repository.publish_profile(updated, query_name="Ada Lovelace")
    assert repository.list_favorites("test-user")[0]["has_updates"] is True
    monkeypatch.setattr(main, "repository", repository)

    response = authenticated_client.post("/api/favorites/seen", json={
        "author_id": "A1",
        "profile_version": saved["profile_version"],
    })

    assert response.status_code == 200
    assert repository.list_favorites("test-user")[0]["has_updates"] is False


def test_tracking_routes_add_list_and_remove_for_current_user(monkeypatch, authenticated_client):
    import main

    repository = InMemoryRepository()
    repository.publish_profile(_state(), query_name="Ada Lovelace")
    monkeypatch.setattr(main, "repository", repository)

    added = authenticated_client.post("/api/tracking", json={"author_id": "A1"})
    listed = authenticated_client.get("/api/tracking")
    removed = authenticated_client.delete("/api/tracking/A1")

    assert added.status_code == 200
    assert [item["author_id"] for item in listed.json()["items"]] == ["A1"]
    assert removed.status_code == 200
    assert repository.list_favorites("test-user") == []


def test_tracking_refresh_requires_existing_tracking(monkeypatch, authenticated_client):
    import main

    repository = InMemoryRepository()
    repository.publish_profile(_state(), query_name="Ada Lovelace")
    repository.add_favorite("another-user", "A1")
    monkeypatch.setattr(main, "repository", repository)

    response = authenticated_client.post("/api/tracking/A1/refresh")

    assert response.status_code == 404
    assert repository.jobs == {}
    assert repository.is_tracking("another-user", "A1") is True
    assert repository.is_tracking("test-user", "A1") is False


def test_tracking_refresh_requires_authentication():
    response = TestClient(app).post("/api/tracking/A1/refresh")

    assert response.status_code == 401


def test_tracking_refresh_deduplicates_active_jobs(monkeypatch, authenticated_client):
    import main

    author_id = "https://openalex.org/A1"
    repository = InMemoryRepository()
    repository.publish_profile(_state(author_id=author_id), query_name="Ada Lovelace")
    repository.add_favorite("test-user", author_id)
    monkeypatch.setattr(main, "repository", repository)
    encoded_author_id = quote(author_id, safe="")

    first = authenticated_client.post(f"/api/tracking/{encoded_author_id}/refresh")
    second = authenticated_client.post(f"/api/tracking/{encoded_author_id}/refresh")

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["job_id"] == second.json()["job_id"]
    assert first.json()["status"] == "queued"
    assert len(repository.jobs) == 1


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
