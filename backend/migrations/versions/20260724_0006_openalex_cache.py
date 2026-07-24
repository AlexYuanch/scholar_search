"""Add shared OpenAlex caches, search jobs, and budget state.

Revision ID: 20260724_0006
Revises: 20260722_0005
"""
from alembic import op


revision = "20260724_0006"
down_revision = "20260722_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        create table public.openalex_search_cache (
            query_key text primary key,
            query_text text not null,
            candidates jsonb not null default '[]'::jsonb,
            expires_at timestamptz not null,
            created_at timestamptz not null default now(),
            updated_at timestamptz not null default now(),
            check (query_key = lower(btrim(query_key))),
            check (jsonb_typeof(candidates) = 'array')
        );

        create table public.openalex_identity_cache (
            author_id text primary key,
            fingerprint jsonb not null default '{}'::jsonb,
            expires_at timestamptz not null,
            created_at timestamptz not null default now(),
            updated_at timestamptz not null default now(),
            check (jsonb_typeof(fingerprint) = 'object')
        );

        create table public.openalex_search_jobs (
            id uuid primary key default gen_random_uuid(),
            query_key text not null,
            query_text text not null,
            status text not null default 'pending'
                check (status in ('pending', 'running', 'succeeded', 'failed')),
            attempts integer not null default 0 check (attempts >= 0),
            scheduled_at timestamptz not null default now(),
            started_at timestamptz,
            locked_at timestamptz,
            finished_at timestamptz,
            last_error text,
            created_at timestamptz not null default now(),
            updated_at timestamptz not null default now(),
            check (query_key = lower(btrim(query_key)))
        );

        create table public.upstream_rate_limits (
            provider text primary key,
            limit_credits bigint,
            remaining_credits bigint,
            reset_at timestamptz,
            updated_at timestamptz not null default now(),
            check (limit_credits is null or limit_credits >= 0),
            check (remaining_credits is null or remaining_credits >= 0)
        );

        create unique index openalex_search_jobs_one_active_per_query
            on public.openalex_search_jobs (query_key)
            where status in ('pending', 'running');
        create index openalex_search_jobs_claim_idx
            on public.openalex_search_jobs (status, scheduled_at)
            where status = 'pending';
        create index openalex_search_cache_expiry_idx
            on public.openalex_search_cache (expires_at);
        create index openalex_identity_cache_expiry_idx
            on public.openalex_identity_cache (expires_at);

        revoke all on public.openalex_search_cache from public;
        revoke all on public.openalex_identity_cache from public;
        revoke all on public.openalex_search_jobs from public;
        revoke all on public.upstream_rate_limits from public;

        do $$
        begin
            if exists (select 1 from pg_roles where rolname = 'scholar_app') then
                grant select, insert, update, delete on public.openalex_search_cache to scholar_app;
                grant select, insert, update, delete on public.openalex_identity_cache to scholar_app;
                grant select, insert, update, delete on public.openalex_search_jobs to scholar_app;
                grant select, insert, update, delete on public.upstream_rate_limits to scholar_app;
            end if;
        end $$;
    """)


def downgrade() -> None:
    op.execute("""
        drop table if exists public.upstream_rate_limits;
        drop table if exists public.openalex_search_jobs;
        drop table if exists public.openalex_identity_cache;
        drop table if exists public.openalex_search_cache;
    """)
