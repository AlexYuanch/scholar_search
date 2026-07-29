"""Add user preferences and durable initial profile jobs.

Revision ID: 20260730_0010
Revises: 20260728_0009
"""
from alembic import op


revision = "20260730_0010"
down_revision = "20260728_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        alter table public.app_users
            add column display_name text,
            add column avatar_key text not null default 'initials',
            add column theme text not null default 'default',
            add constraint app_users_display_name_length
                check (display_name is null or char_length(display_name) between 1 and 40),
            add constraint app_users_avatar_key_check
                check (avatar_key in ('initials', 'sage', 'ocean', 'sunset', 'plum', 'gold')),
            add constraint app_users_theme_check
                check (theme in ('default', 'green', 'purple', 'orange'));

        update public.app_users
        set display_name = username
        where display_name is null;

        alter table public.app_users
            alter column display_name set not null;

        alter table public.refresh_jobs
            add column query_name text not null default '',
            add column author_ids jsonb not null default '[]'::jsonb,
            add constraint refresh_jobs_author_ids_array
                check (jsonb_typeof(author_ids) = 'array');
    """)


def downgrade() -> None:
    op.execute("""
        alter table public.refresh_jobs
            drop constraint if exists refresh_jobs_author_ids_array,
            drop column if exists author_ids,
            drop column if exists query_name;

        alter table public.app_users
            drop constraint if exists app_users_theme_check,
            drop constraint if exists app_users_avatar_key_check,
            drop constraint if exists app_users_display_name_length,
            drop column if exists theme,
            drop column if exists avatar_key,
            drop column if exists display_name;
    """)
