from concurrent.futures import ThreadPoolExecutor
from threading import Event, Lock

from intelligence_service import ScholarIntelligenceService
from repository import InMemoryRepository


AUTHOR_ID = "https://openalex.org/A-CACHE"


def _ready_repository() -> InMemoryRepository:
    repository = InMemoryRepository()
    repository._research_graph_store = {
        "sync": {
            AUTHOR_ID: {
                "status": "ready",
                "version": 1,
                "updated_at": "2026-07-28T00:00:00+00:00",
                "data_fingerprint": "snapshot-1",
            },
        },
    }
    return repository


def test_analysis_cache_returns_isolated_payloads(monkeypatch):
    repository = _ready_repository()
    service = ScholarIntelligenceService()
    calls = 0

    def build(_repository, author_id, *, limit, candidate_offset):
        nonlocal calls
        calls += 1
        return {
            "author_id": author_id,
            "limit": limit,
            "candidate_offset": candidate_offset,
            "nested": {"value": 1},
        }

    monkeypatch.setattr("intelligence_service.build_scholar_intelligence", build)

    first = service.analyze(repository, AUTHOR_ID, limit=8)
    first["nested"]["value"] = 99
    second = service.analyze(repository, AUTHOR_ID, limit=8)

    assert calls == 1
    assert second["nested"]["value"] == 1
    assert service.cache_info(repository) == {
        "entries": 1,
        "hits": 1,
        "misses": 1,
        "in_flight": 0,
    }


def test_graph_revision_invalidates_analysis_cache(monkeypatch):
    repository = _ready_repository()
    service = ScholarIntelligenceService()
    calls = 0

    def build(_repository, _author_id, *, limit, candidate_offset):
        nonlocal calls
        calls += 1
        return {
            "build": calls,
            "limit": limit,
            "candidate_offset": candidate_offset,
        }

    monkeypatch.setattr("intelligence_service.build_scholar_intelligence", build)

    assert service.analyze(repository, AUTHOR_ID)["build"] == 1
    state = repository._research_graph_store["sync"][AUTHOR_ID]
    state.update(
        version=2,
        updated_at="2026-07-28T00:01:00+00:00",
        data_fingerprint="snapshot-2",
    )
    assert service.analyze(repository, AUTHOR_ID)["build"] == 2


def test_unrelated_graph_revision_does_not_invalidate_analysis_cache(monkeypatch):
    repository = _ready_repository()
    repository._research_graph_store["sync"]["https://openalex.org/A-OTHER"] = {
        "status": "ready",
        "version": 1,
        "updated_at": "2026-07-28T00:00:00+00:00",
        "data_fingerprint": "other-1",
    }
    service = ScholarIntelligenceService()
    calls = 0

    def build(_repository, _author_id, *, limit, candidate_offset):
        nonlocal calls
        calls += 1
        return {
            "build": calls,
            "limit": limit,
            "candidate_offset": candidate_offset,
        }

    monkeypatch.setattr("intelligence_service.build_scholar_intelligence", build)

    assert service.analyze(repository, AUTHOR_ID)["build"] == 1
    repository._research_graph_store["sync"][
        "https://openalex.org/A-OTHER"
    ].update(
        version=2,
        updated_at="2026-07-28T00:01:00+00:00",
        data_fingerprint="other-2",
    )
    assert service.analyze(repository, AUTHOR_ID)["build"] == 1


def test_candidate_pages_use_separate_cache_entries(monkeypatch):
    repository = _ready_repository()
    service = ScholarIntelligenceService()
    calls = 0

    def build(_repository, _author_id, *, limit, candidate_offset):
        nonlocal calls
        calls += 1
        return {
            "build": calls,
            "limit": limit,
            "candidate_offset": candidate_offset,
        }

    monkeypatch.setattr("intelligence_service.build_scholar_intelligence", build)

    first = service.analyze(repository, AUTHOR_ID, limit=20)
    second = service.analyze(
        repository,
        AUTHOR_ID,
        limit=20,
        candidate_offset=20,
    )
    repeated = service.analyze(
        repository,
        AUTHOR_ID,
        limit=20,
        candidate_offset=20,
    )

    assert first["candidate_offset"] == 0
    assert second["candidate_offset"] == 20
    assert repeated == second
    assert calls == 2


def test_discovery_revision_invalidates_analysis_cache(monkeypatch):
    repository = _ready_repository()
    repository._field_discovery_store = {
        "states": {
            AUTHOR_ID: {
                "status": "enriching",
                "version": 1,
                "updated_at": "2026-07-28T00:00:00+00:00",
            },
        },
    }
    service = ScholarIntelligenceService()
    calls = 0

    def build(_repository, _author_id, *, limit, candidate_offset):
        nonlocal calls
        calls += 1
        return {
            "build": calls,
            "limit": limit,
            "candidate_offset": candidate_offset,
        }

    monkeypatch.setattr("intelligence_service.build_scholar_intelligence", build)

    assert service.analyze(repository, AUTHOR_ID)["build"] == 1
    repository._field_discovery_store["states"][AUTHOR_ID].update(
        status="ready",
        version=2,
        updated_at="2026-07-28T00:01:00+00:00",
    )
    assert service.analyze(repository, AUTHOR_ID)["build"] == 2


def test_cache_ttl_and_lru_bound(monkeypatch):
    repository = _ready_repository()
    now = 0.0
    service = ScholarIntelligenceService(
        max_entries=2,
        ttl_seconds=10,
        clock=lambda: now,
    )
    calls = 0

    def build(_repository, author_id, *, limit, candidate_offset):
        nonlocal calls
        calls += 1
        return {
            "author_id": author_id,
            "limit": limit,
            "candidate_offset": candidate_offset,
            "build": calls,
        }

    monkeypatch.setattr("intelligence_service.build_scholar_intelligence", build)

    service.analyze(repository, AUTHOR_ID, limit=1)
    service.analyze(repository, AUTHOR_ID, limit=2)
    service.analyze(repository, AUTHOR_ID, limit=3)
    assert service.cache_info(repository)["entries"] == 2

    now = 11.0
    assert service.analyze(repository, AUTHOR_ID, limit=3)["build"] == 4


def test_concurrent_identical_requests_share_one_build(monkeypatch):
    repository = _ready_repository()
    service = ScholarIntelligenceService()
    started = Event()
    release = Event()
    counter_lock = Lock()
    calls = 0

    def build(_repository, author_id, *, limit, candidate_offset):
        nonlocal calls
        with counter_lock:
            calls += 1
        started.set()
        assert release.wait(timeout=2)
        return {
            "author_id": author_id,
            "limit": limit,
            "candidate_offset": candidate_offset,
        }

    monkeypatch.setattr("intelligence_service.build_scholar_intelligence", build)

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(service.analyze, repository, AUTHOR_ID)
        assert started.wait(timeout=2)
        second = executor.submit(service.analyze, repository, AUTHOR_ID)
        release.set()
        assert first.result(timeout=2) == second.result(timeout=2)

    assert calls == 1
