import os
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from auth import hash_password, verify_password
from credentials import decrypt_secret, encrypt_secret
from repository import APIQuotaExceeded, PostgresRepository
from research_graph import build_research_graph_batch
from research_graph_repository import (
    apply_research_graph_batch,
    get_research_graph,
)
from worker import process_one_job, process_one_search_job


DATABASE_URL = os.getenv("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="TEST_DATABASE_URL is not configured")


def _state(work_count: int) -> dict:
    works = []
    for index in range(work_count):
        works.append({
            "id": f"https://openalex.org/W-CODEX-{index}",
            "title": f"Integration paper {index}",
            "publication_year": 2020 + index % 5,
            "cited_by_count": index,
            "authorships": [
                {
                    "author_position": "first",
                    "author": {"id": "https://openalex.org/A-CODEX", "display_name": "Test Scholar"},
                    "institutions": [],
                },
                {
                    "author_position": "middle",
                    "author": {"id": "https://openalex.org/A-CODEX-CO", "display_name": "Same Name"},
                    "institutions": [],
                },
            ],
        })
    return {
        "target_author_id": "https://openalex.org/A-CODEX",
        "target_author_profile": {
            "id": "https://openalex.org/A-CODEX",
            "display_name": "Test Scholar",
            "works_count": work_count,
            "cited_by_count": 100,
            "summary_stats": {"h_index": 5},
            "last_known_institutions": [],
        },
        "deduped_works": works,
        "works_complete": True,
        "web_payload": {"name": "Test Scholar", "totalPapers": work_count, "totalCitations": 100},
        "warnings": [],
        "errors": [],
    }


def test_publish_paginate_and_refresh_queue_against_postgres():
    repository = PostgresRepository(DATABASE_URL)
    try:
        initial_state = _state(55)
        initial_state["topic_clusters"] = [{
            "topic": "Knowledge graph",
            "paper_indices": [0],
        }]
        first = repository.publish_profile(initial_state, query_name="Test Scholar")
        page = repository.list_works("https://openalex.org/A-CODEX", 50, 0, "citations")
        filtered_page = repository.list_works(
            "https://openalex.org/A-CODEX",
            50,
            0,
            "citations",
            year=2020,
            topic="Knowledge graph",
        )

        assert first["profile_version"] == 1
        assert first["data_fingerprint"]
        assert page["total"] == 55
        assert len(page["items"]) == 50
        assert filtered_page["total"] == 1
        assert filtered_page["items"][0]["topics"] == ["Knowledge graph"]

        second = repository.publish_profile(_state(0), query_name="Test Scholar")
        assert second["profile_version"] == 2
        assert repository.list_works("https://openalex.org/A-CODEX", 50, 0, "citations")["total"] == 0

        job_id = repository.enqueue_refresh("https://openalex.org/A-CODEX", "integration_test")
        assert repository.enqueue_refresh("https://openalex.org/A-CODEX", "duplicate") == job_id
        claimed = repository.claim_refresh_job()
        assert str(claimed["id"]) == job_id
        assert repository.get_profile("https://openalex.org/A-CODEX")["refresh_status"] == "updating"

        repository.fail_refresh_job(job_id, "expected", retry=False)
        assert repository.get_profile("https://openalex.org/A-CODEX")["refresh_status"] == "failed"
    finally:
        with repository.engine.begin() as conn:
            conn.execute(text("delete from public.works where source_work_id like 'https://openalex.org/W-CODEX-%'"))
            conn.execute(text("delete from public.scholars where source_author_id like 'https://openalex.org/A-CODEX%'"))


def test_cached_profile_keeps_publication_affiliations_separate_from_employment():
    repository = PostgresRepository(DATABASE_URL)
    unique = os.urandom(6).hex()
    author_id = f"https://openalex.org/A-IDENTITY-{unique}"
    try:
        state = _state(1)
        state["target_author_id"] = author_id
        state["target_author_profile"].update({
            "id": author_id,
            "orcid": "https://orcid.org/0000-0000-0000-0001",
            "last_known_institutions": [
                {"id": "I1", "display_name": "Tongji University"},
            ],
            "affiliations": [{
                "institution": {"id": "I1", "display_name": "Tongji University"},
                "years": [2026],
            }],
        })
        authorship = state["deduped_works"][0]["authorships"][0]
        authorship["author"]["id"] = author_id
        authorship["raw_affiliation_strings"] = [
            "Shanghai Research Institute for Intelligent Autonomous Systems, "
            "Tongji University, Shanghai, China"
        ]
        state["web_payload"].pop("affiliationEvidence", None)
        state["web_payload"]["professionalIdentity"] = {
            "currentInstitution": "Tongji University",
            "researchUnit": (
                "Shanghai Research Institute for Intelligent Autonomous Systems"
            ),
        }
        state["web_payload"]["department"] = "Incorrect inferred department"

        saved = repository.publish_profile(state, query_name="Identity Scholar")
        reloaded = PostgresRepository(DATABASE_URL).get_profile(author_id)

        assert "professionalIdentity" not in saved["payload"]
        assert "professionalIdentity" not in reloaded["payload"]
        assert saved["payload"]["department"] == ""
        assert reloaded["payload"]["department"] == ""
        expected_statement = {
            "text": (
                "Shanghai Research Institute for Intelligent Autonomous Systems, "
                "Tongji University, Shanghai, China"
            ),
            "years": [2020],
        }
        assert (
            saved["payload"]["affiliationEvidence"]["publicationAffiliationStatements"]
            == [expected_statement]
        )
        assert (
            reloaded["payload"]["affiliationEvidence"]
            == saved["payload"]["affiliationEvidence"]
        )
        assert (
            reloaded["payload"]["affiliationEvidence"]["verifiedEmployment"]
            is None
        )
    finally:
        with repository.engine.begin() as conn:
            conn.execute(
                text("delete from public.scholars where source_author_id = :author_id"),
                {"author_id": author_id},
            )


def test_password_user_session_is_revocable():
    repository = PostgresRepository(DATABASE_URL)
    unique = os.urandom(8).hex()
    session_hash = ((unique[::-1]) * 8)[:64]
    username = f"integration-{unique}"
    registration_ip = f"192.0.2.{int(unique[:2], 16) % 254 + 1}"
    try:
        repository.enforce_registration_rate_limit(registration_ip)
        repository.record_registration_attempt(registration_ip, True)
        password_hash = hash_password("integration password")
        user = repository.create_password_user(username, password_hash)
        stored = repository.get_user_for_login(username.upper())
        assert stored["id"] == user["id"]
        assert verify_password("integration password", stored["password_hash"])

        repository.consume_api_quota("profile", user["id"], registration_ip, 2, 10, 600)
        repository.consume_api_quota("profile", user["id"], registration_ip, 2, 10, 600)
        with pytest.raises(APIQuotaExceeded):
            repository.consume_api_quota("profile", user["id"], registration_ip, 2, 10, 600)

        repository.record_login_attempt(username, "127.0.0.1", True)
        repository.create_user_session(
            user_id=user["id"],
            session_hash=session_hash,
            session_expires_at=datetime.now(timezone.utc) + timedelta(days=1),
            user_agent="pytest",
            request_ip="127.0.0.1",
        )

        assert repository.get_user_by_session(session_hash) == {
            "id": user["id"],
            "username": username,
        }

        repository.revoke_session(session_hash)
        assert repository.get_user_by_session(session_hash) is None
    finally:
        with repository.engine.begin() as conn:
            conn.execute(text(
                "delete from public.auth_registration_attempts where request_ip = cast(:request_ip as inet)"
            ), {"request_ip": registration_ip})
            conn.execute(text(
                "delete from public.auth_login_attempts where normalized_username = :username"
            ), {"username": username})
            conn.execute(text(
                "delete from public.app_users where normalized_username = :username"
            ), {"username": username})


def test_user_openalex_credential_is_persistent_private_and_owns_jobs():
    repository = PostgresRepository(DATABASE_URL)
    unique = os.urandom(6).hex()
    username = f"credential-{unique}"
    other_username = f"credential-other-{unique}"
    query_key = f"credential scholar {unique}"
    try:
        user = repository.create_password_user(
            username,
            hash_password("credential password"),
        )
        other_user = repository.create_password_user(
            other_username,
            hash_password("credential password"),
        )
        encrypted = encrypt_secret("owned-openalex-key")
        repository.save_user_api_credential(
            user["id"],
            "openalex",
            encrypted,
            "••••-key",
        )
        job_id = repository.enqueue_openalex_search(
            query_key,
            f"Credential Scholar {unique}",
            requested_by_user_id=user["id"],
        )

        reloaded = PostgresRepository(DATABASE_URL)
        stored = reloaded.get_user_api_credential(user["id"], "openalex")
        claimed = reloaded.claim_openalex_search_job(query_key)

        assert stored["encrypted_secret"] == encrypted
        assert decrypt_secret(stored["encrypted_secret"]) == "owned-openalex-key"
        assert reloaded.get_user_api_credential(other_user["id"], "openalex") is None
        assert str(claimed["requested_by_user_id"]) == user["id"]

        reloaded.complete_openalex_search_job(job_id)
        assert reloaded.delete_user_api_credential(other_user["id"], "openalex") is False
        assert reloaded.get_user_api_credential(user["id"], "openalex") is not None
        assert reloaded.delete_user_api_credential(user["id"], "openalex") is True
        assert reloaded.get_user_api_credential(user["id"], "openalex") is None
    finally:
        with repository.engine.begin() as conn:
            conn.execute(text(
                "delete from public.openalex_search_jobs where query_key = :query_key"
            ), {"query_key": query_key})
            conn.execute(text("""
                delete from public.app_users
                where normalized_username in (:username, :other_username)
            """), {
                "username": username,
                "other_username": other_username,
            })


def test_favorite_tracking_reports_and_clears_profile_deltas():
    repository = PostgresRepository(DATABASE_URL)
    unique = os.urandom(6).hex()
    author_id = f"https://openalex.org/A-TRACK-{unique}"
    username = f"tracking-{unique}"
    other_username = f"tracking-other-{unique}"
    try:
        user = repository.create_password_user(username, hash_password("tracking password"))
        other_user = repository.create_password_user(other_username, hash_password("tracking password"))
        initial_state = _state(1)
        initial_state["target_author_id"] = author_id
        initial_state["target_author_profile"]["id"] = author_id
        initial_state["deduped_works"][0]["authorships"][0]["author"]["id"] = author_id
        initial_state["web_payload"]["totalCitations"] = 10
        repository.publish_profile(initial_state, query_name="Tracking Scholar")
        repository.add_favorite(user["id"], author_id)

        reloaded_repository = PostgresRepository(DATABASE_URL)
        assert reloaded_repository.is_tracking(user["id"], author_id) is True
        assert reloaded_repository.list_favorites(user["id"])[0]["has_updates"] is False
        assert reloaded_repository.is_tracking(other_user["id"], author_id) is False
        assert reloaded_repository.list_favorites(other_user["id"]) == []

        updated_state = _state(2)
        updated_state["target_author_id"] = author_id
        updated_state["target_author_profile"]["id"] = author_id
        for work in updated_state["deduped_works"]:
            work["authorships"][0]["author"]["id"] = author_id
        updated_state["web_payload"]["totalCitations"] = 35
        saved = repository.publish_profile(updated_state, query_name="Tracking Scholar")

        tracked = repository.list_favorites(user["id"])[0]
        assert tracked["has_updates"] is True
        assert tracked["new_papers"] == 1
        assert tracked["new_citations"] == 25

        repository.mark_favorite_seen(other_user["id"], author_id, saved["profile_version"])
        assert repository.list_favorites(user["id"])[0]["has_updates"] is True

        repository.mark_favorite_seen(user["id"], author_id, saved["profile_version"])
        assert repository.list_favorites(user["id"])[0]["has_updates"] is False
    finally:
        with repository.engine.begin() as conn:
            conn.execute(text(
                "delete from public.app_users where normalized_username in (:username, :other_username)"
            ), {"username": username, "other_username": other_username})
            conn.execute(text("delete from public.scholars where source_author_id = :author_id"), {"author_id": author_id})


def test_postgres_refresh_job_is_persisted_and_processed_by_worker():
    repository = PostgresRepository(DATABASE_URL)
    unique = os.urandom(6).hex()
    author_id = f"https://openalex.org/A-WORKER-{unique}"

    def state_for_author(work_count: int) -> dict:
        state = _state(work_count)
        state["target_author_id"] = author_id
        state["target_author_profile"]["id"] = author_id
        for work in state["deduped_works"]:
            work["authorships"][0]["author"]["id"] = author_id
        return state

    class DeterministicWorkflowGraph:
        def invoke(self, state):
            assert state["target_author_id"] == author_id
            return state_for_author(2)

    try:
        repository.publish_profile(state_for_author(1), query_name="Worker Scholar")
        job_id = repository.enqueue_refresh(author_id, "worker_integration")

        worker_repository = PostgresRepository(DATABASE_URL)
        assert process_one_job(worker_repository, DeterministicWorkflowGraph()) is True

        reloaded_repository = PostgresRepository(DATABASE_URL)
        assert reloaded_repository.get_profile(author_id)["profile_version"] == 2
        assert reloaded_repository.list_works(author_id, 50, 0, "citations")["total"] == 2
        with reloaded_repository.engine.connect() as conn:
            job_status = conn.execute(text("""
                select status from public.refresh_jobs where id = cast(:job_id as uuid)
            """), {"job_id": job_id}).scalar_one()
        assert job_status == "succeeded"
    finally:
        with repository.engine.begin() as conn:
            conn.execute(text("delete from public.scholars where source_author_id = :author_id"), {"author_id": author_id})


def test_maintenance_recovers_abandoned_running_job():
    repository = PostgresRepository(DATABASE_URL)
    author_id = f"https://openalex.org/A-LEASE-{os.urandom(4).hex()}"
    state = _state(1)
    state["target_author_id"] = author_id
    state["target_author_profile"]["id"] = author_id
    state["deduped_works"][0]["authorships"][0]["author"]["id"] = author_id
    try:
        repository.publish_profile(state, query_name="Lease Test")
        job_id = repository.enqueue_refresh(author_id, "lease_test")
        repository.claim_refresh_job()
        with repository.engine.begin() as conn:
            conn.execute(text("""
                update public.refresh_jobs
                set locked_at = now() - interval '2 hours'
                where id = cast(:job_id as uuid)
            """), {"job_id": job_id})

        repository.run_maintenance()

        with repository.engine.connect() as conn:
            status = conn.execute(text("""
                select status from public.refresh_jobs where id = cast(:job_id as uuid)
            """), {"job_id": job_id}).scalar_one()
        assert status == "pending"
        assert repository.get_profile(author_id)["refresh_status"] == "queued"
    finally:
        with repository.engine.begin() as conn:
            conn.execute(text("delete from public.scholars where source_author_id = :author_id"), {"author_id": author_id})


def test_maintenance_queues_tracked_scholar_without_user_openalex_credential():
    repository = PostgresRepository(DATABASE_URL)
    unique = os.urandom(6).hex()
    author_id = f"https://openalex.org/A-SHARED-KEY-{unique}"
    username = f"shared-key-{unique}"
    state = _state(1)
    state["target_author_id"] = author_id
    state["target_author_profile"]["id"] = author_id
    state["deduped_works"][0]["authorships"][0]["author"]["id"] = author_id
    user = repository.create_password_user(
        username,
        hash_password("shared key password"),
    )
    try:
        repository.publish_profile(state, query_name="Shared Key Scholar")
        repository.add_favorite(user["id"], author_id)
        with repository.engine.begin() as conn:
            conn.execute(text("""
                update public.scholars
                set last_synced_at = now() - interval '2 days'
                where source_author_id = :author_id
            """), {"author_id": author_id})

        result = repository.run_maintenance()

        assert result["enqueued"] >= 1
        with repository.engine.connect() as conn:
            requester = conn.execute(text("""
                select j.requested_by_user_id
                from public.refresh_jobs j
                join public.scholars s on s.id = j.scholar_id
                where s.source_author_id = :author_id
                  and j.status = 'pending'
            """), {"author_id": author_id}).scalar_one()
        assert str(requester) == user["id"]
    finally:
        with repository.engine.begin() as conn:
            conn.execute(text(
                "delete from public.app_users where normalized_username = :username"
            ), {"username": username})
            conn.execute(text(
                "delete from public.scholars where source_author_id = :author_id"
            ), {"author_id": author_id})


def test_openalex_cache_jobs_and_budget_are_shared_across_repository_instances():
    repository = PostgresRepository(DATABASE_URL)
    unique = os.urandom(6).hex()
    query_key = f"integration scholar {unique}"
    author_id = f"https://openalex.org/A-CACHE-{unique}"
    provider = f"openalex-integration-{unique}"
    candidates = [{"id": author_id, "name": "Integration Scholar"}]
    try:
        repository.save_openalex_search_cache(
            query_key,
            "Integration Scholar",
            candidates,
            3600,
        )
        repository.save_openalex_identity_cache(
            author_id,
            {
                "sampled_works": 1,
                "work_ids": ["W1"],
                "coauthor_ids": [],
                "topic_ids": ["T1"],
            },
            3600,
        )
        job_id = repository.enqueue_openalex_search(query_key, "Integration Scholar")
        assert repository.enqueue_openalex_search(query_key, "Duplicate Text") == job_id
        repository.record_upstream_rate_limit(provider, 1000, 10, 600)

        reloaded = PostgresRepository(DATABASE_URL)
        cached = reloaded.get_openalex_search_cache(query_key)
        identity = reloaded.get_openalex_identity_caches([author_id])
        claimed = reloaded.claim_openalex_search_job(query_key)

        assert cached["fresh"] is True
        assert cached["candidates"] == candidates
        assert identity[author_id]["fresh"] is True
        assert identity[author_id]["fingerprint"]["topic_ids"] == ["T1"]
        assert str(claimed["id"]) == job_id
        assert reloaded.claim_openalex_search_job(query_key) is None
        assert 1 <= reloaded.get_upstream_retry_after(provider, 200) <= 600

        reloaded.complete_openalex_search_job(job_id)
    finally:
        with repository.engine.begin() as conn:
            conn.execute(text(
                "delete from public.openalex_search_jobs where query_key = :query_key"
            ), {"query_key": query_key})
            conn.execute(text(
                "delete from public.openalex_search_cache where query_key = :query_key"
            ), {"query_key": query_key})
            conn.execute(text(
                "delete from public.openalex_identity_cache where author_id = :author_id"
            ), {"author_id": author_id})
            conn.execute(text(
                "delete from public.upstream_rate_limits where provider = :provider"
            ), {"provider": provider})


def test_postgres_openalex_search_job_is_processed_by_worker():
    repository = PostgresRepository(DATABASE_URL)
    unique = os.urandom(6).hex()
    query_key = f"worker scholar {unique}"
    query_text = f"Worker Scholar {unique}"
    job_id = repository.enqueue_openalex_search(query_key, query_text)

    def builder(_repository, received_query):
        assert received_query == query_text
        return [{"id": f"A-{unique}", "name": query_text}], True

    try:
        worker_repository = PostgresRepository(DATABASE_URL)
        assert process_one_search_job(worker_repository, builder) is True

        reloaded = PostgresRepository(DATABASE_URL)
        cached = reloaded.get_openalex_search_cache(query_key)
        with reloaded.engine.connect() as conn:
            status = conn.execute(text("""
                select status
                from public.openalex_search_jobs
                where id = cast(:job_id as uuid)
            """), {"job_id": job_id}).scalar_one()

        assert status == "succeeded"
        assert cached["fresh"] is True
        assert cached["candidates"][0]["name"] == query_text
    finally:
        with repository.engine.begin() as conn:
            conn.execute(text(
                "delete from public.openalex_search_jobs where query_key = :query_key"
            ), {"query_key": query_key})
            conn.execute(text(
                "delete from public.openalex_search_cache where query_key = :query_key"
            ), {"query_key": query_key})


def test_dynamic_research_graph_is_incremental_unique_and_queryable():
    repository = PostgresRepository(DATABASE_URL)
    unique = os.urandom(6).hex()
    author_id = f"https://openalex.org/A-GRAPH-{unique}"
    coauthor_id = f"https://openalex.org/A-GRAPH-CO-{unique}"
    institution_id = f"https://openalex.org/I-GRAPH-{unique}"
    topic_id = f"https://openalex.org/T-GRAPH-{unique}"
    work_prefix = f"https://openalex.org/W-GRAPH-{unique}"

    author = {
        "id": author_id,
        "display_name": f"Graph Scholar {unique}",
        "works_count": 2,
        "cited_by_count": 5,
        "summary_stats": {"h_index": 1},
        "affiliations": [{
            "institution": {
                "id": institution_id,
                "display_name": f"Graph University {unique}",
            },
            "years": [2022, 2024],
        }],
        "last_known_institutions": [{
            "id": institution_id,
            "display_name": f"Graph University {unique}",
        }],
    }

    def work(index: int, year: int, referenced=None, abstract=True):
        abstract_index = {
            "We": [0],
            "propose": [1],
            "incremental": [2],
            "graphs.": [3],
        } if abstract else None
        return {
            "id": f"{work_prefix}-{index}",
            "doi": f"10.5555/{unique}.{index}",
            "title": f"Graph paper {index}",
            "publication_year": year,
            "publication_date": f"{year}-01-01",
            "updated_date": f"{year}-02-01T00:00:00Z",
            "cited_by_count": index,
            "abstract_inverted_index": abstract_index,
            "referenced_works": referenced or [],
            "authorships": [
                {
                    "author_position": "first",
                    "author": {"id": author_id, "display_name": "Graph Scholar"},
                    "institutions": [{
                        "id": institution_id,
                        "display_name": "Graph University",
                    }],
                },
                {
                    "author_position": "last",
                    "author": {
                        "id": coauthor_id,
                        "display_name": "Graph Collaborator",
                    },
                    "institutions": [],
                },
            ],
            "primary_topic": {
                "id": topic_id,
                "display_name": f"Dynamic Graph {unique}",
                "score": 0.9,
            },
            "topics": [{
                "id": topic_id,
                "display_name": f"Dynamic Graph {unique}",
                "score": 0.9,
            }],
            "primary_location": {"source": {"display_name": "Graph Journal"}},
            "type": "article",
            "language": "en",
        }

    try:
        first_work = work(1, 2022)
        repository.publish_profile({
            "target_author_id": author_id,
            "target_author_profile": author,
            "deduped_works": [first_work],
            "works_complete": True,
            "web_payload": {
                "name": f"Graph Scholar {unique}",
                "totalPapers": 1,
                "totalCitations": 1,
            },
            "warnings": [],
            "errors": [],
        })
        first_batch = build_research_graph_batch(author, [first_work])
        apply_research_graph_batch(
            repository,
            first_batch,
            force_rebuild=False,
            warnings=[],
        )
        apply_research_graph_batch(
            repository,
            first_batch,
            force_rebuild=False,
            warnings=[],
        )
        second_work = work(
            2,
            2024,
            referenced=[f"{work_prefix}-1"],
            abstract=False,
        )
        second_batch = build_research_graph_batch(
            author,
            [second_work],
        )
        apply_research_graph_batch(
            repository,
            second_batch,
            force_rebuild=False,
            warnings=[],
        )

        graph = get_research_graph(repository, author_id)

        assert len(graph["papers"]) == 2
        assert graph["papers"][0]["year"] == 2024
        assert graph["papers"][0]["insight"]["based_on_abstract"] is False
        assert graph["topic_evolution"][0]["works_count"] == 2
        assert graph["collaborations"][0]["works_count"] == 2
        assert graph["affiliations"][0]["is_current"] is True
        assert any(
            citation["cited"]["title"] == "Graph paper 1"
            for citation in graph["citations"]
        )
        years = [
            event["event_year"]
            for event in graph["timeline"]
            if event["event_year"]
        ]
        assert years == sorted(years, reverse=True)

        with repository.engine.connect() as conn:
            counts = {
                table: conn.execute(text(f"select count(*) from public.{table}")).scalar_one()
                for table in (
                    "work_topics",
                    "scholar_topics",
                    "collaborations",
                    "work_citations",
                )
            }
        assert all(value >= 1 for value in counts.values())

        apply_research_graph_batch(
            repository,
            build_research_graph_batch(author, [second_work]),
            force_rebuild=True,
            warnings=[],
        )
        rebuilt = get_research_graph(repository, author_id)
        assert [paper["source_id"] for paper in rebuilt["papers"]] == [
            f"{work_prefix}-2"
        ]
        assert rebuilt["topic_evolution"][0]["works_count"] == 1
        assert rebuilt["collaborations"][0]["works_count"] == 1
        assert {
            event["title"]
            for event in rebuilt["timeline"]
            if event["event_type"] == "paper_published"
        } == {"Graph paper 2"}
    finally:
        with repository.engine.begin() as conn:
            conn.execute(text("""
                delete from public.works
                where source_work_id like :work_prefix
            """), {"work_prefix": f"{work_prefix}%"})
            conn.execute(text("""
                delete from public.scholars
                where source_author_id in (:author_id, :coauthor_id)
            """), {"author_id": author_id, "coauthor_id": coauthor_id})
            conn.execute(text("""
                delete from public.institutions
                where source_institution_id = :institution_id
            """), {"institution_id": institution_id})
            conn.execute(text("""
                delete from public.research_topics
                where source_topic_id = :topic_id
            """), {"topic_id": topic_id})
