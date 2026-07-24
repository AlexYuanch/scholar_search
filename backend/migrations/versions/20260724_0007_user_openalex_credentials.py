"""Add encrypted user OpenAlex credentials and queue ownership.

Revision ID: 20260724_0007
Revises: 20260724_0006
"""
from alembic import op


revision = "20260724_0007"
down_revision = "20260724_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        create table public.user_api_credentials (
            user_id uuid not null references public.app_users(id) on delete cascade,
            provider text not null,
            encrypted_secret text not null,
            key_hint text not null,
            validated_at timestamptz not null,
            created_at timestamptz not null default now(),
            updated_at timestamptz not null default now(),
            primary key (user_id, provider),
            check (provider in ('openalex')),
            check (length(encrypted_secret) >= 32),
            check (length(key_hint) between 4 and 16)
        );

        alter table public.refresh_jobs
            add column requested_by_user_id uuid
            references public.app_users(id) on delete set null;
        alter table public.openalex_search_jobs
            add column requested_by_user_id uuid
            references public.app_users(id) on delete set null;

        update public.refresh_jobs
        set status = 'failed',
            last_error = 'legacy job has no user-owned OpenAlex credential',
            finished_at = now(),
            locked_at = null,
            updated_at = now()
        where status in ('pending', 'running');

        update public.openalex_search_jobs
        set status = 'failed',
            last_error = 'legacy job has no user-owned OpenAlex credential',
            finished_at = now(),
            locked_at = null,
            updated_at = now()
        where status in ('pending', 'running');

        create index refresh_jobs_requester_idx
            on public.refresh_jobs (requested_by_user_id, status);
        create index openalex_search_jobs_requester_idx
            on public.openalex_search_jobs (requested_by_user_id, status);

        revoke all on public.user_api_credentials from public;
        do $$
        begin
            if exists (select 1 from pg_roles where rolname = 'scholar_app') then
                grant select, insert, update, delete
                    on public.user_api_credentials to scholar_app;
            end if;
        end $$;
    """)


def downgrade() -> None:
    op.execute("""
        drop index if exists public.openalex_search_jobs_requester_idx;
        drop index if exists public.refresh_jobs_requester_idx;
        alter table public.openalex_search_jobs
            drop column if exists requested_by_user_id;
        alter table public.refresh_jobs
            drop column if exists requested_by_user_id;
        drop table if exists public.user_api_credentials;
    """)
