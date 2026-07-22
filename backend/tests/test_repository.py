from datetime import datetime, timedelta, timezone

import pytest

from repository import APIQuotaExceeded, InMemoryRepository, _normalize_database_url


def _workflow_state(work_count=60):
    works = [
        {
            "id": f"https://openalex.org/W{i}",
            "doi": f"https://doi.org/10.1/{i}",
            "title": f"Paper {i}",
            "publication_year": 2020 + (i % 5),
            "cited_by_count": i,
            "authorships": [
                {
                    "author_position": "first",
                    "author": {"id": "https://openalex.org/A1", "display_name": "Ada"},
                    "institutions": [],
                }
            ],
        }
        for i in range(work_count)
    ]
    return {
        "target_author_id": "https://openalex.org/A1",
        "target_author_profile": {
            "id": "https://openalex.org/A1",
            "display_name": "Ada",
            "display_name_alternatives": ["Ada Lovelace"],
            "works_count": work_count,
            "cited_by_count": 100,
            "summary_stats": {"h_index": 5},
            "last_known_institutions": [],
        },
        "deduped_works": works,
        "web_payload": {"name": "Ada", "totalPapers": work_count, "totalCitations": 100},
        "warnings": [],
        "errors": [],
        "works_complete": True,
    }


def test_publish_profile_keeps_latest_payload_and_all_works():
    repository = InMemoryRepository()

    saved = repository.publish_profile(_workflow_state(), query_name="Ada")
    cached = repository.get_profile("https://openalex.org/A1")
    page = repository.list_works("https://openalex.org/A1", limit=50, offset=0, sort="citations")

    assert saved["profile_version"] == 1
    assert saved["data_fingerprint"]
    assert cached["payload"]["totalPapers"] == 60
    assert len(page["items"]) == 50
    assert page["total"] == 60
    assert page["items"][0]["citations"] == 59


def test_refresh_queue_deduplicates_active_jobs_and_claims_once():
    repository = InMemoryRepository()
    repository.publish_profile(_workflow_state(2), query_name="Ada")

    first = repository.enqueue_refresh("https://openalex.org/A1", reason="favorite")
    second = repository.enqueue_refresh("https://openalex.org/A1", reason="recent_access")
    claimed = repository.claim_refresh_job()

    assert first == second
    assert claimed["id"] == first
    assert repository.claim_refresh_job() is None


def test_history_and_favorites_are_isolated_by_user():
    repository = InMemoryRepository()
    repository.publish_profile(_workflow_state(2), query_name="Ada")

    repository.record_history("user-1", "https://openalex.org/A1", "Ada")
    repository.add_favorite("user-1", "https://openalex.org/A1")

    assert len(repository.list_history("user-1", limit=20)) == 1
    assert repository.list_history("user-2", limit=20) == []
    assert len(repository.list_favorites("user-1")) == 1
    assert repository.list_favorites("user-2") == []


def test_favorite_reports_profile_changes_until_user_marks_them_seen():
    repository = InMemoryRepository()
    repository.publish_profile(_workflow_state(2), query_name="Ada")
    repository.add_favorite("user-1", "https://openalex.org/A1")

    initial = repository.list_favorites("user-1")[0]
    assert initial["has_updates"] is False
    assert initial["new_papers"] == 0
    assert initial["new_citations"] == 0

    updated_state = _workflow_state(3)
    updated_state["web_payload"]["totalCitations"] = 130
    saved = repository.publish_profile(updated_state, query_name="Ada")

    updated = repository.list_favorites("user-1")[0]
    assert updated["has_updates"] is True
    assert updated["new_papers"] == 1
    assert updated["new_citations"] == 30

    repository.mark_favorite_seen(
        "user-1",
        "https://openalex.org/A1",
        saved["profile_version"],
    )

    seen = repository.list_favorites("user-1")[0]
    assert seen["has_updates"] is False
    assert seen["new_papers"] == 0
    assert seen["new_citations"] == 0


def test_password_reset_revokes_existing_sessions():
    repository = InMemoryRepository()
    user = repository.create_password_user("alice", "old-password-hash")
    repository.create_user_session(
        user["id"],
        "session-hash",
        datetime.now(timezone.utc) + timedelta(days=1),
    )

    assert repository.set_password("ALICE", "new-password-hash")
    assert repository.get_user_by_session("session-hash") is None


def test_api_quota_limits_each_user_within_time_window():
    repository = InMemoryRepository()

    repository.consume_api_quota("profile", "user-1", "192.0.2.1", 2, 10, 600)
    repository.consume_api_quota("profile", "user-1", "192.0.2.1", 2, 10, 600)

    with pytest.raises(APIQuotaExceeded):
        repository.consume_api_quota("profile", "user-1", "192.0.2.1", 2, 10, 600)

    repository.consume_api_quota("profile", "user-2", "192.0.2.1", 2, 10, 600)


def test_standard_postgres_url_uses_psycopg_driver():
    assert _normalize_database_url("postgres://user:pass@host/db") == (
        "postgresql+psycopg://user:pass@host/db"
    )
    assert _normalize_database_url("postgresql://user:pass@host/db") == (
        "postgresql+psycopg://user:pass@host/db"
    )
    assert _normalize_database_url("postgresql+psycopg://user:pass@host/db") == (
        "postgresql+psycopg://user:pass@host/db"
    )
