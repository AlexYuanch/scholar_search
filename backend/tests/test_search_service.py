import threading
import time
from datetime import timedelta

import pytest

import search_service
from openalex import OpenAlexError
from repository import InMemoryRepository, _now


def _payload(author_id="A1"):
    return [{
        "id": author_id,
        "name": "Ada Lovelace",
        "institution": "Analytical Engine Institute",
        "institutions": ["Analytical Engine Institute"],
        "current_institution": "Analytical Engine Institute",
        "historical_institutions": [],
        "works_count": 1,
        "cited_by_count": 10,
        "h_index": 1,
        "orcid": None,
        "merged_count": 1,
        "merged_ids": [author_id],
        "disambiguation": "Independent profile",
        "identity_confidence": "single",
        "identity_evidence": [],
    }]


def test_cold_search_is_saved_and_subsequent_users_reuse_cache():
    repository = InMemoryRepository()
    calls = []

    def builder(_repository, query_text):
        calls.append(query_text)
        return _payload(), True

    first = search_service.search_with_cache(repository, "  Ada   Lovelace  ", builder)
    second = search_service.search_with_cache(repository, "ada lovelace", builder)

    assert first["source"] == "live"
    assert second["source"] == "cache"
    assert first["candidates"] == second["candidates"]
    assert calls == ["Ada Lovelace"]


def test_stale_search_returns_immediately_and_enqueues_worker_refresh():
    repository = InMemoryRepository()
    key, query_text = search_service.normalize_search_query("Ada")
    repository.save_openalex_search_cache(key, query_text, _payload(), 60)
    repository.openalex_search_cache[key]["expires_at"] = _now() - timedelta(seconds=1)

    result = search_service.search_with_cache(
        repository,
        "Ada",
        lambda *_args: pytest.fail("stale requests must not refresh in the web request"),
    )

    assert result["source"] == "stale"
    assert result["candidates"] == _payload()
    assert len(repository.openalex_search_jobs) == 1
    assert next(iter(repository.openalex_search_jobs.values()))["status"] == "pending"


def test_concurrent_cold_search_waits_for_the_single_owner(monkeypatch):
    repository = InMemoryRepository()
    key, query_text = search_service.normalize_search_query("Ada")
    repository.enqueue_openalex_search(key, query_text)
    owner = repository.claim_openalex_search_job(key)
    assert owner is not None
    monkeypatch.setattr(search_service, "SEARCH_COALESCE_WAIT_SECONDS", 1)
    monkeypatch.setattr(search_service, "SEARCH_COALESCE_POLL_SECONDS", 0.01)

    def publish_cache():
        time.sleep(0.03)
        repository.save_openalex_search_cache(key, query_text, _payload(), 60)
        repository.complete_openalex_search_job(owner["id"])

    thread = threading.Thread(target=publish_cache)
    thread.start()
    try:
        result = search_service.search_with_cache(
            repository,
            "Ada",
            lambda *_args: pytest.fail("the follower must not call OpenAlex"),
        )
    finally:
        thread.join()

    assert result["source"] == "coalesced"
    assert len(repository.openalex_search_jobs) == 1


def test_identity_fingerprints_are_reused_across_different_queries():
    repository = InMemoryRepository()
    repository.save_openalex_identity_cache(
        "A1",
        {"sampled_works": 1, "work_ids": ["W1"], "coauthor_ids": [], "topic_ids": []},
        3600,
    )
    authors = [
        {
            "id": "A1",
            "display_name": "Ada",
            "last_known_institutions": [],
            "affiliations": [],
        },
        {
            "id": "A2",
            "display_name": "Ada",
            "last_known_institutions": [],
            "affiliations": [],
        },
    ]
    enriched_ids = []

    def enrich(candidates):
        enriched_ids.extend(candidate["id"] for candidate in candidates)
        return [
            {
                **candidate,
                "identity_fingerprint": {
                    "sampled_works": 1,
                    "work_ids": [f"W-{candidate['id']}"],
                    "coauthor_ids": [],
                    "topic_ids": [],
                },
            }
            for candidate in candidates
        ]

    search_service.build_live_candidate_payload(
        repository,
        "Ada",
        api_key="test-key",
        budget_provider="openalex:user:test",
        search_fn=lambda _query: authors,
        enrich_fn=enrich,
    )
    search_service.build_live_candidate_payload(
        repository,
        "Ada L.",
        api_key="test-key",
        budget_provider="openalex:user:test",
        search_fn=lambda _query: authors,
        enrich_fn=lambda _candidates: pytest.fail("both fingerprints should be cached"),
    )

    assert enriched_ids == ["A2"]


def test_shared_budget_reserve_blocks_only_uncached_searches():
    repository = InMemoryRepository()
    repository.record_upstream_rate_limit("openalex", 1000, 0, 600)

    with pytest.raises(OpenAlexError) as captured:
        search_service.search_with_cache(
            repository,
            "New Scholar",
            lambda *_args: pytest.fail("budget guard must run before OpenAlex"),
        )

    assert captured.value.status_code == 429
    assert int(captured.value.retry_after) > 0

    key, query_text = search_service.normalize_search_query("Cached Scholar")
    repository.save_openalex_search_cache(key, query_text, _payload(), 60)
    cached = search_service.search_with_cache(repository, "Cached Scholar")
    assert cached["source"] == "cache"


def test_budget_outage_still_serves_real_published_local_scholar():
    repository = InMemoryRepository()
    repository.publish_profile({
        "target_author_id": "A1",
        "target_author_profile": {
            "id": "A1",
            "display_name": "Ada Lovelace",
            "merged_author_ids": ["A1", "A1-merged"],
            "works_count": 1,
            "cited_by_count": 10,
            "summary_stats": {"h_index": 1},
            "last_known_institutions": [{"display_name": "Analytical Engine Institute"}],
        },
        "deduped_works": [],
        "web_payload": {
            "name": "Ada Lovelace",
            "institution": "Analytical Engine Institute",
        },
        "warnings": [],
        "errors": [],
    })
    repository.record_upstream_rate_limit("openalex", 1000, 0, 600)

    result = search_service.search_with_cache(
        repository,
        "Ada Lovelace",
        lambda *_args: pytest.fail("local fallback must avoid OpenAlex"),
    )

    assert result["source"] == "local"
    assert result["candidates"][0]["id"] == "A1"
    assert result["candidates"][0]["merged_count"] == 2
    assert {
        "type": "published_profile",
        "merged_count": 2,
    } in result["candidates"][0]["identity_evidence"]
