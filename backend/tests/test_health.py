from datetime import datetime, timedelta, timezone
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient

from auth import AuthUser, require_user
from credentials import encrypt_secret
from main import app
from openalex import IDENTITY_FINGERPRINT_VERSION
from repository import InMemoryRepository


def _configure_openalex(repository, user_id="test-user", api_key="test-openalex-key"):
    repository.save_user_api_credential(
        user_id,
        "openalex",
        encrypt_secret(api_key),
        f"••••{api_key[-4:]}",
    )


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


def test_openalex_settings_require_authentication():
    assert TestClient(app).get("/api/settings/openalex").status_code == 401
    assert TestClient(app).put(
        "/api/settings/openalex",
        json={"api_key": "test-openalex-key"},
    ).status_code == 401


def test_openalex_settings_are_encrypted_and_isolated(
    monkeypatch,
    authenticated_client,
):
    import main
    from credentials import decrypt_secret

    repository = InMemoryRepository()
    monkeypatch.setattr(main, "repository", repository)
    monkeypatch.setattr(
        main,
        "validate_openalex_api_key",
        lambda key, budget_provider: {
            "daily_remaining_usd": 0.75,
            "validated_for": budget_provider,
            "key_length": len(key),
        },
    )
    api_key = "user-owned-openalex-secret"

    saved = authenticated_client.put(
        "/api/settings/openalex",
        json={"api_key": api_key},
    )
    stored = repository.get_user_api_credential("test-user", "openalex")

    assert saved.status_code == 200
    assert api_key not in saved.text
    assert stored["encrypted_secret"] != api_key
    assert api_key not in stored["encrypted_secret"]
    assert decrypt_secret(stored["encrypted_secret"]) == api_key
    assert saved.json()["key_hint"] == "••••cret"

    app.dependency_overrides[require_user] = lambda: AuthUser(
        id="other-user",
        username="other",
    )
    assert authenticated_client.get("/api/settings/openalex").json()["configured"] is False
    assert authenticated_client.delete("/api/settings/openalex").status_code == 200
    assert repository.get_user_api_credential("test-user", "openalex") is not None

    app.dependency_overrides[require_user] = lambda: AuthUser(
        id="test-user",
        username="tester",
    )
    assert authenticated_client.delete("/api/settings/openalex").status_code == 200
    assert repository.get_user_api_credential("test-user", "openalex") is None


def test_search_uses_server_openalex_key_without_user_configuration(
    monkeypatch,
    authenticated_client,
):
    import main

    repository = InMemoryRepository()
    monkeypatch.setattr(main, "repository", repository)
    monkeypatch.setenv("OPENALEX_API_KEY", "server-openalex-key")
    monkeypatch.setenv("COOKIE_SECURE", "false")
    monkeypatch.setattr(
        main,
        "search_authors",
        lambda _name, *, api_key, budget_provider: (
            [{"id": "A1", "display_name": "Ada Lovelace"}]
            if api_key == "server-openalex-key"
            and budget_provider == "openalex:server"
            else []
        ),
    )
    monkeypatch.setattr(
        main,
        "enrich_authors_for_disambiguation",
        lambda candidates, **_kwargs: candidates,
    )

    assert authenticated_client.post("/api/analytics/visit").status_code == 204
    response = authenticated_client.get("/api/search?name=Ada")

    assert response.status_code == 200
    assert [candidate["name"] for candidate in response.json()["candidates"]] == [
        "Ada Lovelace"
    ]
    search_event = next(
        event for event in repository.analytics_events
        if event["event_type"] == "search"
    )
    assert search_event["metadata"] == {"query": "Ada"}


def test_search_reports_missing_platform_data_source_configuration(
    monkeypatch,
    authenticated_client,
):
    import main

    monkeypatch.setattr(main, "repository", InMemoryRepository())
    monkeypatch.delenv("OPENALEX_API_KEY", raising=False)

    response = authenticated_client.get("/api/search?name=Ada")

    assert response.status_code == 503
    assert response.json()["detail"] == "学术数据源尚未配置，请联系管理员。"


def test_server_openalex_key_takes_priority_over_saved_user_key(
    monkeypatch,
    authenticated_client,
):
    import main

    repository = InMemoryRepository()
    _configure_openalex(repository, api_key="user-openalex-key")
    monkeypatch.setattr(main, "repository", repository)
    monkeypatch.setenv("OPENALEX_API_KEY", "server-openalex-key")
    monkeypatch.setattr(
        main,
        "search_authors",
        lambda _name, *, api_key, budget_provider: (
            [{"id": "A1", "display_name": f"{api_key}:{budget_provider}"}]
        ),
    )
    monkeypatch.setattr(
        main,
        "enrich_authors_for_disambiguation",
        lambda candidates, **_kwargs: candidates,
    )

    response = authenticated_client.get("/api/search?name=Ada")

    assert response.status_code == 200
    assert response.json()["candidates"][0]["name"] == (
        "server-openalex-key:openalex:server"
    )


def test_production_rejects_api_key_over_public_http(
    monkeypatch,
    authenticated_client,
):
    import main

    repository = InMemoryRepository()
    monkeypatch.setattr(main, "repository", repository)
    monkeypatch.setenv("APP_ENV", "production")

    response = authenticated_client.put(
        "/api/settings/openalex",
        json={"api_key": "test-openalex-key"},
        headers={"host": "203.0.113.10"},
    )

    assert response.status_code == 426
    assert repository.get_user_api_credential("test-user", "openalex") is None


def test_search_exposes_identity_confirmation_evidence(monkeypatch, authenticated_client):
    import main

    repository = InMemoryRepository()
    _configure_openalex(repository)
    monkeypatch.setattr(main, "repository", repository)
    author = {
        "id": "A1",
        "display_name": "Ada Lovelace",
        "orcid": "https://orcid.org/0000-0000-0000-0001",
        "works_count": 2,
        "cited_by_count": 10,
        "summary_stats": {"h_index": 2},
        "last_known_institutions": [{"display_name": "Current Institute"}],
        "affiliations": [
            {"institution": {"display_name": "Current Institute"}, "years": [2024, 2025]},
            {"institution": {"display_name": "Previous Institute"}, "years": [2020]},
        ],
        "identity_fingerprint": {
            "version": IDENTITY_FINGERPRINT_VERSION,
            "sampled_works": 2,
            "coauthor_ids": ["C1"],
            "topic_ids": ["T1"],
            "affiliations": [{
                "name": "Current Institute",
                "years": [2024, 2025],
                "work_count": 2,
            }],
        },
    }
    monkeypatch.setattr(main, "search_authors", lambda _name, **_kwargs: [author])
    monkeypatch.setattr(
        main,
        "enrich_authors_for_disambiguation",
        lambda candidates, **_kwargs: candidates,
    )

    response = authenticated_client.get("/api/search?name=Ada")
    candidate = response.json()["candidates"][0]

    assert response.status_code == 200
    assert response.json()["source"] == "live"
    assert candidate["identity_confidence"] == "single"
    assert candidate["primary_institution"] == "Current Institute"
    assert candidate["other_institutions"] == ["Previous Institute"]
    assert candidate["historical_affiliations"] == [{
        "name": "Previous Institute",
        "years": [2020],
        "work_count": 0,
    }]
    assert candidate["orcid"].endswith("0001")
    assert {item["type"] for item in candidate["identity_evidence"]} == {
        "orcid",
        "primary_institution",
        "independent_profile",
    }

    cached_response = authenticated_client.get("/api/search?name=ada")
    assert cached_response.status_code == 200
    assert cached_response.json()["source"] == "cache"


def test_search_maps_openalex_rate_limit_to_retryable_response(monkeypatch, authenticated_client):
    import main
    from openalex import OpenAlexError

    repository = InMemoryRepository()
    _configure_openalex(repository)
    monkeypatch.setattr(main, "repository", repository)

    def rate_limited(_name, **_kwargs):
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

    repository = InMemoryRepository()
    _configure_openalex(repository)
    monkeypatch.setattr(main, "repository", repository)

    def unavailable(_name, **_kwargs):
        raise OpenAlexError("secret upstream URL", status_code=503)

    monkeypatch.setattr(main, "search_authors", unavailable)

    response = authenticated_client.get("/api/search?name=Yunfan%20Gao")

    assert response.status_code == 502
    assert response.json()["detail"] == "学术数据源暂时不可用，请稍后重试。"
    assert "secret upstream URL" not in response.text


def test_profile_returns_latest_payload_without_running_graph(monkeypatch, authenticated_client):
    import main

    repository = InMemoryRepository()
    _configure_openalex(repository)
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
    _configure_openalex(repository)
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
    _configure_openalex(repository)
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
    _configure_openalex(repository)
    monkeypatch.setattr(main, "repository", repository)
    monkeypatch.setattr(main.graph, "invoke", lambda _input: _state())

    response = authenticated_client.post("/api/profile", json={"author_id": "A1"})

    assert response.status_code == 200
    assert response.json()["source"] == "live"
    assert repository.get_profile("A1")["profile_version"] == 1


def test_cold_profile_job_returns_immediately_and_appears_in_history(
    monkeypatch,
    authenticated_client,
):
    import main

    repository = InMemoryRepository()
    monkeypatch.setattr(main, "repository", repository)
    monkeypatch.setenv("OPENALEX_API_KEY", "server-openalex-key")

    response = authenticated_client.post(
        "/api/profile/jobs",
        json={
            "author_id": "A1",
            "author_ids": ["A1", "A2"],
            "query_name": "Ada Lovelace",
        },
    )
    history = authenticated_client.get("/api/history").json()["items"]

    assert response.status_code == 200
    assert response.json()["status"] == "queued"
    assert history[0]["name"] == "Ada Lovelace"
    assert history[0]["refresh_status"] == "queued"


def test_profile_stream_returns_cached_profile_without_running_workflow(
    monkeypatch, authenticated_client
):
    import main

    repository = InMemoryRepository()
    _configure_openalex(repository)
    repository.publish_profile(_state(), query_name="Ada Lovelace")
    monkeypatch.setattr(main, "repository", repository)

    class ExplodingGraph:
        def stream(self, _state, stream_mode="values"):
            raise AssertionError("cached profile must not run the workflow")

    monkeypatch.setattr(main, "graph", ExplodingGraph())

    response = authenticated_client.post("/api/profile/stream", json={"author_id": "A1"})
    body = response.text

    assert response.status_code == 200
    assert '"stages": ["verify_identity", "aggregate_outputs", "analyze_trajectory", "verify_evidence"]' in body
    assert '"source": "cache"' in body
    assert '"profile_version": 1' in body
    assert '"name": "Ada Lovelace"' in body
    assert repository.get_profile("A1")["profile_version"] == 1


def test_profile_stream_returns_cached_profile_without_any_openalex_key(
    monkeypatch,
    authenticated_client,
):
    import main

    repository = InMemoryRepository()
    repository.publish_profile(_state(), query_name="Ada Lovelace")
    monkeypatch.setattr(main, "repository", repository)
    monkeypatch.delenv("OPENALEX_API_KEY", raising=False)

    response = authenticated_client.post("/api/profile/stream", json={"author_id": "A1"})

    assert response.status_code == 200
    assert '"source": "cache"' in response.text
    assert '"name": "Ada Lovelace"' in response.text


def test_mark_favorite_seen_clears_tracking_updates(monkeypatch, authenticated_client):
    import main

    repository = InMemoryRepository()
    _configure_openalex(repository)
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
    _configure_openalex(repository)
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
    _configure_openalex(repository)
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


def test_profile_refresh_requires_authentication():
    response = TestClient(app).post("/api/authors/A1/profile/refresh")

    assert response.status_code == 401


def test_profile_refresh_requires_existing_profile(monkeypatch, authenticated_client):
    import main

    repository = InMemoryRepository()
    _configure_openalex(repository)
    monkeypatch.setattr(main, "repository", repository)

    response = authenticated_client.post("/api/authors/A1/profile/refresh")

    assert response.status_code == 404
    assert repository.jobs == {}


def test_profile_refresh_queues_complete_workflow_and_deduplicates(
    monkeypatch,
    authenticated_client,
):
    import main

    author_id = "https://openalex.org/A1"
    repository = InMemoryRepository()
    _configure_openalex(repository)
    saved = repository.publish_profile(
        _state(author_id=author_id),
        query_name="Ada Lovelace",
    )
    monkeypatch.setattr(main, "repository", repository)
    encoded_author_id = quote(author_id, safe="")

    first = authenticated_client.post(
        f"/api/authors/{encoded_author_id}/profile/refresh",
    )
    second = authenticated_client.post(
        f"/api/authors/{encoded_author_id}/profile/refresh",
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json() == {
        "status": "queued",
        "job_id": second.json()["job_id"],
        "profile_version": saved["profile_version"],
    }
    assert len(repository.jobs) == 1
    assert next(iter(repository.jobs.values()))["reason"] == "manual_profile"


def test_profile_status_events_emit_same_version_task_changes():
    import main

    ready = {"version": 3, "status": "ready", "updated_at": "2026-07-27T10:00:00Z"}
    queued = {"version": 3, "status": "queued", "updated_at": "2026-07-27T10:01:00Z"}
    updating = {"version": 3, "status": "updating", "updated_at": "2026-07-27T10:02:00Z"}

    assert main._should_emit_profile_status(ready, 3, None) is False
    assert main._should_emit_profile_status(queued, 3, main._profile_status_event_key(ready)) is True
    assert main._should_emit_profile_status(
        updating,
        3,
        main._profile_status_event_key(queued),
    ) is True
    assert main._should_emit_profile_status(
        updating,
        3,
        main._profile_status_event_key(updating),
    ) is False


def test_profile_stream_reports_workflow_error(monkeypatch, authenticated_client):
    import main

    class BrokenGraph:
        def stream(self, _state, stream_mode="values"):
            raise RuntimeError("workflow exploded")

    repository = InMemoryRepository()
    _configure_openalex(repository)
    monkeypatch.setattr(main, "repository", repository)
    monkeypatch.setattr(main, "graph", BrokenGraph())

    response = authenticated_client.post("/api/profile/stream", json={"author_id": "A1"})

    assert response.status_code == 200
    assert '"type": "error"' in response.text
    assert "workflow exploded" in response.text
