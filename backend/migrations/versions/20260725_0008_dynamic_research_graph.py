"""Add the incremental dynamic research graph.

Revision ID: 20260725_0008
Revises: 20260724_0007
"""
from alembic import op


revision = "20260725_0008"
down_revision = "20260724_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(r"""
        alter table public.works
            add column abstract text,
            add column publication_date date,
            add column venue text,
            add column work_type text,
            add column language text,
            add column source_updated_at timestamptz,
            add column last_synced_at timestamptz,
            add column metadata_sources jsonb not null default '[]'::jsonb,
            add column confidence numeric(4,3) not null default 0.900
                check (confidence between 0 and 1);

        alter table public.authorships
            add column source text not null default 'openalex',
            add column confidence numeric(4,3) not null default 0.950
                check (confidence between 0 and 1),
            add column updated_at timestamptz not null default now();

        alter table public.scholar_institutions
            add column start_year integer,
            add column end_year integer,
            add column years integer[] not null default '{}',
            add column is_current boolean not null default false,
            add column source text not null default 'openalex',
            add column confidence numeric(4,3) not null default 0.850
                check (confidence between 0 and 1),
            add column source_records jsonb not null default '[]'::jsonb,
            add column updated_at timestamptz not null default now(),
            add constraint scholar_institutions_year_order
                check (start_year is null or end_year is null or start_year <= end_year);

        create table public.work_external_ids (
            work_id uuid not null references public.works(id) on delete cascade,
            identifier_type text not null check (identifier_type in ('openalex', 'doi', 'crossref')),
            identifier_value text not null,
            source text not null,
            created_at timestamptz not null default now(),
            updated_at timestamptz not null default now(),
            primary key (identifier_type, identifier_value)
        );

        insert into public.work_external_ids (
            work_id, identifier_type, identifier_value, source
        )
        select id, 'openalex', source_work_id, source
        from public.works
        where source = 'openalex' and btrim(source_work_id) <> ''
        on conflict do nothing;

        insert into public.work_external_ids (
            work_id, identifier_type, identifier_value, source
        )
        select id,
               'doi',
               lower(regexp_replace(
                   regexp_replace(btrim(doi), '^https?://(dx\.)?doi\.org/', '', 'i'),
                   '^doi:\s*', '', 'i'
               )),
               source
        from public.works
        where doi is not null and btrim(doi) <> ''
        on conflict do nothing;

        create table public.research_topics (
            id uuid primary key default gen_random_uuid(),
            source text not null,
            source_topic_id text not null,
            display_name text not null,
            normalized_name text not null,
            description text,
            raw_json jsonb not null default '{}'::jsonb,
            created_at timestamptz not null default now(),
            updated_at timestamptz not null default now(),
            unique (source, source_topic_id),
            unique (normalized_name)
        );

        create table public.work_topics (
            work_id uuid not null references public.works(id) on delete cascade,
            topic_id uuid not null references public.research_topics(id) on delete cascade,
            score numeric(6,5),
            is_primary boolean not null default false,
            source text not null,
            confidence numeric(4,3) not null default 0.850
                check (confidence between 0 and 1),
            created_at timestamptz not null default now(),
            updated_at timestamptz not null default now(),
            primary key (work_id, topic_id)
        );

        create table public.scholar_topics (
            scholar_id uuid not null references public.scholars(id) on delete cascade,
            topic_id uuid not null references public.research_topics(id) on delete cascade,
            first_year integer,
            last_year integer,
            works_count integer not null default 0 check (works_count >= 0),
            source text not null,
            confidence numeric(4,3) not null default 0.850
                check (confidence between 0 and 1),
            created_at timestamptz not null default now(),
            updated_at timestamptz not null default now(),
            primary key (scholar_id, topic_id),
            check (first_year is null or last_year is null or first_year <= last_year)
        );

        create table public.collaborations (
            scholar_a_id uuid not null references public.scholars(id) on delete cascade,
            scholar_b_id uuid not null references public.scholars(id) on delete cascade,
            first_year integer,
            last_year integer,
            works_count integer not null default 0 check (works_count >= 0),
            source text not null,
            confidence numeric(4,3) not null default 0.900
                check (confidence between 0 and 1),
            created_at timestamptz not null default now(),
            updated_at timestamptz not null default now(),
            primary key (scholar_a_id, scholar_b_id),
            check (scholar_a_id < scholar_b_id),
            check (first_year is null or last_year is null or first_year <= last_year)
        );

        create table public.collaboration_works (
            scholar_a_id uuid not null,
            scholar_b_id uuid not null,
            work_id uuid not null references public.works(id) on delete cascade,
            source text not null,
            confidence numeric(4,3) not null default 0.900
                check (confidence between 0 and 1),
            created_at timestamptz not null default now(),
            primary key (scholar_a_id, scholar_b_id, work_id),
            foreign key (scholar_a_id, scholar_b_id)
                references public.collaborations(scholar_a_id, scholar_b_id)
                on delete cascade
        );

        create table public.work_citations (
            citing_work_id uuid not null references public.works(id) on delete cascade,
            cited_work_id uuid references public.works(id) on delete set null,
            cited_source_work_id text not null,
            source text not null,
            confidence numeric(4,3) not null default 0.950
                check (confidence between 0 and 1),
            created_at timestamptz not null default now(),
            updated_at timestamptz not null default now(),
            primary key (citing_work_id, cited_source_work_id),
            check (cited_work_id is null or cited_work_id <> citing_work_id)
        );

        create table public.paper_insights (
            work_id uuid primary key references public.works(id) on delete cascade,
            problem text,
            core_method text,
            main_contribution text,
            topic_relationship text,
            abstract_evidence jsonb not null default '[]'::jsonb,
            based_on_abstract boolean not null,
            analyzer_version text not null,
            source text not null,
            confidence numeric(4,3) not null default 0.700
                check (confidence between 0 and 1),
            created_at timestamptz not null default now(),
            updated_at timestamptz not null default now(),
            check (
                based_on_abstract
                or (
                    problem is null
                    and core_method is null
                    and main_contribution is null
                    and topic_relationship is null
                    and abstract_evidence = '[]'::jsonb
                )
            )
        );

        create table public.timeline_events (
            id uuid primary key default gen_random_uuid(),
            scholar_id uuid not null references public.scholars(id) on delete cascade,
            event_key text not null,
            event_type text not null check (
                event_type in (
                    'paper_published', 'topic_started', 'collaboration_started',
                    'institution_started', 'institution_ended'
                )
            ),
            event_year integer,
            event_date date,
            title text not null,
            description text not null default '',
            work_id uuid references public.works(id) on delete cascade,
            topic_id uuid references public.research_topics(id) on delete cascade,
            institution_id uuid references public.institutions(id) on delete cascade,
            collaborator_id uuid references public.scholars(id) on delete cascade,
            source text not null,
            confidence numeric(4,3) not null default 0.850
                check (confidence between 0 and 1),
            created_at timestamptz not null default now(),
            updated_at timestamptz not null default now(),
            unique (scholar_id, event_key)
        );

        create table public.research_graph_sync_state (
            scholar_id uuid primary key references public.scholars(id) on delete cascade,
            status text not null default 'never' check (
                status in ('never', 'queued', 'updating', 'ready', 'failed')
            ),
            last_attempted_at timestamptz,
            last_success_at timestamptz,
            source_watermark timestamptz,
            data_fingerprint text,
            last_error text,
            warnings jsonb not null default '[]'::jsonb,
            version bigint not null default 0 check (version >= 0),
            updated_at timestamptz not null default now()
        );

        create table public.research_graph_refresh_jobs (
            id uuid primary key default gen_random_uuid(),
            scholar_id uuid not null references public.scholars(id) on delete cascade,
            requested_by_user_id uuid references public.app_users(id) on delete set null,
            reason text not null,
            force_rebuild boolean not null default false,
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

        create unique index research_graph_one_active_per_scholar
            on public.research_graph_refresh_jobs (scholar_id)
            where status in ('pending', 'running');
        create index work_external_ids_work_idx
            on public.work_external_ids (work_id);
        create index work_topics_topic_idx
            on public.work_topics (topic_id, work_id);
        create index scholar_topics_recent_idx
            on public.scholar_topics (scholar_id, last_year desc nulls last);
        create index collaborations_a_recent_idx
            on public.collaborations (scholar_a_id, last_year desc nulls last);
        create index collaborations_b_recent_idx
            on public.collaborations (scholar_b_id, last_year desc nulls last);
        create index work_citations_cited_idx
            on public.work_citations (cited_work_id)
            where cited_work_id is not null;
        create index timeline_events_scholar_time_idx
            on public.timeline_events (
                scholar_id, event_year desc nulls last, event_date desc nulls last, id
            );
        create index research_graph_jobs_claim_idx
            on public.research_graph_refresh_jobs (status, scheduled_at)
            where status = 'pending';

        revoke all on public.work_external_ids from public;
        revoke all on public.research_topics from public;
        revoke all on public.work_topics from public;
        revoke all on public.scholar_topics from public;
        revoke all on public.collaborations from public;
        revoke all on public.collaboration_works from public;
        revoke all on public.work_citations from public;
        revoke all on public.paper_insights from public;
        revoke all on public.timeline_events from public;
        revoke all on public.research_graph_sync_state from public;
        revoke all on public.research_graph_refresh_jobs from public;

        do $$
        begin
            if exists (select 1 from pg_roles where rolname = 'scholar_app') then
                grant select, insert, update, delete on
                    public.work_external_ids,
                    public.research_topics,
                    public.work_topics,
                    public.scholar_topics,
                    public.collaborations,
                    public.collaboration_works,
                    public.work_citations,
                    public.paper_insights,
                    public.timeline_events,
                    public.research_graph_sync_state,
                    public.research_graph_refresh_jobs
                to scholar_app;
            end if;
        end $$;
    """)


def downgrade() -> None:
    op.execute("""
        drop table if exists public.research_graph_refresh_jobs;
        drop table if exists public.research_graph_sync_state;
        drop table if exists public.timeline_events;
        drop table if exists public.paper_insights;
        drop table if exists public.work_citations;
        drop table if exists public.collaboration_works;
        drop table if exists public.collaborations;
        drop table if exists public.scholar_topics;
        drop table if exists public.work_topics;
        drop table if exists public.research_topics;
        drop table if exists public.work_external_ids;

        alter table public.scholar_institutions
            drop constraint if exists scholar_institutions_year_order,
            drop column if exists updated_at,
            drop column if exists source_records,
            drop column if exists confidence,
            drop column if exists source,
            drop column if exists is_current,
            drop column if exists years,
            drop column if exists end_year,
            drop column if exists start_year;

        alter table public.authorships
            drop column if exists updated_at,
            drop column if exists confidence,
            drop column if exists source;

        alter table public.works
            drop column if exists confidence,
            drop column if exists metadata_sources,
            drop column if exists last_synced_at,
            drop column if exists source_updated_at,
            drop column if exists language,
            drop column if exists work_type,
            drop column if exists venue,
            drop column if exists publication_date,
            drop column if exists abstract;
    """)
