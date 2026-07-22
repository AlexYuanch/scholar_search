"""Track profile changes for favorite scholars.

Revision ID: 20260722_0005
Revises: 20260722_0004
"""
from alembic import op


revision = "20260722_0005"
down_revision = "20260722_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        alter table public.favorites
            add column last_seen_profile_version integer not null default 0,
            add column last_seen_total_papers integer not null default 0,
            add column last_seen_total_citations bigint not null default 0,
            add column last_seen_at timestamptz;

        update public.favorites f
        set last_seen_profile_version = coalesce(ps.version, 0),
            last_seen_total_papers = coalesce((p.payload ->> 'totalPapers')::integer, 0),
            last_seen_total_citations = coalesce((p.payload ->> 'totalCitations')::bigint, 0),
            last_seen_at = coalesce(p.generated_at, f.created_at)
        from public.scholars s
        left join public.profile_status ps on ps.scholar_id = s.id
        left join public.scholar_profiles p on p.scholar_id = s.id
        where f.scholar_id = s.id;

        alter table public.favorites
            add constraint favorites_seen_version_nonnegative
                check (last_seen_profile_version >= 0),
            add constraint favorites_seen_papers_nonnegative
                check (last_seen_total_papers >= 0),
            add constraint favorites_seen_citations_nonnegative
                check (last_seen_total_citations >= 0);
    """)


def downgrade() -> None:
    op.execute("""
        alter table public.favorites
            drop constraint if exists favorites_seen_citations_nonnegative,
            drop constraint if exists favorites_seen_papers_nonnegative,
            drop constraint if exists favorites_seen_version_nonnegative,
            drop column if exists last_seen_at,
            drop column if exists last_seen_total_citations,
            drop column if exists last_seen_total_papers,
            drop column if exists last_seen_profile_version;
    """)
