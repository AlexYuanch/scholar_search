from copy import deepcopy
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

from fastapi.testclient import TestClient

from auth import generate_token, hash_password, hash_token
from credentials import encrypt_secret
from main import app
from repository import InMemoryRepository
from research_graph import (
    build_research_graph_batch,
    deduplicate_graph_works,
    reconstruct_openalex_abstract,
    understand_abstract,
)
from research_graph_repository import (
    apply_research_graph_batch,
    enqueue_research_graph_refresh,
    get_research_graph,
    research_graph_needs_refresh,
)
from worker import process_one_graph_job


AUTHOR_ID = "https://openalex.org/A-DYNAMIC"
COAUTHOR_ID = "https://openalex.org/A-COLLABORATOR"


def _inverted(text: str) -> dict:
    result = {}
    for index, word in enumerate(text.split()):
        result.setdefault(word, []).append(index)
    return result


def _author() -> dict:
    return {
        "id": AUTHOR_ID,
        "display_name": "Dynamic Scholar",
        "works_count": 2,
        "cited_by_count": 20,
        "summary_stats": {"h_index": 2},
        "affiliations": [{
            "institution": {
                "id": "https://openalex.org/I-DYNAMIC",
                "display_name": "Graph University",
                "country_code": "CN",
            },
            "years": [2021, 2022, 2023],
        }],
        "last_known_institutions": [{
            "id": "https://openalex.org/I-DYNAMIC",
            "display_name": "Graph University",
            "country_code": "CN",
        }],
    }


def _work(
    source_id: str,
    doi: str,
    year: int,
    *,
    referenced_works=None,
    abstract=True,
) -> dict:
    abstract_text = (
        "We address reliable research graph updates. "
        "We propose an incremental graph method. "
        "Results show that duplicate relations are removed."
    )
    return {
        "id": source_id,
        "doi": doi,
        "title": f"Research graph paper {year}",
        "publication_year": year,
        "publication_date": f"{year}-05-10",
        "updated_date": f"{year}-06-01T00:00:00Z",
        "cited_by_count": year - 2020,
        "abstract_inverted_index": _inverted(abstract_text) if abstract else None,
        "referenced_works": referenced_works or [],
        "authorships": [
            {
                "author_position": "first",
                "author": {"id": AUTHOR_ID, "display_name": "Dynamic Scholar"},
                "institutions": [{
                    "id": "https://openalex.org/I-DYNAMIC",
                    "display_name": "Graph University",
                }],
            },
            {
                "author_position": "last",
                "author": {
                    "id": COAUTHOR_ID,
                    "display_name": "Graph Collaborator",
                },
                "institutions": [],
            },
        ],
        "primary_topic": {
            "id": "https://openalex.org/T-DYNAMIC",
            "display_name": "Research graph",
            "score": 0.9,
        },
        "topics": [{
            "id": "https://openalex.org/T-DYNAMIC",
            "display_name": "Research graph",
            "score": 0.9,
        }],
        "primary_location": {"source": {"display_name": "Graph Journal"}},
        "type": "article",
        "language": "en",
    }


def test_openalex_abstract_reconstruction_and_absence_are_evidence_bounded():
    text = "We propose a graph method."

    assert reconstruct_openalex_abstract(_inverted(text)) == text
    assert reconstruct_openalex_abstract(None) is None

    present = understand_abstract(text, [])
    absent = understand_abstract(None, [])

    assert present["based_on_abstract"] is True
    assert present["core_method"] == text
    assert present["abstract_evidence"] == [{"field": "problem", "text": text}]
    assert absent == {
        "problem": None,
        "core_method": None,
        "main_contribution": None,
        "topic_relationship": None,
        "abstract_evidence": [],
        "based_on_abstract": False,
        "analyzer_version": "abstract-extractive-v1",
        "source": "openalex_abstract",
        "confidence": 0.0,
    }


def test_stable_doi_deduplicates_openalex_records():
    first = _work("https://openalex.org/W-ONE", "https://doi.org/10.1/DUP", 2022)
    duplicate = _work("https://openalex.org/W-TWO", "doi:10.1/dup", 2022)
    duplicate["title"] = "Richer duplicate title"

    deduplicated = deduplicate_graph_works([first, duplicate])

    assert len(deduplicated) == 1
    assert deduplicated[0]["doi"].lower().endswith("10.1/dup")
    assert set(deduplicated[0]["_openalex_ids"]) == {
        "https://openalex.org/W-ONE",
        "https://openalex.org/W-TWO",
    }
    batch = build_research_graph_batch(_author(), [first, duplicate])
    assert set(batch["works"][0]["external_openalex_ids"]) == {
        "https://openalex.org/W-ONE",
        "https://openalex.org/W-TWO",
    }


def test_stable_identifier_bridge_merges_previously_separate_record_groups():
    openalex_only = _work(
        "https://openalex.org/W-BRIDGE-ONE",
        "",
        2021,
    )
    doi_group = _work(
        "https://openalex.org/W-BRIDGE-TWO",
        "10.1000/bridge",
        2022,
    )
    bridge = _work(
        "https://openalex.org/W-BRIDGE-ONE",
        "10.1000/bridge",
        2023,
    )

    deduplicated = deduplicate_graph_works([openalex_only, doi_group, bridge])

    assert len(deduplicated) == 1
    assert set(deduplicated[0]["_openalex_ids"]) == {
        "https://openalex.org/W-BRIDGE-ONE",
        "https://openalex.org/W-BRIDGE-TWO",
    }
    assert deduplicated[0]["_normalized_dois"] == ["10.1000/bridge"]


def test_merged_openalex_author_ids_are_normalized_to_the_primary_scholar():
    merged_author_id = "https://openalex.org/A-DYNAMIC-MERGED"
    merged_work = _work(
        "https://openalex.org/W-MERGED-AUTHOR",
        "10.1000/merged-author",
        2023,
    )
    merged_work["authorships"][0]["author"] = {
        "id": merged_author_id,
        "display_name": "Historical Dynamic Scholar",
    }

    batch = build_research_graph_batch(
        _author(),
        [merged_work],
        target_author_ids=[AUTHOR_ID, merged_author_id],
    )

    normalized_authorship = batch["works"][0]["authorships"][0]
    assert normalized_authorship["author"]["id"] == AUTHOR_ID
    assert normalized_authorship["source_author_id"] == merged_author_id
    assert [item["author"]["id"] for item in batch["collaborations"]] == [
        COAUTHOR_ID
    ]


def test_incremental_graph_upsert_keeps_relationships_unique_and_sorted():
    repository = InMemoryRepository()
    first_work = _work(
        "https://openalex.org/W-DYNAMIC-1",
        "10.1000/dynamic-1",
        2022,
        referenced_works=["https://openalex.org/W-EXTERNAL"],
    )
    first_batch = build_research_graph_batch(_author(), [first_work])

    apply_research_graph_batch(
        repository,
        first_batch,
        force_rebuild=False,
        warnings=[],
    )
    apply_research_graph_batch(
        repository,
        deepcopy(first_batch),
        force_rebuild=False,
        warnings=[],
    )

    second_work = _work(
        "https://openalex.org/W-DYNAMIC-2",
        "10.1000/dynamic-2",
        2024,
        referenced_works=["https://openalex.org/W-DYNAMIC-1"],
        abstract=False,
    )
    second_batch = build_research_graph_batch(_author(), [second_work])
    apply_research_graph_batch(
        repository,
        second_batch,
        force_rebuild=False,
        warnings=[],
    )
    graph = get_research_graph(repository, AUTHOR_ID)

    assert len(graph["papers"]) == 2
    assert graph["topic_evolution"][0]["works_count"] == 2
    assert graph["topic_evolution"][0]["first_year"] == 2022
    assert graph["topic_evolution"][0]["last_year"] == 2024
    assert len(graph["collaborations"]) == 1
    assert graph["collaborations"][0]["works_count"] == 2
    assert graph["affiliations"][0]["name"] == "Graph University"
    assert graph["affiliations"][0]["is_current"] is True
    assert any(
        citation["cited"]["title"] == "Research graph paper 2022"
        for citation in graph["citations"]
    )
    assert all(citation["cited"]["id"] for citation in graph["citations"])
    assert not any(
        citation["cited"]["source_id"] == "https://openalex.org/W-EXTERNAL"
        for citation in graph["citations"]
    )
    timeline_years = [
        item["event_year"]
        for item in graph["timeline"]
        if item.get("event_year")
    ]
    assert timeline_years == sorted(timeline_years, reverse=True)
    missing_abstract_paper = next(
        paper for paper in graph["papers"] if paper["year"] == 2024
    )
    assert missing_abstract_paper["has_abstract"] is False
    assert missing_abstract_paper["insight"]["based_on_abstract"] is False
    assert missing_abstract_paper["insight"]["problem"] is None


def test_forced_rebuild_replaces_only_the_target_scholar_graph_relations():
    repository = InMemoryRepository()
    first_work = _work(
        "https://openalex.org/W-REBUILD-OLD",
        "10.1000/rebuild-old",
        2022,
    )
    second_work = _work(
        "https://openalex.org/W-REBUILD-CURRENT",
        "10.1000/rebuild-current",
        2024,
    )
    apply_research_graph_batch(
        repository,
        build_research_graph_batch(_author(), [first_work, second_work]),
        force_rebuild=False,
        warnings=[],
    )

    apply_research_graph_batch(
        repository,
        build_research_graph_batch(_author(), [second_work]),
        force_rebuild=True,
        warnings=[],
    )
    graph = get_research_graph(repository, AUTHOR_ID)

    assert [paper["source_id"] for paper in graph["papers"]] == [
        "https://openalex.org/W-REBUILD-CURRENT"
    ]
    assert graph["topic_evolution"][0]["works_count"] == 1
    assert graph["collaborations"][0]["works_count"] == 1
    assert {
        event["title"]
        for event in graph["timeline"]
        if event["event_type"] == "paper_published"
    } == {"Research graph paper 2024"}


def test_failed_background_batch_preserves_last_successful_graph(monkeypatch):
    repository = InMemoryRepository()
    batch = build_research_graph_batch(
        _author(),
        [_work("https://openalex.org/W-STABLE", "10.1000/stable", 2023)],
    )
    apply_research_graph_batch(
        repository,
        batch,
        force_rebuild=False,
        warnings=[],
    )
    before = get_research_graph(repository, AUTHOR_ID)
    job_id = enqueue_research_graph_refresh(
        repository,
        AUTHOR_ID,
        requested_by_user_id="user-a",
        reason="test_failure",
    )
    monkeypatch.setenv("OPENALEX_API_KEY", "server-test-key")

    def fail_sync(*_args, **_kwargs):
        raise RuntimeError("upstream unavailable")

    assert process_one_graph_job(repository, fail_sync) is False

    after = get_research_graph(repository, AUTHOR_ID)
    assert after["papers"] == before["papers"]
    assert after["timeline"] == before["timeline"]
    assert repository._research_graph_store["jobs"][job_id]["status"] == "pending"
    assert after["status"]["last_success_at"] == before["status"]["last_success_at"]
    assert "upstream unavailable" not in after["status"]["last_error"]
    assert "已有成功数据" in after["status"]["last_error"]


def test_graph_job_deduplicates_force_escalation_and_stops_after_three_attempts(
    monkeypatch,
):
    repository = InMemoryRepository()
    first_id = enqueue_research_graph_refresh(
        repository,
        AUTHOR_ID,
        requested_by_user_id="user-a",
        reason="incremental",
        force_rebuild=False,
    )
    second_id = enqueue_research_graph_refresh(
        repository,
        AUTHOR_ID,
        requested_by_user_id="user-a",
        reason="rebuild",
        force_rebuild=True,
    )
    monkeypatch.setenv("OPENALEX_API_KEY", "server-test-key")

    def fail_sync(*_args, **_kwargs):
        raise RuntimeError("private upstream detail")

    assert first_id == second_id
    assert repository._research_graph_store["jobs"][first_id]["force_rebuild"]
    for attempt in range(1, 4):
        assert process_one_graph_job(repository, fail_sync) is False
        job = repository._research_graph_store["jobs"][first_id]
        assert job["attempts"] == attempt
        assert job["status"] == ("pending" if attempt < 3 else "failed")
    assert "private upstream detail" not in job["last_error"]
    assert process_one_graph_job(repository, fail_sync) is False


def test_graph_refresh_check_does_not_requeue_active_or_failed_jobs():
    repository = InMemoryRepository()
    batch = build_research_graph_batch(
        _author(),
        [_work("https://openalex.org/W-REFRESH", "10.1000/refresh", 2024)],
    )
    apply_research_graph_batch(
        repository,
        batch,
        force_rebuild=False,
        warnings=[],
    )
    state = repository._research_graph_store["sync"][AUTHOR_ID]
    state["last_success_at"] = (
        datetime.now(timezone.utc) - timedelta(days=8)
    ).isoformat()

    assert research_graph_needs_refresh(repository, AUTHOR_ID)
    for status in ("queued", "updating", "failed"):
        state["status"] = status
        assert not research_graph_needs_refresh(repository, AUTHOR_ID)


def test_crossref_failure_does_not_replace_previous_verified_publication_fields():
    repository = InMemoryRepository()
    source_work = _work(
        "https://openalex.org/W-CROSSREF-STABLE",
        "10.1000/crossref-stable",
        2023,
    )
    verified = build_research_graph_batch(
        _author(),
        [source_work],
        crossref_records={
            "10.1000/crossref-stable": {
                "title": "Crossref verified title",
                "journal": "Crossref Verified Journal",
                "publication_year": 2023,
                "type": "journal-article",
            },
        },
    )
    apply_research_graph_batch(
        repository,
        verified,
        force_rebuild=False,
        warnings=[],
    )

    changed_openalex = deepcopy(source_work)
    changed_openalex["title"] = "Unverified replacement title"
    failed_crossref_batch = build_research_graph_batch(
        _author(),
        [changed_openalex],
        crossref_records={},
        crossref_report={"requested": 1, "verified": 0, "missing": 0, "failed": 1},
    )
    apply_research_graph_batch(
        repository,
        failed_crossref_batch,
        force_rebuild=False,
        warnings=["Crossref unavailable"],
    )
    paper = get_research_graph(repository, AUTHOR_ID)["papers"][0]

    assert paper["title"] == "Crossref verified title"
    assert paper["venue"] == "Crossref Verified Journal"
    assert paper["source"] == ["openalex", "crossref"]


def test_authenticated_graph_api_reads_queues_and_returns_object_details(monkeypatch):
    import main

    repository = InMemoryRepository()
    repository.publish_profile({
        "target_author_id": AUTHOR_ID,
        "target_author_profile": _author(),
        "deduped_works": [],
        "works_complete": True,
        "web_payload": {"name": "Dynamic Scholar", "totalPapers": 0},
        "warnings": [],
        "errors": [],
    })
    batch = build_research_graph_batch(
        _author(),
        [_work("https://openalex.org/W-API", "10.1000/api", 2024)],
    )
    apply_research_graph_batch(
        repository,
        batch,
        force_rebuild=False,
        warnings=[],
    )
    user = repository.create_password_user(
        "graph-user",
        hash_password("correct horse battery staple"),
    )
    raw_session = generate_token()
    repository.create_user_session(
        user["id"],
        hash_token(raw_session),
        datetime.now(timezone.utc) + timedelta(days=1),
    )
    monkeypatch.setattr(main, "repository", repository)
    monkeypatch.setattr(app.state, "repository", repository)
    monkeypatch.setenv("OPENALEX_API_KEY", "server-test-key")
    encoded_author_id = quote(AUTHOR_ID, safe="")

    with TestClient(app) as client:
        client.cookies.set("scholar_session", raw_session)
        graph_response = client.get(
            f"/api/authors/{encoded_author_id}/research-graph"
        )
        assert graph_response.status_code == 200
        paper_id = graph_response.json()["papers"][0]["id"]
        repository._research_graph_store["sync"][AUTHOR_ID]["status"] = "failed"

        refresh_response = client.post(
            f"/api/authors/{encoded_author_id}/research-graph/refresh",
            json={"force_rebuild": True},
        )
        detail_response = client.get(
            f"/api/research-graph/objects/paper/{paper_id}"
        )

    assert refresh_response.status_code == 200
    assert refresh_response.json()["force_rebuild"] is True
    assert detail_response.status_code == 200
    assert detail_response.json()["data"]["title"] == "Research graph paper 2024"


def test_profile_access_defers_graph_build_until_graph_tab_is_requested(monkeypatch):
    import main

    repository = InMemoryRepository()
    repository.publish_profile({
        "target_author_id": AUTHOR_ID,
        "target_author_profile": _author(),
        "deduped_works": [],
        "works_complete": True,
        "web_payload": {"name": "Dynamic Scholar", "totalPapers": 0},
        "warnings": [],
        "errors": [],
    })
    user = repository.create_password_user(
        "lazy-graph-user",
        hash_password("correct horse battery staple"),
    )
    raw_session = generate_token()
    repository.create_user_session(
        user["id"],
        hash_token(raw_session),
        datetime.now(timezone.utc) + timedelta(days=1),
    )
    monkeypatch.setattr(main, "repository", repository)
    monkeypatch.setattr(app.state, "repository", repository)
    monkeypatch.setenv("OPENALEX_API_KEY", "server-test-key")
    encoded_author_id = quote(AUTHOR_ID, safe="")

    with TestClient(app) as client:
        client.cookies.set("scholar_session", raw_session)
        profile_response = client.post(
            "/api/profile",
            json={"author_id": AUTHOR_ID},
        )
        assert profile_response.status_code == 200
        assert not getattr(repository, "_research_graph_store", {}).get("jobs")

        graph_response = client.get(
            f"/api/authors/{encoded_author_id}/research-graph"
        )

    assert graph_response.status_code == 200
    assert graph_response.json()["status"]["status"] == "queued"
    assert len(repository._research_graph_store["jobs"]) == 1


def test_graph_refresh_cannot_borrow_another_users_private_credential(monkeypatch):
    import main

    repository = InMemoryRepository()
    repository.publish_profile({
        "target_author_id": AUTHOR_ID,
        "target_author_profile": _author(),
        "deduped_works": [],
        "works_complete": True,
        "web_payload": {"name": "Dynamic Scholar", "totalPapers": 0},
        "warnings": [],
        "errors": [],
    })
    owner = repository.create_password_user(
        "graph-owner",
        hash_password("correct horse battery staple"),
    )
    other = repository.create_password_user(
        "graph-other",
        hash_password("correct horse battery staple"),
    )
    repository.save_user_api_credential(
        owner["id"],
        "openalex",
        encrypt_secret("owner-only-key"),
        "••••-key",
    )
    owner_session = generate_token()
    other_session = generate_token()
    expires_at = datetime.now(timezone.utc) + timedelta(days=1)
    repository.create_user_session(
        owner["id"],
        hash_token(owner_session),
        expires_at,
    )
    repository.create_user_session(
        other["id"],
        hash_token(other_session),
        expires_at,
    )
    monkeypatch.setattr(main, "repository", repository)
    monkeypatch.setattr(app.state, "repository", repository)
    monkeypatch.delenv("OPENALEX_API_KEY", raising=False)
    encoded_author_id = quote(AUTHOR_ID, safe="")

    with TestClient(app) as client:
        client.cookies.set("scholar_session", other_session)
        denied = client.post(
            f"/api/authors/{encoded_author_id}/research-graph/refresh",
            json={"force_rebuild": False},
        )
        client.cookies.set("scholar_session", owner_session)
        allowed = client.post(
            f"/api/authors/{encoded_author_id}/research-graph/refresh",
            json={"force_rebuild": False},
        )

    assert denied.status_code == 503
    assert allowed.status_code == 200
    jobs = repository._research_graph_store["jobs"]
    assert len(jobs) == 1
    assert next(iter(jobs.values()))["requested_by_user_id"] == owner["id"]
