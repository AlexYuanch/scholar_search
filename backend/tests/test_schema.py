import json
import os
import uuid

import psycopg
import pytest
from psycopg import errors


DATABASE_URL = os.getenv("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="TEST_DATABASE_URL is not configured")


EXPECTED_TABLES = {
    "analytics_events",
    "analytics_visitors",
    "api_rate_limit_events",
    "app_users",
    "auth_login_attempts",
    "auth_registration_attempts",
    "authorships",
    "favorites",
    "field_discovery_candidates",
    "field_discovery_institutions",
    "field_discovery_jobs",
    "field_discovery_state",
    "institutions",
    "openalex_identity_cache",
    "openalex_search_cache",
    "openalex_search_jobs",
    "profile_status",
    "refresh_jobs",
    "research_graph_refresh_jobs",
    "research_graph_sync_state",
    "research_topics",
    "scholar_aliases",
    "scholar_institutions",
    "scholar_profiles",
    "scholar_intelligence_feedback",
    "scholar_topics",
    "scholars",
    "collaborations",
    "collaboration_works",
    "paper_insights",
    "timeline_events",
    "user_history",
    "user_sessions",
    "upstream_rate_limits",
    "user_api_credentials",
    "work_citations",
    "work_external_ids",
    "work_topics",
    "works",
}


def test_portable_schema_has_expected_tables_without_rls():
    with psycopg.connect(DATABASE_URL) as connection:
        rows = connection.execute("""
            select c.relname, c.relrowsecurity
            from pg_class c
            join pg_namespace n on n.oid = c.relnamespace
            where n.nspname = 'public' and c.relkind = 'r'
        """).fetchall()

    tables = {name for name, _ in rows}
    assert EXPECTED_TABLES <= tables
    assert all(not rls for name, rls in rows if name in EXPECTED_TABLES)


def test_application_role_cannot_create_tables():
    with psycopg.connect(DATABASE_URL) as connection:
        with pytest.raises(errors.InsufficientPrivilege):
            connection.execute("create table public.should_not_exist (id integer)")


def test_local_password_user_columns_are_present():
    with psycopg.connect(DATABASE_URL) as connection:
        columns = {
            row[0]: row[1]
            for row in connection.execute("""
                select column_name, is_nullable
                from information_schema.columns
                where table_schema = 'public' and table_name = 'app_users'
            """)
        }

    assert columns["username"] == "NO"
    assert columns["normalized_username"] == "NO"
    assert columns["password_hash"] == "NO"
    assert columns["role"] == "NO"
    assert "email" not in columns
    assert "normalized_email" not in columns


def test_analytics_tables_do_not_store_raw_ip():
    with psycopg.connect(DATABASE_URL) as connection:
        columns = {
            row[0]
            for row in connection.execute("""
                select column_name
                from information_schema.columns
                where table_schema = 'public'
                  and table_name in ('analytics_visitors', 'analytics_events')
            """)
        }

    assert "request_ip" not in columns
    assert "ip" not in columns


def test_favorite_tracking_columns_are_present():
    with psycopg.connect(DATABASE_URL) as connection:
        columns = {
            row[0]: row[1]
            for row in connection.execute("""
                select column_name, is_nullable
                from information_schema.columns
                where table_schema = 'public' and table_name = 'favorites'
            """)
        }

    assert columns["last_seen_profile_version"] == "NO"
    assert columns["last_seen_total_papers"] == "NO"
    assert columns["last_seen_total_citations"] == "NO"
    assert columns["last_seen_at"] == "YES"


def test_user_api_credentials_and_queue_ownership_are_present():
    with psycopg.connect(DATABASE_URL) as connection:
        credential_columns = {
            row[0]
            for row in connection.execute("""
                select column_name
                from information_schema.columns
                where table_schema = 'public'
                  and table_name = 'user_api_credentials'
            """)
        }
        queue_columns = {
            (row[0], row[1])
            for row in connection.execute("""
                select table_name, column_name
                from information_schema.columns
                where table_schema = 'public'
                  and table_name in ('refresh_jobs', 'openalex_search_jobs')
                  and column_name = 'requested_by_user_id'
            """)
        }

    assert {
        "user_id",
        "provider",
        "encrypted_secret",
        "key_hint",
        "validated_at",
    } <= credential_columns
    assert queue_columns == {
        ("refresh_jobs", "requested_by_user_id"),
        ("openalex_search_jobs", "requested_by_user_id"),
    }


def test_dynamic_research_graph_columns_and_relation_sources_are_present():
    with psycopg.connect(DATABASE_URL) as connection:
        work_columns = {
            row[0]
            for row in connection.execute("""
                select column_name
                from information_schema.columns
                where table_schema = 'public' and table_name = 'works'
            """)
        }
        sourced_relations = {
            row[0]
            for row in connection.execute("""
                select table_name
                from information_schema.columns
                where table_schema = 'public'
                  and table_name in (
                      'authorships', 'scholar_institutions', 'work_topics',
                      'scholar_topics', 'collaborations', 'collaboration_works',
                      'work_citations', 'timeline_events'
                  )
                  and column_name = 'source'
            """)
        }

    assert {
        "abstract",
        "publication_date",
        "venue",
        "source_updated_at",
        "last_synced_at",
        "metadata_sources",
        "confidence",
    } <= work_columns
    assert sourced_relations == {
        "authorships",
        "scholar_institutions",
        "work_topics",
        "scholar_topics",
        "collaborations",
        "collaboration_works",
        "work_citations",
        "timeline_events",
    }


def test_scholar_intelligence_feedback_is_user_owned_and_versioned():
    with psycopg.connect(DATABASE_URL) as connection:
        columns = {
            row[0]: row[1]
            for row in connection.execute("""
                select column_name, is_nullable
                from information_schema.columns
                where table_schema = 'public'
                  and table_name = 'scholar_intelligence_feedback'
            """)
        }

    assert columns["user_id"] == "NO"
    assert columns["target_author_id"] == "NO"
    assert columns["candidate_author_id"] == "NO"
    assert columns["analysis_key"] == "NO"
    assert columns["verdict"] == "NO"
    assert columns["analysis_version"] == "NO"


def test_field_discovery_relations_reuse_graph_entities_and_user_owned_jobs():
    with psycopg.connect(DATABASE_URL) as connection:
        candidate_foreign_keys = {
            row[0].rsplit(".", 1)[-1]
            for row in connection.execute("""
                select confrelid::regclass::text
                from pg_constraint
                where conrelid = 'public.field_discovery_candidates'::regclass
                  and contype = 'f'
            """)
        }
        state_columns = {
            row[0]
            for row in connection.execute("""
                select column_name
                from information_schema.columns
                where table_schema = 'public'
                  and table_name = 'field_discovery_state'
            """)
        }

    assert candidate_foreign_keys == {"scholars"}
    assert {
        "focus_scholar_id",
        "requested_by_user_id",
        "selected_topics",
        "discovered_count",
        "analyzed_count",
        "target_count",
        "last_success_at",
        "retry_after_at",
    } <= state_columns


def test_profile_status_emits_postgres_notification():
    author_id = f"schema-test-{uuid.uuid4()}"
    with psycopg.connect(DATABASE_URL, autocommit=True) as connection:
        connection.execute("listen profile_status")
        scholar_id = connection.execute(
            """
            insert into public.scholars (source, source_author_id, display_name)
            values ('test', %s, 'Schema Test') returning id
            """,
            (author_id,),
        ).fetchone()[0]
        connection.execute(
            "insert into public.profile_status (scholar_id, version, status) values (%s, 1, 'ready')",
            (scholar_id,),
        )
        notifications = list(connection.notifies(timeout=2, stop_after=1))
        connection.execute("delete from public.scholars where id = %s", (scholar_id,))

    assert notifications
    payload = json.loads(notifications[0].payload)
    assert payload["scholar_id"] == str(scholar_id)
    assert payload["version"] == 1
    assert payload["status"] == "ready"
