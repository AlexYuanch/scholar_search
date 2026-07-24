import json
import os
import uuid

import psycopg
import pytest
from psycopg import errors


DATABASE_URL = os.getenv("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="TEST_DATABASE_URL is not configured")


EXPECTED_TABLES = {
    "api_rate_limit_events",
    "app_users",
    "auth_login_attempts",
    "auth_registration_attempts",
    "authorships",
    "favorites",
    "institutions",
    "openalex_identity_cache",
    "openalex_search_cache",
    "openalex_search_jobs",
    "profile_status",
    "refresh_jobs",
    "scholar_aliases",
    "scholar_institutions",
    "scholar_profiles",
    "scholars",
    "user_history",
    "user_sessions",
    "upstream_rate_limits",
    "user_api_credentials",
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
    assert "email" not in columns
    assert "normalized_email" not in columns


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
