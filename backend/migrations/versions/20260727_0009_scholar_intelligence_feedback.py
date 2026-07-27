"""Store user-owned feedback for deterministic scholar intelligence.

Revision ID: 20260727_0009
Revises: 20260725_0008
"""
from alembic import op


revision = "20260727_0009"
down_revision = "20260725_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        create table public.scholar_intelligence_feedback (
            id uuid primary key default gen_random_uuid(),
            user_id uuid not null
                references public.app_users(id) on delete cascade,
            target_author_id text not null,
            candidate_author_id text not null default '',
            analysis_key text not null,
            verdict text not null
                check (verdict in ('helpful', 'inaccurate')),
            analysis_version text not null,
            context jsonb not null default '{}'::jsonb,
            created_at timestamptz not null default now(),
            updated_at timestamptz not null default now(),
            unique (
                user_id, target_author_id, candidate_author_id,
                analysis_key, analysis_version
            )
        );

        create index scholar_intelligence_feedback_user_updated_idx
            on public.scholar_intelligence_feedback (user_id, updated_at desc);

        revoke all on public.scholar_intelligence_feedback from public;

        do $$
        begin
            if exists (select 1 from pg_roles where rolname = 'scholar_app') then
                grant select, insert, update, delete
                on public.scholar_intelligence_feedback
                to scholar_app;
            end if;
        end $$;
    """)


def downgrade() -> None:
    op.execute("""
        drop table if exists public.scholar_intelligence_feedback;
    """)
