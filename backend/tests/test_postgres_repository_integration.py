import os
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from auth import hash_password, verify_password
from repository import PostgresRepository


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
        "web_payload": {"name": "Test Scholar", "totalPapers": work_count},
        "warnings": [],
        "errors": [],
    }


def test_publish_paginate_and_refresh_queue_against_postgres():
    repository = PostgresRepository(DATABASE_URL)
    try:
        first = repository.publish_profile(_state(55), query_name="Test Scholar")
        page = repository.list_works("https://openalex.org/A-CODEX", 50, 0, "citations")

        assert first["profile_version"] == 1
        assert first["data_fingerprint"]
        assert page["total"] == 55
        assert len(page["items"]) == 50

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
