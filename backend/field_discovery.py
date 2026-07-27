"""Progressive field discovery feeding the existing dynamic research graph.

OpenAlex groupings choose a bounded set of authors and institutions to inspect.
They never become recommendation scores. Candidate authors must complete the
stage-2 research graph before deterministic scholar intelligence can use them.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from typing import Any
from uuid import uuid4

from sqlalchemy import text

from intelligence_repository import load_intelligence_dataset
from openalex import OpenAlexError, count_works, group_works
from research_graph_repository import (
    enqueue_research_graph_refresh,
    get_research_graph_sync_state,
)


MAX_DISCOVERED_CANDIDATES = 60
MAX_ANALYZED_CANDIDATES = 20
INITIAL_GRAPH_BATCH = 8
FOLLOWUP_GRAPH_BATCH = 4
TARGET_RESULTS_PER_CATEGORY = 3
DISCOVERY_MAX_AGE_DAYS = 7
MAX_AUTHOR_TOPIC_WORKS = 600


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: Any = None) -> str:
    if isinstance(value, str):
        return value
    return (value or _now()).isoformat()


def _is_postgres(repository) -> bool:
    return hasattr(repository, "engine")


def _memory_store(repository) -> dict:
    store = getattr(repository, "_field_discovery_store", None)
    if store is None:
        store = {
            "states": {},
            "candidates": {},
            "institutions": {},
            "jobs": {},
        }
        repository._field_discovery_store = store
    return store


def _default_state(author_id: str) -> dict:
    return {
        "author_id": author_id,
        "status": "never",
        "selected_topics": [],
        "discovered_count": 0,
        "analyzed_count": 0,
        "attempted_count": 0,
        "target_count": 0,
        "queued_count": 0,
        "failed_count": 0,
        "last_attempted_at": None,
        "last_success_at": None,
        "next_refresh_at": None,
        "retry_after_at": None,
        "last_error": None,
        "version": 0,
    }


def _openalex_url(kind: str, value: str) -> str:
    identifier = str(value or "").strip().rstrip("/").rsplit("/", 1)[-1]
    if not identifier:
        return ""
    return f"https://openalex.org/{identifier}" if identifier.startswith(kind) else ""


def _topic_source_id(topic: dict) -> str:
    value = topic.get("source_id") or topic.get("id") or ""
    return _openalex_url("T", str(value))


def select_discovery_topics(repository, author_id: str) -> list[dict]:
    """Select up to three sustained and three recent topics from stage 2."""
    dataset = load_intelligence_dataset(repository, author_id)
    scholar = dataset.get("scholars", {}).get(author_id) or {}
    if not scholar.get("graph_ready"):
        return []
    as_of_year = dataset.get("as_of_year")
    recent_start = as_of_year - 3 if as_of_year else None
    stats: dict[str, dict] = {}
    for work_id in scholar.get("work_ids") or []:
        work = dataset.get("works", {}).get(work_id) or {}
        year = work.get("year")
        for topic in work.get("topics") or []:
            source_id = _topic_source_id(topic)
            name = str(topic.get("name") or "").strip()
            if not source_id or not name:
                continue
            row = stats.setdefault(source_id, {
                "source_id": source_id,
                "name": name,
                "works_count": 0,
                "years": set(),
                "recent_works": 0,
            })
            row["works_count"] += 1
            if year:
                row["years"].add(int(year))
            if recent_start is None or (year or 0) >= recent_start:
                row["recent_works"] += 1

    sustained = sorted(
        (
            row for row in stats.values()
            if row["works_count"] >= 2 or len(row["years"]) >= 2
        ),
        key=lambda row: (
            -len(row["years"]),
            -row["works_count"],
            row["source_id"],
        ),
    )[:3]
    recent = sorted(
        (row for row in stats.values() if row["recent_works"] > 0),
        key=lambda row: (
            -row["recent_works"],
            -row["works_count"],
            row["source_id"],
        ),
    )[:3]
    selected = []
    seen = set()
    sustained_ids = {row["source_id"] for row in sustained}
    recent_ids = {row["source_id"] for row in recent}
    for row in [*sustained, *recent]:
        if row["source_id"] in seen:
            continue
        seen.add(row["source_id"])
        selected.append({
            "source_id": row["source_id"],
            "name": row["name"],
            "works_count": row["works_count"],
            "active_years": len(row["years"]),
            "recent_works": row["recent_works"],
            "long_term": row["source_id"] in sustained_ids,
            "recent": row["source_id"] in recent_ids,
        })
    return selected


def _merge_groups(
    historical: list[dict],
    recent: list[dict],
    *,
    kind: str,
    excluded_id: str = "",
    limit: int,
) -> list[dict]:
    rows: dict[str, dict] = {}
    for window, groups in (("historical_works", historical), ("recent_works", recent)):
        for group in groups:
            source_id = _openalex_url(kind, group.get("key") or "")
            if not source_id or source_id == excluded_id:
                continue
            row = rows.setdefault(source_id, {
                "source_id": source_id,
                "name": group.get("name") or source_id,
                "historical_works": 0,
                "recent_works": 0,
            })
            row[window] = max(row[window], int(group.get("count") or 0))
            if group.get("name"):
                row["name"] = group["name"]
    ranked = sorted(
        (
            row for row in rows.values()
            if kind != "A" or row["historical_works"] <= MAX_AUTHOR_TOPIC_WORKS
        ),
        key=lambda row: (
            -(row["historical_works"] + 2 * row["recent_works"]),
            -row["recent_works"],
            -row["historical_works"],
            row["source_id"],
        ),
    )[:limit]
    return [
        {
            **row,
            "rank": index,
            "score": row["historical_works"] + 2 * row["recent_works"],
        }
        for index, row in enumerate(ranked, 1)
    ]


def discover_field_candidates(
    repository,
    author_id: str,
    *,
    api_key: str,
    budget_provider: str,
) -> dict:
    topics = select_discovery_topics(repository, author_id)
    if not topics:
        raise ValueError("The focus graph has no reliable OpenAlex topics")
    topic_ids = [row["source_id"] for row in topics]
    dataset = load_intelligence_dataset(repository, author_id)
    as_of_year = dataset.get("as_of_year") or _now().year
    published_since = f"{int(as_of_year) - 3}-01-01"

    author_historical = group_works(
        topic_ids=topic_ids,
        group_by="authorships.author.id",
        published_since=None,
        api_key=api_key,
        budget_provider=budget_provider,
    )
    author_recent = group_works(
        topic_ids=topic_ids,
        group_by="authorships.author.id",
        published_since=published_since,
        api_key=api_key,
        budget_provider=budget_provider,
    )
    institution_historical = group_works(
        topic_ids=topic_ids,
        group_by="authorships.institutions.id",
        published_since=None,
        api_key=api_key,
        budget_provider=budget_provider,
    )
    institution_recent = group_works(
        topic_ids=topic_ids,
        group_by="authorships.institutions.id",
        published_since=published_since,
        api_key=api_key,
        budget_provider=budget_provider,
    )
    institutions = _merge_groups(
        institution_historical,
        institution_recent,
        kind="I",
        limit=60,
    )
    focus = dataset.get("scholars", {}).get(author_id) or {}
    focus_affiliation = (focus.get("affiliations") or [{}])[0]
    focus_institution_id = focus_affiliation.get("source_id")
    focus_institution = next(
        (
            institution
            for institution in institutions
            if institution["source_id"] == focus_institution_id
        ),
        None,
    )
    if focus_institution:
        focus_institution["name"] = (
            focus_affiliation.get("name")
            or focus_institution["name"]
        )
        focus_institution["country_code"] = focus_affiliation.get("country_code")
    elif focus_institution_id:
        historical_works = count_works(
            topic_ids=topic_ids,
            institution_id=focus_institution_id,
            published_since=None,
            api_key=api_key,
            budget_provider=budget_provider,
        )
        recent_works = count_works(
            topic_ids=topic_ids,
            institution_id=focus_institution_id,
            published_since=published_since,
            api_key=api_key,
            budget_provider=budget_provider,
        )
        institutions.append({
            "source_id": focus_institution_id,
            "name": focus_affiliation.get("name") or focus_institution_id,
            "country_code": focus_affiliation.get("country_code"),
            "historical_works": historical_works,
            "recent_works": recent_works,
            "rank": len(institutions) + 1,
            "score": historical_works + 2 * recent_works,
        })
    return {
        "topics": topics,
        "recent_window": {
            "start_year": int(as_of_year) - 3,
            "end_year": int(as_of_year),
        },
        "candidates": _merge_groups(
            author_historical,
            author_recent,
            kind="A",
            excluded_id=author_id,
            limit=MAX_DISCOVERED_CANDIDATES,
        ),
        "institutions": institutions,
    }


def get_field_discovery_state(repository, author_id: str) -> dict:
    if not _is_postgres(repository):
        state = deepcopy(
            _memory_store(repository)["states"].get(author_id)
            or _default_state(author_id)
        )
        return _with_live_counts(repository, state)
    with repository.engine.connect() as conn:
        row = conn.execute(text("""
            select s.source_author_id as author_id, fds.*
            from public.scholars s
            left join public.field_discovery_state fds
                on fds.focus_scholar_id = s.id
            where s.source = 'openalex' and s.source_author_id = :author_id
        """), {"author_id": author_id}).mappings().first()
    if not row or row["status"] is None:
        return _default_state(author_id)
    state = dict(row)
    state.pop("focus_scholar_id", None)
    state.pop("requested_by_user_id", None)
    for key, value in list(state.items()):
        if hasattr(value, "isoformat"):
            state[key] = value.isoformat()
    return _with_live_counts(repository, state)


def field_discovery_needs_refresh(
    repository,
    author_id: str,
    max_age_days: int = DISCOVERY_MAX_AGE_DAYS,
) -> bool:
    state = get_field_discovery_state(repository, author_id)
    if state["status"] in {"queued", "discovering", "enriching"}:
        return False
    if state["status"] == "failed":
        retry_after = state.get("retry_after_at")
        if retry_after:
            try:
                parsed = datetime.fromisoformat(str(retry_after).replace("Z", "+00:00"))
                if parsed > _now():
                    return False
            except ValueError:
                pass
    if not state.get("last_success_at"):
        return True
    try:
        updated = datetime.fromisoformat(
            str(state["last_success_at"]).replace("Z", "+00:00")
        )
    except ValueError:
        return True
    if updated.tzinfo is None:
        updated = updated.replace(tzinfo=timezone.utc)
    return _now() - updated > timedelta(days=max_age_days)


def enqueue_field_discovery(
    repository,
    author_id: str,
    *,
    requested_by_user_id: str,
    reason: str,
    force_refresh: bool = False,
) -> str:
    if not _is_postgres(repository):
        store = _memory_store(repository)
        if hasattr(repository, "_scholar"):
            repository._scholar(author_id)
        for job in store["jobs"].values():
            if job["author_id"] == author_id and job["status"] in {"pending", "running"}:
                job["force_refresh"] = bool(job["force_refresh"] or force_refresh)
                return job["id"]
        job_id = str(uuid4())
        store["jobs"][job_id] = {
            "id": job_id,
            "author_id": author_id,
            "requested_by_user_id": requested_by_user_id,
            "reason": reason,
            "force_refresh": force_refresh,
            "status": "pending",
            "attempts": 0,
            "scheduled_at": _iso(),
        }
        previous = store["states"].get(author_id) or _default_state(author_id)
        previous.update({
            "status": "queued",
            "requested_by_user_id": requested_by_user_id,
            "last_error": None,
            "retry_after_at": None,
            "updated_at": _iso(),
        })
        store["states"][author_id] = previous
        return job_id

    with repository.engine.begin() as conn:
        scholar_id = conn.execute(text("""
            select id from public.scholars
            where source = 'openalex' and source_author_id = :author_id
        """), {"author_id": author_id}).scalar_one_or_none()
        if not scholar_id:
            raise KeyError("scholar not found")
        job_id = conn.execute(text("""
            insert into public.field_discovery_jobs (
                focus_scholar_id, requested_by_user_id, reason,
                force_refresh, status, scheduled_at
            ) values (
                :scholar_id, cast(:user_id as uuid), :reason,
                :force_refresh, 'pending', now()
            )
            on conflict do nothing
            returning id
        """), {
            "scholar_id": scholar_id,
            "user_id": requested_by_user_id,
            "reason": reason,
            "force_refresh": force_refresh,
        }).scalar_one_or_none()
        if not job_id:
            job_id = conn.execute(text("""
                update public.field_discovery_jobs
                set force_refresh = force_refresh or :force_refresh,
                    requested_by_user_id = coalesce(
                        requested_by_user_id, cast(:user_id as uuid)
                    ),
                    updated_at = now()
                where focus_scholar_id = :scholar_id
                  and status in ('pending', 'running')
                returning id
            """), {
                "scholar_id": scholar_id,
                "user_id": requested_by_user_id,
                "force_refresh": force_refresh,
            }).scalar_one()
        conn.execute(text("""
            insert into public.field_discovery_state (
                focus_scholar_id, requested_by_user_id, status,
                last_error, retry_after_at, updated_at
            ) values (
                :scholar_id, cast(:user_id as uuid), 'queued',
                null, null, now()
            )
            on conflict (focus_scholar_id) do update set
                requested_by_user_id = excluded.requested_by_user_id,
                status = case
                    when field_discovery_state.status = 'discovering'
                    then 'discovering' else 'queued' end,
                last_error = null,
                retry_after_at = null,
                updated_at = now()
        """), {"scholar_id": scholar_id, "user_id": requested_by_user_id})
    return str(job_id)


def claim_field_discovery(repository) -> dict | None:
    if not _is_postgres(repository):
        store = _memory_store(repository)
        pending = [job for job in store["jobs"].values() if job["status"] == "pending"]
        if not pending:
            return None
        job = sorted(pending, key=lambda item: item["scheduled_at"])[0]
        job.update({
            "status": "running",
            "attempts": int(job.get("attempts") or 0) + 1,
            "started_at": _iso(),
        })
        state = store["states"].setdefault(job["author_id"], _default_state(job["author_id"]))
        state.update({
            "status": "discovering",
            "last_attempted_at": _iso(),
            "updated_at": _iso(),
        })
        return deepcopy(job)

    with repository.engine.begin() as conn:
        row = conn.execute(text("""
            with candidate as (
                select id
                from public.field_discovery_jobs
                where status = 'pending' and scheduled_at <= now()
                order by scheduled_at, created_at
                for update skip locked
                limit 1
            )
            update public.field_discovery_jobs j
            set status = 'running',
                attempts = attempts + 1,
                started_at = now(),
                locked_at = now(),
                updated_at = now()
            from candidate c, public.scholars s
            where j.id = c.id
              and s.id = j.focus_scholar_id
            returning j.id, s.source_author_id as author_id,
                      j.requested_by_user_id, j.reason, j.force_refresh,
                      j.attempts, j.status
        """)).mappings().first()
        if row:
            conn.execute(text("""
                update public.field_discovery_state
                set status = 'discovering',
                    last_attempted_at = now(),
                    updated_at = now()
                where focus_scholar_id = (
                    select focus_scholar_id
                    from public.field_discovery_jobs
                    where id = :job_id
                )
            """), {"job_id": row["id"]})
    return dict(row) if row else None


def defer_field_discovery(repository, job_id: str, seconds: int = 30) -> None:
    if not _is_postgres(repository):
        store = _memory_store(repository)
        job = store["jobs"].get(job_id)
        if not job:
            return
        job.update(status="pending", scheduled_at=_iso(_now() + timedelta(seconds=seconds)))
        store["states"][job["author_id"]]["status"] = "queued"
        return
    with repository.engine.begin() as conn:
        row = conn.execute(text("""
            update public.field_discovery_jobs
            set status = 'pending',
                scheduled_at = now() + make_interval(secs => :seconds),
                locked_at = null,
                updated_at = now()
            where id = cast(:job_id as uuid)
            returning focus_scholar_id
        """), {"job_id": job_id, "seconds": max(1, seconds)}).mappings().first()
        if row:
            conn.execute(text("""
                update public.field_discovery_state
                set status = 'queued', updated_at = now()
                where focus_scholar_id = :scholar_id
            """), {"scholar_id": row["focus_scholar_id"]})


def save_field_discovery(
    repository,
    job_id: str,
    author_id: str,
    result: dict,
) -> None:
    topic_ids = [row["source_id"] for row in result["topics"]]
    if not _is_postgres(repository):
        store = _memory_store(repository)
        for key in [key for key in store["candidates"] if key[0] == author_id]:
            store["candidates"].pop(key)
        for candidate in result["candidates"]:
            candidate_id = candidate["source_id"]
            if hasattr(repository, "_scholar"):
                repository._scholar(candidate_id, candidate["name"])
            store["candidates"][(author_id, candidate_id)] = {
                **deepcopy(candidate),
                "focus_author_id": author_id,
                "topic_source_ids": topic_ids,
            }
        for key in [key for key in store["institutions"] if key[0] == author_id]:
            store["institutions"].pop(key)
        for institution in result["institutions"]:
            store["institutions"][(author_id, institution["source_id"])] = {
                **deepcopy(institution),
                "focus_author_id": author_id,
                "topic_source_ids": topic_ids,
            }
        job = store["jobs"].get(job_id)
        if job:
            job.update(status="succeeded", finished_at=_iso(), updated_at=_iso())
        state = store["states"].setdefault(author_id, _default_state(author_id))
        state.update({
            "status": "enriching" if result["candidates"] else "partial",
            "selected_topics": deepcopy(result["topics"]),
            "discovered_count": len(result["candidates"]),
            "target_count": min(MAX_ANALYZED_CANDIDATES, len(result["candidates"])),
            "last_success_at": _iso(),
            "next_refresh_at": _iso(_now() + timedelta(days=DISCOVERY_MAX_AGE_DAYS)),
            "last_error": None,
            "retry_after_at": None,
            "version": int(state.get("version") or 0) + 1,
            "updated_at": _iso(),
        })
        return

    with repository.engine.begin() as conn:
        focus_id = conn.execute(text("""
            select id from public.scholars
            where source = 'openalex' and source_author_id = :author_id
        """), {"author_id": author_id}).scalar_one()
        candidate_ids = []
        for candidate in result["candidates"]:
            candidate_ids.append(repository._upsert_scholar(conn, {
                "id": candidate["source_id"],
                "display_name": candidate["name"],
            }))
        keep_candidate_ids = [str(value) for value in candidate_ids]
        if keep_candidate_ids:
            conn.execute(text("""
                delete from public.field_discovery_candidates
                where focus_scholar_id = :focus_id
                  and candidate_scholar_id <> all(cast(:keep_ids as uuid[]))
            """), {"focus_id": focus_id, "keep_ids": keep_candidate_ids})
        else:
            conn.execute(text("""
                delete from public.field_discovery_candidates
                where focus_scholar_id = :focus_id
            """), {"focus_id": focus_id})
        for candidate, candidate_id in zip(result["candidates"], candidate_ids):
            conn.execute(text("""
                insert into public.field_discovery_candidates (
                    focus_scholar_id, candidate_scholar_id, discovery_rank,
                    discovery_score, historical_works, recent_works,
                    topic_source_ids, updated_at
                ) values (
                    :focus_id, :candidate_id, :rank, :score,
                    :historical_works, :recent_works,
                    cast(:topic_ids as text[]), now()
                )
                on conflict (focus_scholar_id, candidate_scholar_id) do update set
                    discovery_rank = excluded.discovery_rank,
                    discovery_score = excluded.discovery_score,
                    historical_works = excluded.historical_works,
                    recent_works = excluded.recent_works,
                    topic_source_ids = excluded.topic_source_ids,
                    updated_at = now()
            """), {
                "focus_id": focus_id,
                "candidate_id": candidate_id,
                "rank": candidate["rank"],
                "score": candidate["score"],
                "historical_works": candidate["historical_works"],
                "recent_works": candidate["recent_works"],
                "topic_ids": topic_ids,
            })

        institution_ids = []
        for institution in result["institutions"]:
            institution_ids.append(conn.execute(text("""
                insert into public.institutions (
                    source, source_institution_id, display_name,
                    raw_json, updated_at
                ) values (
                    'openalex', :source_id, :display_name,
                    cast(:raw_json as jsonb), now()
                )
                on conflict (source, source_institution_id) do update set
                    display_name = excluded.display_name,
                    updated_at = now()
                returning id
            """), {
                "source_id": institution["source_id"],
                "display_name": institution["name"],
                "raw_json": json.dumps({
                    "id": institution["source_id"],
                    "display_name": institution["name"],
                    "source": "field_discovery",
                }, ensure_ascii=False),
            }).scalar_one())
        keep_institution_ids = [str(value) for value in institution_ids]
        if keep_institution_ids:
            conn.execute(text("""
                delete from public.field_discovery_institutions
                where focus_scholar_id = :focus_id
                  and institution_id <> all(cast(:keep_ids as uuid[]))
            """), {"focus_id": focus_id, "keep_ids": keep_institution_ids})
        else:
            conn.execute(text("""
                delete from public.field_discovery_institutions
                where focus_scholar_id = :focus_id
            """), {"focus_id": focus_id})
        for institution, institution_id in zip(result["institutions"], institution_ids):
            conn.execute(text("""
                insert into public.field_discovery_institutions (
                    focus_scholar_id, institution_id, discovery_rank,
                    historical_works, recent_works, topic_source_ids,
                    updated_at
                ) values (
                    :focus_id, :institution_id, :rank,
                    :historical_works, :recent_works,
                    cast(:topic_ids as text[]), now()
                )
                on conflict (focus_scholar_id, institution_id) do update set
                    discovery_rank = excluded.discovery_rank,
                    historical_works = excluded.historical_works,
                    recent_works = excluded.recent_works,
                    topic_source_ids = excluded.topic_source_ids,
                    updated_at = now()
            """), {
                "focus_id": focus_id,
                "institution_id": institution_id,
                "rank": institution["rank"],
                "historical_works": institution["historical_works"],
                "recent_works": institution["recent_works"],
                "topic_ids": topic_ids,
            })
        conn.execute(text("""
            update public.field_discovery_jobs
            set status = 'succeeded', finished_at = now(),
                locked_at = null, updated_at = now()
            where id = cast(:job_id as uuid)
        """), {"job_id": job_id})
        conn.execute(text("""
            insert into public.field_discovery_state (
                focus_scholar_id, status, selected_topics,
                discovered_count, target_count, last_success_at,
                next_refresh_at, last_error, retry_after_at,
                version, updated_at
            ) values (
                :focus_id, :status, cast(:topics as jsonb),
                :discovered_count, :target_count, now(),
                now() + interval '7 days', null, null, 1, now()
            )
            on conflict (focus_scholar_id) do update set
                status = excluded.status,
                selected_topics = excluded.selected_topics,
                discovered_count = excluded.discovered_count,
                target_count = excluded.target_count,
                last_success_at = now(),
                next_refresh_at = now() + interval '7 days',
                last_error = null,
                retry_after_at = null,
                version = field_discovery_state.version + 1,
                updated_at = now()
        """), {
            "focus_id": focus_id,
            "status": "enriching" if result["candidates"] else "partial",
            "topics": json.dumps(result["topics"], ensure_ascii=False),
            "discovered_count": len(result["candidates"]),
            "target_count": min(MAX_ANALYZED_CANDIDATES, len(result["candidates"])),
        })


def fail_field_discovery(
    repository,
    job_id: str,
    error: str,
    *,
    retry: bool,
    retry_after_seconds: int | None = None,
) -> None:
    retry_seconds = max(30, int(retry_after_seconds or 60))
    if not _is_postgres(repository):
        store = _memory_store(repository)
        job = store["jobs"].get(job_id)
        if not job:
            return
        job.update({
            "status": "pending" if retry else "failed",
            "scheduled_at": _iso(_now() + timedelta(seconds=retry_seconds)),
            "last_error": error,
            "updated_at": _iso(),
        })
        state = store["states"].setdefault(job["author_id"], _default_state(job["author_id"]))
        state.update({
            "status": "queued" if retry else "failed",
            "last_error": error,
            "retry_after_at": _iso(_now() + timedelta(seconds=retry_seconds)),
            "updated_at": _iso(),
        })
        return
    with repository.engine.begin() as conn:
        row = conn.execute(text("""
            update public.field_discovery_jobs
            set status = case when :retry then 'pending' else 'failed' end,
                scheduled_at = case
                    when :retry
                    then now() + make_interval(secs => :retry_seconds)
                    else scheduled_at
                end,
                finished_at = case when :retry then null else now() end,
                locked_at = null,
                last_error = :error,
                updated_at = now()
            where id = cast(:job_id as uuid)
            returning focus_scholar_id
        """), {
            "job_id": job_id,
            "retry": retry,
            "retry_seconds": retry_seconds,
            "error": error[:4000],
        }).mappings().first()
        if row:
            conn.execute(text("""
                update public.field_discovery_state
                set status = case when :retry then 'queued' else 'failed' end,
                    last_error = :error,
                    retry_after_at = now()
                        + make_interval(secs => :retry_seconds),
                    updated_at = now()
                where focus_scholar_id = :focus_id
            """), {
                "focus_id": row["focus_scholar_id"],
                "retry": retry,
                "retry_seconds": retry_seconds,
                "error": error[:4000],
            })


def get_field_candidate_author_ids(repository, author_id: str) -> list[str]:
    if not _is_postgres(repository):
        return [
            candidate_id
            for (focus_id, candidate_id), _row in sorted(
                _memory_store(repository)["candidates"].items(),
                key=lambda item: item[1]["rank"],
            )
            if focus_id == author_id
        ]
    with repository.engine.connect() as conn:
        rows = conn.execute(text("""
            select candidate.source_author_id
            from public.field_discovery_candidates fdc
            join public.scholars focus on focus.id = fdc.focus_scholar_id
            join public.scholars candidate
                on candidate.id = fdc.candidate_scholar_id
            where focus.source = 'openalex'
              and focus.source_author_id = :author_id
            order by fdc.discovery_rank
        """), {"author_id": author_id}).all()
    return [str(row[0]) for row in rows]


def _candidate_progress(repository, author_id: str) -> list[dict]:
    if not _is_postgres(repository):
        store = _memory_store(repository)
        rows = []
        for (focus_id, candidate_id), candidate in store["candidates"].items():
            if focus_id != author_id:
                continue
            sync = (
                getattr(repository, "_research_graph_store", {})
                .get("sync", {})
                .get(candidate_id, {})
            )
            rows.append({
                "author_id": candidate_id,
                "rank": candidate["rank"],
                "status": sync.get("status") or "never",
                "usable": bool(
                    sync.get("status") == "ready"
                    or sync.get("last_success_at")
                    or int(sync.get("version") or 0) > 0
                ),
            })
        return sorted(rows, key=lambda row: row["rank"])
    with repository.engine.connect() as conn:
        rows = conn.execute(text("""
            select candidate.source_author_id as author_id,
                   fdc.discovery_rank as rank,
                   coalesce(gs.status, 'never') as status,
                   gs.status = 'ready'
                       or coalesce(gs.version, 0) > 0
                       or gs.last_success_at is not null as usable
            from public.field_discovery_candidates fdc
            join public.scholars focus on focus.id = fdc.focus_scholar_id
            join public.scholars candidate
                on candidate.id = fdc.candidate_scholar_id
            left join public.research_graph_sync_state gs
                on gs.scholar_id = candidate.id
            where focus.source = 'openalex'
              and focus.source_author_id = :author_id
            order by fdc.discovery_rank
        """), {"author_id": author_id}).mappings().all()
    return [dict(row) for row in rows]


def _with_live_counts(repository, state: dict) -> dict:
    progress = _candidate_progress(repository, state["author_id"])
    ready = sum(bool(row.get("usable")) for row in progress)
    failed = sum(
        row["status"] == "failed" and not row.get("usable")
        for row in progress
    )
    queued = sum(row["status"] in {"queued", "updating"} for row in progress)
    attempted = sum(
        bool(row.get("usable"))
        or row["status"] in {"failed", "queued", "updating"}
        for row in progress
    )
    state.update({
        "discovered_count": len(progress) or int(state.get("discovered_count") or 0),
        "analyzed_count": ready,
        "attempted_count": attempted,
        "queued_count": queued,
        "failed_count": failed,
        "target_count": min(
            MAX_ANALYZED_CANDIDATES,
            len(progress) or int(state.get("target_count") or 0),
        ),
    })
    return state


def _update_progress_state(repository, author_id: str, values: dict) -> None:
    if not _is_postgres(repository):
        state = _memory_store(repository)["states"].setdefault(
            author_id, _default_state(author_id)
        )
        state.update(deepcopy(values), updated_at=_iso())
        return
    allowed = {
        "status", "analyzed_count", "attempted_count", "target_count",
        "last_error",
    }
    updates = {key: value for key, value in values.items() if key in allowed}
    if not updates:
        return
    assignments = ", ".join(f"{key} = :{key}" for key in updates)
    with repository.engine.begin() as conn:
        conn.execute(text(f"""
            update public.field_discovery_state fds
            set {assignments}, updated_at = now()
            from public.scholars s
            where fds.focus_scholar_id = s.id
              and s.source = 'openalex'
              and s.source_author_id = :author_id
        """), {**updates, "author_id": author_id})


def _requesting_user_id(repository, author_id: str) -> str | None:
    if not _is_postgres(repository):
        return (
            _memory_store(repository)["states"].get(author_id, {})
            .get("requested_by_user_id")
        )
    with repository.engine.connect() as conn:
        value = conn.execute(text("""
            select fds.requested_by_user_id
            from public.field_discovery_state fds
            join public.scholars s on s.id = fds.focus_scholar_id
            where s.source = 'openalex'
              and s.source_author_id = :author_id
        """), {"author_id": author_id}).scalar_one_or_none()
    return str(value) if value else None


def advance_field_discovery(
    repository,
    author_id: str,
    *,
    result_counts: dict[str, int] | None = None,
) -> dict:
    state = get_field_discovery_state(repository, author_id)
    if state["status"] not in {"enriching", "partial", "ready"}:
        return state
    progress = _candidate_progress(repository, author_id)
    ready = sum(bool(row.get("usable")) for row in progress)
    failed = sum(
        row["status"] == "failed" and not row.get("usable")
        for row in progress
    )
    active = sum(row["status"] in {"queued", "updating"} for row in progress)
    attempted = sum(
        bool(row.get("usable"))
        or row["status"] in {"failed", "queued", "updating"}
        for row in progress
    )
    target = min(MAX_ANALYZED_CANDIDATES, len(progress))
    completed_categories = bool(result_counts) and all(
        int(result_counts.get(key) or 0) >= TARGET_RESULTS_PER_CATEGORY
        for key in (
            "north_stars",
            "peers",
            "potential_collaborators",
            "potential_competitors",
        )
    )
    if completed_categories or attempted >= target or not progress:
        final_status = "partial" if failed or ready < target else "ready"
        _update_progress_state(repository, author_id, {
            "status": final_status,
            "analyzed_count": ready,
            "attempted_count": attempted,
            "target_count": target,
        })
        return get_field_discovery_state(repository, author_id)
    if active:
        _update_progress_state(repository, author_id, {
            "status": "enriching",
            "analyzed_count": ready,
            "attempted_count": attempted,
            "target_count": target,
        })
        return get_field_discovery_state(repository, author_id)

    batch_size = INITIAL_GRAPH_BATCH if attempted == 0 else FOLLOWUP_GRAPH_BATCH
    pending = [
        row for row in progress
        if row["status"] == "never" and not row.get("usable")
    ][:min(batch_size, max(0, target - attempted))]
    requester = _requesting_user_id(repository, author_id)
    if not requester:
        _update_progress_state(repository, author_id, {
            "status": "partial",
            "analyzed_count": ready,
            "attempted_count": attempted,
            "target_count": target,
            "last_error": "No requesting user is available for candidate graph enrichment",
        })
        return get_field_discovery_state(repository, author_id)
    queued = 0
    for row in pending:
        try:
            enqueue_research_graph_refresh(
                repository,
                row["author_id"],
                requested_by_user_id=requester,
                reason=f"field_discovery:{author_id}",
            )
            queued += 1
        except KeyError:
            continue
    _update_progress_state(repository, author_id, {
        "status": "enriching" if queued else "partial",
        "analyzed_count": ready,
        "attempted_count": attempted + queued,
        "target_count": target,
        "last_error": None if queued else "No candidate graph could be queued",
    })
    return get_field_discovery_state(repository, author_id)


def advance_discoveries_for_candidate(repository, candidate_author_id: str) -> None:
    if not _is_postgres(repository):
        focus_ids = sorted({
            focus_id
            for (focus_id, candidate_id) in _memory_store(repository)["candidates"]
            if candidate_id == candidate_author_id
        })
    else:
        with repository.engine.connect() as conn:
            rows = conn.execute(text("""
                select focus.source_author_id
                from public.field_discovery_candidates fdc
                join public.scholars focus on focus.id = fdc.focus_scholar_id
                join public.scholars candidate
                    on candidate.id = fdc.candidate_scholar_id
                where candidate.source = 'openalex'
                  and candidate.source_author_id = :candidate_author_id
            """), {"candidate_author_id": candidate_author_id}).all()
        focus_ids = [str(row[0]) for row in rows]
    for focus_id in focus_ids:
        try:
            from scholar_intelligence import build_scholar_intelligence

            result = build_scholar_intelligence(repository, focus_id)
            counts = {
                key: len(rows)
                for key, rows in result["recommendations"].items()
            }
            advance_field_discovery(
                repository,
                focus_id,
                result_counts=counts,
            )
        except Exception:
            continue


def process_claimed_field_discovery(
    repository,
    job: dict,
    *,
    api_key: str,
    budget_provider: str,
) -> bool:
    state = get_research_graph_sync_state(repository, job["author_id"]) or {}
    if state.get("status") != "ready":
        defer_field_discovery(repository, str(job["id"]))
        return False
    try:
        result = discover_field_candidates(
            repository,
            job["author_id"],
            api_key=api_key,
            budget_provider=budget_provider,
        )
        save_field_discovery(repository, str(job["id"]), job["author_id"], result)
        advance_field_discovery(repository, job["author_id"])
        return True
    except OpenAlexError as exc:
        retry_after = None
        try:
            retry_after = int(exc.retry_after) if exc.retry_after else None
        except ValueError:
            retry_after = None
        fail_field_discovery(
            repository,
            str(job["id"]),
            "OpenAlex 暂时无法完成领域样本发现；已保留最近一次成功结果。",
            retry=int(job.get("attempts") or 0) < 3,
            retry_after_seconds=retry_after,
        )
        return False
    except Exception:
        fail_field_discovery(
            repository,
            str(job["id"]),
            "领域样本发现失败；已保留最近一次成功结果。",
            retry=int(job.get("attempts") or 0) < 3,
        )
        return False


def _raw_institutions(repository, author_id: str) -> list[dict]:
    if not _is_postgres(repository):
        return [
            deepcopy(row)
            for (focus_id, _institution_id), row in sorted(
                _memory_store(repository)["institutions"].items(),
                key=lambda item: item[1]["rank"],
            )
            if focus_id == author_id
        ]
    with repository.engine.connect() as conn:
        rows = conn.execute(text("""
            select i.id, i.source_institution_id as source_id,
                   i.display_name as name, i.country_code,
                   fdi.discovery_rank as rank,
                   fdi.historical_works, fdi.recent_works,
                   fdi.topic_source_ids
            from public.field_discovery_institutions fdi
            join public.scholars focus on focus.id = fdi.focus_scholar_id
            join public.institutions i on i.id = fdi.institution_id
            where focus.source = 'openalex'
              and focus.source_author_id = :author_id
            order by fdi.discovery_rank
        """), {"author_id": author_id}).mappings().all()
    return [
        {
            **dict(row),
            "id": str(row["id"]),
            "topic_source_ids": list(row["topic_source_ids"] or []),
        }
        for row in rows
    ]


def build_field_institutions(
    repository,
    author_id: str,
    dataset: dict,
    field_topics: list[dict],
) -> dict:
    raw_rows = _raw_institutions(repository, author_id)
    focus = dataset.get("scholars", {}).get(author_id) or {}
    focus_affiliation = (focus.get("affiliations") or [{}])[0]
    focus_institution_id = focus_affiliation.get("source_id")
    rows = []
    for raw in raw_rows:
        source_id = raw.get("source_id") or ""
        members = []
        collaboration_count = 0
        for candidate_id, scholar in dataset.get("scholars", {}).items():
            if candidate_id == author_id or not scholar.get("graph_ready"):
                continue
            affiliation = (scholar.get("affiliations") or [{}])[0]
            if affiliation.get("source_id") != source_id:
                continue
            members.append(candidate_id)
            collaboration_count += int(
                (focus.get("collaborations", {}).get(candidate_id) or {})
                .get("works_count")
                or 0
            )
        rows.append({
            "institution_id": source_id,
            "name": raw.get("name") or source_id,
            "country_code": raw.get("country_code"),
            "historical_works": int(raw.get("historical_works") or 0),
            "recent_works": int(raw.get("recent_works") or 0),
            "current_collaboration_count": collaboration_count,
            "analyzed_member_count": len(members),
            "topics": [
                {"name": topic["name"]}
                for topic in field_topics[:5]
            ],
            "is_focus_institution": source_id == focus_institution_id,
            "coverage": {
                "source": "openalex_grouping",
                "analyzed_members": len(members),
            },
        })
    ranked_active = sorted(
        rows,
        key=lambda row: (
            -row["recent_works"],
            -row["historical_works"],
            row["institution_id"],
        ),
    )
    active = ranked_active[:8]
    focus_row = next(
        (row for row in ranked_active if row["is_focus_institution"]),
        None,
    )
    if focus_row and focus_row not in active:
        active = [*active[:7], focus_row]
    opportunities = sorted(
        (
            row for row in rows
            if not row["is_focus_institution"]
            and row["recent_works"] > 0
            and row["current_collaboration_count"] <= 1
        ),
        key=lambda row: (
            row["current_collaboration_count"],
            -row["recent_works"],
            -row["analyzed_member_count"],
            row["institution_id"],
        ),
    )[:8]
    return {
        "active": active,
        "opportunities": opportunities,
        "focus_institution_id": focus_institution_id,
        "limitations": [
            {
                "zh": "机构活动量来自所选主题下的论文分组，不表示机构质量或完整产出。",
                "en": "Institution activity comes from works grouped under selected topics; it is not institutional quality or complete output.",
            },
            {
                "zh": "已分析成员仅指当前动态研究图谱覆盖的作者，不代表机构名册。",
                "en": "Analyzed members are authors covered by the current dynamic graph, not an institutional roster.",
            },
        ],
    }


def compare_field_institutions(
    repository,
    focus_author_id: str,
    candidate_institution_id: str,
) -> dict:
    dataset = load_intelligence_dataset(repository, focus_author_id)
    focus = dataset.get("scholars", {}).get(focus_author_id) or {}
    focus_affiliation = (focus.get("affiliations") or [{}])[0]
    focus_institution_id = focus_affiliation.get("source_id")
    topic_counts: Counter[str] = Counter()
    topic_names: dict[str, str] = {}
    for work_id in focus.get("work_ids") or []:
        for topic in (dataset.get("works", {}).get(work_id) or {}).get("topics") or []:
            source_id = topic.get("source_id") or topic.get("id") or topic.get("name")
            topic_counts[str(source_id)] += 1
            topic_names[str(source_id)] = topic.get("name") or str(source_id)
    graph_topics = [
        {"name": topic_names[key], "works_count": count}
        for key, count in topic_counts.most_common(6)
    ]
    discovery = get_field_discovery_state(repository, focus_author_id)
    topics = discovery.get("selected_topics") or graph_topics
    institution_view = build_field_institutions(
        repository,
        focus_author_id,
        dataset,
        topics,
    )
    by_id = {
        row["institution_id"]: row
        for row in [
            *institution_view["active"],
            *institution_view["opportunities"],
        ]
    }
    left = by_id.get(focus_institution_id)
    right = by_id.get(candidate_institution_id)
    if not left or not right:
        return {
            "analysis_version": "deterministic-graph-v1",
            "mode": "institution",
            "status": "insufficient",
            "left": left,
            "right": right,
            "conclusion": {
                "zh": "至少一侧缺少所选主题下的机构活动数据，无法可靠比较。",
                "en": "At least one side lacks institution activity data under the selected topics.",
            },
            "limitations": institution_view["limitations"],
        }
    dimensions = [
        {
            "key": "historical_activity",
            "label": {"zh": "历史主题论文", "en": "Historical topic works"},
            "left": left["historical_works"],
            "right": right["historical_works"],
        },
        {
            "key": "recent_activity",
            "label": {"zh": "近四年主题论文", "en": "Recent topic works"},
            "left": left["recent_works"],
            "right": right["recent_works"],
        },
        {
            "key": "collaboration",
            "label": {"zh": "与当前学者合作论文", "en": "Works with the focus scholar"},
            "left": left["current_collaboration_count"],
            "right": right["current_collaboration_count"],
        },
        {
            "key": "analyzed_members",
            "label": {"zh": "已分析相关作者", "en": "Analyzed related scholars"},
            "left": left["analyzed_member_count"],
            "right": right["analyzed_member_count"],
        },
    ]
    return {
        "analysis_version": "deterministic-graph-v1",
        "mode": "institution",
        "status": "available",
        "left": left,
        "right": right,
        "dimensions": dimensions,
        "conclusion": {
            "zh": "比较仅描述主题活动、时间变化、合作记录和当前已分析成员，不判断机构绝对优劣。",
            "en": "This comparison only describes topic activity, time windows, collaboration records, and currently analyzed scholars; it does not judge absolute institutional superiority.",
        },
        "limitations": institution_view["limitations"],
    }


def maintain_field_discovery_jobs(repository) -> dict:
    if not _is_postgres(repository):
        return {"enqueued": 0, "deleted": 0}
    with repository.engine.begin() as conn:
        conn.execute(text("""
            with expired as (
                update public.field_discovery_jobs
                set status = case when attempts < 3 then 'pending' else 'failed' end,
                    scheduled_at = case
                        when attempts < 3 then now() else scheduled_at
                    end,
                    finished_at = case when attempts < 3 then null else now() end,
                    locked_at = null,
                    last_error = 'worker lease expired',
                    updated_at = now()
                where status = 'running'
                  and locked_at < now() - interval '15 minutes'
                returning focus_scholar_id, status, last_error
            )
            update public.field_discovery_state fds
            set status = case
                    when expired.status = 'pending' then 'queued' else 'failed'
                end,
                last_error = expired.last_error,
                updated_at = now()
            from expired
            where fds.focus_scholar_id = expired.focus_scholar_id
        """))
        enqueued = conn.execute(text("""
            insert into public.field_discovery_jobs (
                focus_scholar_id, requested_by_user_id, reason,
                status, scheduled_at
            )
            select f.scholar_id, f.user_id, 'tracked_weekly',
                   'pending', now()
            from public.favorites f
            join public.research_graph_sync_state gs
                on gs.scholar_id = f.scholar_id
               and gs.status = 'ready'
            left join public.field_discovery_state fds
                on fds.focus_scholar_id = f.scholar_id
            where fds.status is null
               or (
                    fds.status not in ('queued', 'discovering', 'enriching')
                    and (
                        fds.last_success_at is null
                        or fds.last_success_at < now() - interval '7 days'
                    )
               )
            on conflict do nothing
        """)).rowcount
        conn.execute(text("""
            insert into public.field_discovery_state (
                focus_scholar_id, requested_by_user_id, status, updated_at
            )
            select focus_scholar_id, requested_by_user_id, 'queued', now()
            from public.field_discovery_jobs
            where status = 'pending'
            on conflict (focus_scholar_id) do update set
                requested_by_user_id = excluded.requested_by_user_id,
                status = case
                    when field_discovery_state.status = 'discovering'
                    then 'discovering' else 'queued' end,
                updated_at = now()
        """))
        deleted = conn.execute(text("""
            delete from public.field_discovery_jobs
            where status in ('succeeded', 'failed')
              and updated_at < now() - interval '30 days'
        """)).rowcount
    return {"enqueued": enqueued, "deleted": deleted}
