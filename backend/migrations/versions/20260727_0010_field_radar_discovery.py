"""Add progressive field-radar discovery over the dynamic research graph.

Revision ID: 20260727_0010
Revises: 20260727_0009
"""
from alembic import op


revision = "20260727_0010"
down_revision = "20260727_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        create table public.field_discovery_state (
            focus_scholar_id uuid primary key
                references public.scholars(id) on delete cascade,
            requested_by_user_id uuid
                references public.app_users(id) on delete set null,
            status text not null default 'never' check (
                status in (
                    'never', 'queued', 'discovering', 'enriching',
                    'ready', 'partial', 'failed'
                )
            ),
            selected_topics jsonb not null default '[]'::jsonb,
            discovered_count integer not null default 0
                check (discovered_count >= 0),
            analyzed_count integer not null default 0
                check (analyzed_count >= 0),
            attempted_count integer not null default 0
                check (attempted_count >= 0),
            target_count integer not null default 0
                check (target_count >= 0),
            last_attempted_at timestamptz,
            last_success_at timestamptz,
            next_refresh_at timestamptz,
            retry_after_at timestamptz,
            last_error text,
            version bigint not null default 0 check (version >= 0),
            created_at timestamptz not null default now(),
            updated_at timestamptz not null default now()
        );

        create table public.field_discovery_candidates (
            focus_scholar_id uuid not null
                references public.scholars(id) on delete cascade,
            candidate_scholar_id uuid not null
                references public.scholars(id) on delete cascade,
            discovery_rank integer not null check (discovery_rank > 0),
            discovery_score numeric(12,3) not null default 0
                check (discovery_score >= 0),
            historical_works integer not null default 0
                check (historical_works >= 0),
            recent_works integer not null default 0
                check (recent_works >= 0),
            topic_source_ids text[] not null default '{}',
            source text not null default 'openalex_grouping',
            discovered_at timestamptz not null default now(),
            updated_at timestamptz not null default now(),
            primary key (focus_scholar_id, candidate_scholar_id),
            check (focus_scholar_id <> candidate_scholar_id)
        );

        create table public.field_discovery_institutions (
            focus_scholar_id uuid not null
                references public.scholars(id) on delete cascade,
            institution_id uuid not null
                references public.institutions(id) on delete cascade,
            discovery_rank integer not null check (discovery_rank > 0),
            historical_works integer not null default 0
                check (historical_works >= 0),
            recent_works integer not null default 0
                check (recent_works >= 0),
            topic_source_ids text[] not null default '{}',
            source text not null default 'openalex_grouping',
            discovered_at timestamptz not null default now(),
            updated_at timestamptz not null default now(),
            primary key (focus_scholar_id, institution_id)
        );

        create table public.field_discovery_jobs (
            id uuid primary key default gen_random_uuid(),
            focus_scholar_id uuid not null
                references public.scholars(id) on delete cascade,
            requested_by_user_id uuid
                references public.app_users(id) on delete set null,
            reason text not null,
            force_refresh boolean not null default false,
            status text not null default 'pending' check (
                status in ('pending', 'running', 'succeeded', 'failed')
            ),
            attempts integer not null default 0 check (attempts >= 0),
            scheduled_at timestamptz not null default now(),
            started_at timestamptz,
            locked_at timestamptz,
            finished_at timestamptz,
            last_error text,
            created_at timestamptz not null default now(),
            updated_at timestamptz not null default now()
        );

        create unique index field_discovery_one_active_per_focus
            on public.field_discovery_jobs (focus_scholar_id)
            where status in ('pending', 'running');
        create index field_discovery_jobs_claim_idx
            on public.field_discovery_jobs (status, scheduled_at)
            where status = 'pending';
        create index field_discovery_candidates_rank_idx
            on public.field_discovery_candidates (
                focus_scholar_id, discovery_rank
            );
        create index field_discovery_candidates_reverse_idx
            on public.field_discovery_candidates (candidate_scholar_id);
        create index field_discovery_institutions_rank_idx
            on public.field_discovery_institutions (
                focus_scholar_id, discovery_rank
            );

        revoke all on public.field_discovery_state from public;
        revoke all on public.field_discovery_candidates from public;
        revoke all on public.field_discovery_institutions from public;
        revoke all on public.field_discovery_jobs from public;

        do $$
        begin
            if exists (select 1 from pg_roles where rolname = 'scholar_app') then
                grant select, insert, update, delete on
                    public.field_discovery_state,
                    public.field_discovery_candidates,
                    public.field_discovery_institutions,
                    public.field_discovery_jobs
                to scholar_app;
            end if;
        end $$;
    """)


def downgrade() -> None:
    op.execute("""
        drop table if exists public.field_discovery_jobs;
        drop table if exists public.field_discovery_institutions;
        drop table if exists public.field_discovery_candidates;
        drop table if exists public.field_discovery_state;
    """)
