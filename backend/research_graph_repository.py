"""Persistence boundary for dynamic research graph data and refresh jobs."""
from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import text

from crossref import normalize_doi


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: Any = None) -> str:
    if isinstance(value, str):
        return value
    return (value or _now()).isoformat()


def _json(value: Any) -> str:
    import json

    return json.dumps(value, ensure_ascii=False)


def _is_postgres(repository) -> bool:
    return hasattr(repository, "engine")


def _memory_store(repository) -> dict:
    store = getattr(repository, "_research_graph_store", None)
    if store is None:
        store = {
            "authors": {},
            "works": {},
            "external_ids": {},
            "authorships": {},
            "institutions": {},
            "affiliations": {},
            "topics": {},
            "work_topics": {},
            "scholar_topics": {},
            "collaborations": {},
            "collaboration_works": {},
            "citations": {},
            "insights": {},
            "timeline": {},
            "sync": {},
            "jobs": {},
        }
        repository._research_graph_store = store
    return store


def get_research_graph_sync_state(repository, author_id: str) -> dict | None:
    if not _is_postgres(repository):
        return deepcopy(_memory_store(repository)["sync"].get(author_id))
    with repository.engine.connect() as conn:
        row = conn.execute(text("""
            select s.source_author_id as author_id, gs.status, gs.last_attempted_at,
                   gs.last_success_at, gs.source_watermark, gs.data_fingerprint,
                   gs.last_error, gs.warnings, gs.version, gs.updated_at
            from public.scholars s
            left join public.research_graph_sync_state gs on gs.scholar_id = s.id
            where s.source = 'openalex' and s.source_author_id = :author_id
        """), {"author_id": author_id}).mappings().first()
    if not row or row["status"] is None:
        return None
    result = dict(row)
    for key in ("last_attempted_at", "last_success_at", "source_watermark", "updated_at"):
        result[key] = _iso(result[key]) if result.get(key) else None
    return result


def research_graph_needs_refresh(
    repository,
    author_id: str,
    max_age_days: int = 7,
    *,
    state: dict | None = None,
) -> bool:
    if state is None:
        state = get_research_graph_sync_state(repository, author_id)
    if state and state.get("status") in {"queued", "updating", "failed"}:
        return False
    if not state or not state.get("last_success_at"):
        return True
    try:
        updated = datetime.fromisoformat(
            str(state["last_success_at"]).replace("Z", "+00:00")
        )
    except ValueError:
        return True
    if updated.tzinfo is None:
        updated = updated.replace(tzinfo=timezone.utc)
    profile = repository.get_profile(author_id)
    if profile and profile.get("updated_at"):
        try:
            profile_updated = datetime.fromisoformat(
                str(profile["updated_at"]).replace("Z", "+00:00")
            )
        except ValueError:
            profile_updated = None
        if profile_updated:
            if profile_updated.tzinfo is None:
                profile_updated = profile_updated.replace(tzinfo=timezone.utc)
            if profile_updated > updated:
                return True
    return _now() - updated > timedelta(days=max_age_days)


def enqueue_research_graph_refresh(
    repository,
    author_id: str,
    *,
    requested_by_user_id: str | None,
    reason: str,
    force_rebuild: bool = False,
) -> str:
    if not _is_postgres(repository):
        store = _memory_store(repository)
        if hasattr(repository, "_scholar"):
            repository._scholar(author_id)
        for job in store["jobs"].values():
            if job["author_id"] == author_id and job["status"] in {"pending", "running"}:
                job["force_rebuild"] = bool(job["force_rebuild"] or force_rebuild)
                return job["id"]
        job_id = str(uuid4())
        store["jobs"][job_id] = {
            "id": job_id,
            "author_id": author_id,
            "requested_by_user_id": requested_by_user_id,
            "reason": reason,
            "force_rebuild": force_rebuild,
            "status": "pending",
            "attempts": 0,
            "scheduled_at": _iso(),
        }
        state = store["sync"].setdefault(author_id, {"version": 0})
        state.update(status="queued", last_error=None, updated_at=_iso())
        return job_id

    with repository.engine.begin() as conn:
        scholar_id = conn.execute(text("""
            select id from public.scholars
            where source = 'openalex' and source_author_id = :author_id
        """), {"author_id": author_id}).scalar_one_or_none()
        if not scholar_id:
            raise KeyError("scholar not found")
        job_id = conn.execute(text("""
            insert into public.research_graph_refresh_jobs (
                scholar_id, requested_by_user_id, reason, force_rebuild,
                status, scheduled_at
            ) values (
                :scholar_id, cast(:user_id as uuid), :reason, :force_rebuild,
                'pending', now()
            )
            on conflict do nothing
            returning id
        """), {
            "scholar_id": scholar_id,
            "user_id": requested_by_user_id,
            "reason": reason,
            "force_rebuild": force_rebuild,
        }).scalar_one_or_none()
        if not job_id:
            job_id = conn.execute(text("""
                update public.research_graph_refresh_jobs
                set force_rebuild = force_rebuild or :force_rebuild,
                    requested_by_user_id = coalesce(
                        requested_by_user_id, cast(:user_id as uuid)
                    ),
                    updated_at = now()
                where scholar_id = :scholar_id
                  and status in ('pending', 'running')
                returning id
            """), {
                "scholar_id": scholar_id,
                "user_id": requested_by_user_id,
                "force_rebuild": force_rebuild,
            }).scalar_one()
        conn.execute(text("""
            insert into public.research_graph_sync_state (
                scholar_id, status, updated_at
            ) values (:scholar_id, 'queued', now())
            on conflict (scholar_id) do update set
                status = case
                    when research_graph_sync_state.status = 'updating'
                    then 'updating' else 'queued' end,
                last_error = null,
                updated_at = now()
        """), {"scholar_id": scholar_id})
    return str(job_id)


def claim_research_graph_refresh(repository) -> dict | None:
    if not _is_postgres(repository):
        store = _memory_store(repository)
        pending = [job for job in store["jobs"].values() if job["status"] == "pending"]
        if not pending:
            return None
        job = sorted(pending, key=lambda item: item["scheduled_at"])[0]
        job.update(status="running", attempts=job["attempts"] + 1, started_at=_iso())
        state = store["sync"].setdefault(job["author_id"], {"version": 0})
        state.update(status="updating", last_attempted_at=_iso(), updated_at=_iso())
        return deepcopy(job)

    with repository.engine.begin() as conn:
        row = conn.execute(text("""
            with candidate as (
                select id
                from public.research_graph_refresh_jobs
                where status = 'pending' and scheduled_at <= now()
                order by scheduled_at, created_at
                for update skip locked
                limit 1
            )
            update public.research_graph_refresh_jobs j
            set status = 'running',
                attempts = attempts + 1,
                started_at = now(),
                locked_at = now(),
                updated_at = now()
            from candidate c, public.scholars s
            where j.id = c.id
              and s.id = j.scholar_id
            returning j.id, j.scholar_id, s.source_author_id as author_id,
                      j.requested_by_user_id, j.reason, j.force_rebuild,
                      j.attempts, j.status
        """)).mappings().first()
        if row:
            conn.execute(text("""
                insert into public.research_graph_sync_state (
                    scholar_id, status, last_attempted_at, updated_at
                ) values (:scholar_id, 'updating', now(), now())
                on conflict (scholar_id) do update set
                    status = 'updating',
                    last_attempted_at = now(),
                    updated_at = now()
            """), {"scholar_id": row["scholar_id"]})
    return dict(row) if row else None


def complete_research_graph_refresh(repository, job_id: str) -> None:
    if not _is_postgres(repository):
        store = _memory_store(repository)
        store["jobs"][job_id].update(status="succeeded", finished_at=_iso())
        return
    with repository.engine.begin() as conn:
        conn.execute(text("""
            update public.research_graph_refresh_jobs
            set status = 'succeeded', finished_at = now(), locked_at = null,
                updated_at = now()
            where id = cast(:job_id as uuid)
        """), {"job_id": job_id})


def fail_research_graph_refresh(
    repository,
    job_id: str,
    error: str,
    *,
    retry: bool,
) -> None:
    if not _is_postgres(repository):
        store = _memory_store(repository)
        job = store["jobs"][job_id]
        job.update(
            status="pending" if retry else "failed",
            last_error=error,
            scheduled_at=_iso(_now() + timedelta(minutes=2 ** job["attempts"])),
            finished_at=None if retry else _iso(),
        )
        state = store["sync"].setdefault(job["author_id"], {"version": 0})
        state.update(
            status="queued" if retry else "failed",
            last_error=error,
            updated_at=_iso(),
        )
        return
    with repository.engine.begin() as conn:
        row = conn.execute(text("""
            update public.research_graph_refresh_jobs
            set status = case when :retry then 'pending' else 'failed' end,
                scheduled_at = case
                    when :retry then now() + make_interval(mins => power(2, attempts)::int)
                    else scheduled_at
                end,
                finished_at = case when :retry then null else now() end,
                locked_at = null,
                last_error = :error,
                updated_at = now()
            where id = cast(:job_id as uuid)
            returning scholar_id
        """), {
            "job_id": job_id,
            "retry": retry,
            "error": error[:4000],
        }).mappings().first()
        if row:
            conn.execute(text("""
                update public.research_graph_sync_state
                set status = case when :retry then 'queued' else 'failed' end,
                    last_error = :error,
                    updated_at = now()
                where scholar_id = :scholar_id
            """), {
                "scholar_id": row["scholar_id"],
                "retry": retry,
                "error": error[:4000],
            })


def _memory_work_key(store: dict, work: dict) -> str:
    openalex_id = work["source_work_id"]
    openalex_ids = list(dict.fromkeys([
        openalex_id,
        *(work.get("external_openalex_ids") or []),
    ]))
    doi = normalize_doi(work.get("doi"))
    key = (
        store["external_ids"].get(("doi", doi))
        if doi
        else None
    ) or next(
        (
            store["external_ids"].get(("openalex", value))
            for value in openalex_ids
            if store["external_ids"].get(("openalex", value))
        ),
        None,
    )
    if not key:
        key = str(uuid4())
    for value in openalex_ids:
        store["external_ids"][("openalex", value)] = key
    if doi:
        store["external_ids"].setdefault(("doi", doi), key)
    return key


def _apply_memory_batch(
    repository,
    batch: dict,
    *,
    force_rebuild: bool,
    warnings: list[str],
) -> dict:
    store = _memory_store(repository)
    author_id = batch["target_author_id"]
    if force_rebuild:
        store["authorships"] = {
            key: value
            for key, value in store["authorships"].items()
            if key[1] != author_id
        }
        store["affiliations"] = {
            key: value
            for key, value in store["affiliations"].items()
            if key[0] != author_id
        }
        store["scholar_topics"] = {
            key: value
            for key, value in store["scholar_topics"].items()
            if key[0] != author_id
        }
        removed_pairs = {
            pair for pair in store["collaborations"] if author_id in pair
        }
        store["collaborations"] = {
            pair: value
            for pair, value in store["collaborations"].items()
            if pair not in removed_pairs
        }
        store["collaboration_works"] = {
            key: value
            for key, value in store["collaboration_works"].items()
            if (key[0], key[1]) not in removed_pairs
        }
        store["timeline"] = {
            key: value
            for key, value in store["timeline"].items()
            if key[0] != author_id
        }
    store["authors"][author_id] = deepcopy(batch["author"])
    if hasattr(repository, "_scholar"):
        repository._scholar(author_id, batch["author"].get("display_name", ""))
    work_uuid_by_source: dict[str, str] = {}
    topic_uuid_by_source: dict[str, str] = {}

    for work in batch["works"]:
        work_key = _memory_work_key(store, work)
        current = store["works"].get(work_key, {})
        merged = {**deepcopy(current), **deepcopy(work), "id": work_key}
        if not work.get("abstract") and current.get("abstract"):
            merged["abstract"] = current["abstract"]
        current_has_crossref = "crossref" in (current.get("metadata_sources") or [])
        incoming_has_crossref = "crossref" in (work.get("metadata_sources") or [])
        if current_has_crossref and not incoming_has_crossref:
            for field in (
                "title",
                "publication_year",
                "publication_date",
                "venue",
                "work_type",
                "metadata_sources",
            ):
                merged[field] = deepcopy(current.get(field))
        store["works"][work_key] = merged
        work_uuid_by_source[work["source_work_id"]] = work_key
        if force_rebuild:
            store["authorships"] = {
                key: value
                for key, value in store["authorships"].items()
                if key[0] != work_key
            }
            store["work_topics"] = {
                key: value
                for key, value in store["work_topics"].items()
                if key[0] != work_key
            }
            store["citations"] = {
                key: value
                for key, value in store["citations"].items()
                if key[0] != work_key
            }
        store["insights"].setdefault(work_key, deepcopy(work["insight"]))
        if work["insight"]["based_on_abstract"]:
            store["insights"][work_key] = deepcopy(work["insight"])
        for authorship in work["authorships"]:
            coauthor_id = authorship["author"]["id"]
            store["authors"][coauthor_id] = deepcopy(authorship["author"])
            store["authorships"][(work_key, coauthor_id)] = deepcopy(authorship)
        for topic in work["topics"]:
            topic_source_id = topic["source_topic_id"]
            topic_key = next(
                (
                    key for key, value in store["topics"].items()
                    if value["display_name"].casefold() == topic["display_name"].casefold()
                ),
                str(uuid4()),
            )
            store["topics"][topic_key] = {**deepcopy(topic), "id": topic_key}
            topic_uuid_by_source[topic_source_id] = topic_key
            store["work_topics"][(work_key, topic_key)] = deepcopy(topic)
        for cited_source_id in work["referenced_work_ids"]:
            store["citations"][(work_key, cited_source_id)] = {
                "citing_work_id": work_key,
                "cited_work_id": store["external_ids"].get(
                    ("openalex", cited_source_id)
                ),
                "cited_source_work_id": cited_source_id,
                "source": "openalex",
                "confidence": 0.95,
            }

    for affiliation in batch["affiliations"]:
        institution = affiliation["institution"]
        institution_id = institution["id"]
        store["institutions"][institution_id] = deepcopy(institution)
        store["affiliations"][(author_id, institution_id)] = deepcopy(affiliation)

    for item in batch["scholar_topics"]:
        topic_source_id = item["topic"]["source_topic_id"]
        topic_key = topic_uuid_by_source.get(topic_source_id)
        if topic_key:
            store["scholar_topics"][(author_id, topic_key)] = {
                **deepcopy(item),
                "topic_id": topic_key,
            }

    for collaboration in batch["collaborations"]:
        coauthor_id = collaboration["author"]["id"]
        key = tuple(sorted((author_id, coauthor_id)))
        store["collaborations"][key] = deepcopy(collaboration)
        for source_work_id in collaboration["work_ids"]:
            work_key = work_uuid_by_source.get(source_work_id)
            if work_key:
                store["collaboration_works"][(key[0], key[1], work_key)] = {
                    "source": "openalex",
                    "confidence": collaboration["confidence"],
                }

    authored_work_ids = {
        work_id
        for (work_id, relation_author_id) in store["authorships"]
        if relation_author_id == author_id
    }
    for (relation_author_id, topic_id), relation in list(
        store["scholar_topics"].items()
    ):
        if relation_author_id != author_id:
            continue
        related_work_ids = {
            work_id
            for work_id, related_topic_id in store["work_topics"]
            if related_topic_id == topic_id and work_id in authored_work_ids
        }
        years = sorted({
            store["works"][work_id].get("publication_year")
            for work_id in related_work_ids
            if store["works"][work_id].get("publication_year")
        })
        relation.update(
            first_year=min(years) if years else None,
            last_year=max(years) if years else None,
            years=years,
            work_ids=sorted(related_work_ids),
            works_count=len(related_work_ids),
        )
    for pair, relation in store["collaborations"].items():
        if author_id not in pair:
            continue
        related_work_ids = {
            work_id
            for left, right, work_id in store["collaboration_works"]
            if (left, right) == pair
        }
        years = sorted({
            store["works"][work_id].get("publication_year")
            for work_id in related_work_ids
            if store["works"][work_id].get("publication_year")
        })
        relation.update(
            first_year=min(years) if years else None,
            last_year=max(years) if years else None,
            years=years,
            work_ids=sorted(related_work_ids),
            works_count=len(related_work_ids),
        )

    for event in batch["timeline_events"]:
        persisted = deepcopy(event)
        if event.get("work_source_id"):
            persisted["work_id"] = work_uuid_by_source.get(event["work_source_id"])
        if event.get("topic_source_id"):
            persisted["topic_id"] = topic_uuid_by_source.get(event["topic_source_id"])
        store["timeline"][(author_id, event["event_key"])] = persisted

    for citation in store["citations"].values():
        if not citation.get("cited_work_id"):
            citation["cited_work_id"] = store["external_ids"].get(
                ("openalex", citation["cited_source_work_id"])
            )

    previous = store["sync"].get(author_id, {})
    store["sync"][author_id] = {
        "author_id": author_id,
        "status": "ready",
        "last_attempted_at": previous.get("last_attempted_at") or _iso(),
        "last_success_at": _iso(),
        "source_watermark": batch.get("source_watermark"),
        "data_fingerprint": batch["fingerprint"],
        "last_error": None,
        "warnings": deepcopy(warnings),
        "version": int(previous.get("version", 0)) + 1,
        "updated_at": _iso(),
    }
    return {
        "author_id": author_id,
        "version": store["sync"][author_id]["version"],
        "stored_works": len(batch["works"]),
    }


def _upsert_institution(conn, institution: dict) -> str:
    source_id = str(institution.get("id") or "")
    if not source_id:
        raise ValueError("OpenAlex institution id is required")
    row = conn.execute(text("""
        insert into public.institutions (
            source, source_institution_id, display_name, country_code,
            raw_json, updated_at
        ) values (
            'openalex', :source_id, :display_name, :country_code,
            cast(:raw_json as jsonb), now()
        )
        on conflict (source, source_institution_id) do update set
            display_name = excluded.display_name,
            country_code = coalesce(excluded.country_code, institutions.country_code),
            raw_json = excluded.raw_json,
            updated_at = now()
        returning id
    """), {
        "source_id": source_id,
        "display_name": institution.get("display_name") or "?",
        "country_code": institution.get("country_code"),
        "raw_json": _json(institution),
    }).scalar_one()
    return str(row)


def _upsert_affiliation(
    conn,
    scholar_id: str,
    affiliation: dict,
) -> str:
    institution_id = _upsert_institution(conn, affiliation["institution"])
    conn.execute(text("""
        insert into public.scholar_institutions (
            scholar_id, institution_id, is_last_known, start_year, end_year,
            years, is_current, source, confidence, source_records, updated_at
        ) values (
            :scholar_id, :institution_id, :is_last_known, :start_year, :end_year,
            cast(:years as integer[]), :is_current, :source, :confidence,
            cast(:source_records as jsonb), now()
        )
        on conflict (scholar_id, institution_id) do update set
            is_last_known = scholar_institutions.is_last_known or excluded.is_last_known,
            start_year = case
                when scholar_institutions.start_year is null then excluded.start_year
                when excluded.start_year is null then scholar_institutions.start_year
                else least(scholar_institutions.start_year, excluded.start_year)
            end,
            end_year = case
                when scholar_institutions.end_year is null then excluded.end_year
                when excluded.end_year is null then scholar_institutions.end_year
                else greatest(scholar_institutions.end_year, excluded.end_year)
            end,
            years = array(
                select distinct value
                from unnest(scholar_institutions.years || excluded.years) value
                order by value
            ),
            is_current = scholar_institutions.is_current or excluded.is_current,
            source = excluded.source,
            confidence = greatest(scholar_institutions.confidence, excluded.confidence),
            source_records = scholar_institutions.source_records || excluded.source_records,
            updated_at = now()
    """), {
        "scholar_id": scholar_id,
        "institution_id": institution_id,
        "is_last_known": bool(affiliation.get("is_last_known")),
        "start_year": affiliation.get("start_year"),
        "end_year": affiliation.get("end_year"),
        "years": affiliation.get("years") or [],
        "is_current": bool(affiliation.get("is_current")),
        "source": affiliation.get("source", "openalex"),
        "confidence": affiliation.get("confidence", 0.85),
        "source_records": _json(affiliation.get("source_records") or []),
    })
    return institution_id


def _find_work_id(conn, work: dict) -> str | None:
    identifiers = [
        ("openalex", value)
        for value in dict.fromkeys([
            work["source_work_id"],
            *(work.get("external_openalex_ids") or []),
        ])
    ]
    doi = normalize_doi(work.get("doi"))
    if doi:
        identifiers.insert(0, ("doi", doi))
    for identifier_type, identifier_value in identifiers:
        found = conn.execute(text("""
            select work_id from public.work_external_ids
            where identifier_type = :identifier_type
              and identifier_value = :identifier_value
        """), {
            "identifier_type": identifier_type,
            "identifier_value": identifier_value,
        }).scalar_one_or_none()
        if found:
            return str(found)
    doi = normalize_doi(work.get("doi"))
    fallback = conn.execute(text("""
        select id
        from public.works
        where (
            source = 'openalex' and source_work_id = :source_id
        ) or (
            :doi <> ''
            and lower(regexp_replace(
                regexp_replace(btrim(coalesce(doi, '')),
                    '^https?://(dx\\.)?doi\\.org/', '', 'i'),
                '^doi:\\s*', '', 'i'
            )) = :doi
        )
        order by case
            when :doi <> ''
             and lower(regexp_replace(
                regexp_replace(btrim(coalesce(doi, '')),
                    '^https?://(dx\\.)?doi\\.org/', '', 'i'),
                '^doi:\\s*', '', 'i'
             )) = :doi
            then 0 else 1
        end,
        created_at,
        id
        limit 1
    """), {
        "source_id": work["source_work_id"],
        "doi": doi,
    }).scalar_one_or_none()
    if fallback:
        return str(fallback)
    return None


def _upsert_work(conn, work: dict) -> str:
    work_id = _find_work_id(conn, work)
    params = {
        "work_id": work_id,
        "source_id": work["source_work_id"],
        "doi": work.get("doi"),
        "title": work["title"],
        "year": work.get("publication_year"),
        "publication_date": work.get("publication_date"),
        "citations": work.get("cited_by_count", 0),
        "abstract": work.get("abstract"),
        "venue": work.get("venue"),
        "work_type": work.get("work_type"),
        "language": work.get("language"),
        "source_updated_at": work.get("source_updated_at"),
        "metadata_sources": _json(work.get("metadata_sources") or ["openalex"]),
        "incoming_crossref": "crossref" in (work.get("metadata_sources") or []),
        "confidence": work.get("confidence", 0.9),
        "raw_json": _json(work.get("raw") or {}),
    }
    if work_id:
        conn.execute(text("""
            update public.works
            set doi = coalesce(:doi, doi),
                title = case
                    when :incoming_crossref
                      or not (metadata_sources ? 'crossref')
                    then :title else title
                end,
                publication_year = case
                    when :incoming_crossref
                      or not (metadata_sources ? 'crossref')
                    then coalesce(:year, publication_year)
                    else publication_year
                end,
                publication_date = case
                    when :incoming_crossref
                      or not (metadata_sources ? 'crossref')
                    then coalesce(cast(:publication_date as date), publication_date)
                    else publication_date
                end,
                cited_by_count = greatest(:citations, 0),
                abstract = coalesce(:abstract, abstract),
                venue = case
                    when :incoming_crossref
                      or not (metadata_sources ? 'crossref')
                    then coalesce(:venue, venue)
                    else venue
                end,
                work_type = case
                    when :incoming_crossref
                      or not (metadata_sources ? 'crossref')
                    then coalesce(:work_type, work_type)
                    else work_type
                end,
                language = coalesce(:language, language),
                source_updated_at = coalesce(
                    cast(:source_updated_at as timestamptz), source_updated_at
                ),
                last_synced_at = now(),
                metadata_sources = case
                    when :incoming_crossref
                      or not (metadata_sources ? 'crossref')
                    then cast(:metadata_sources as jsonb)
                    else metadata_sources
                end,
                confidence = greatest(confidence, :confidence),
                raw_json = coalesce(raw_json, '{}'::jsonb) || cast(:raw_json as jsonb),
                updated_at = now()
            where id = cast(:work_id as uuid)
        """), params)
    else:
        work_id = str(conn.execute(text("""
            insert into public.works (
                source, source_work_id, doi, title, publication_year,
                publication_date, cited_by_count, abstract, venue, work_type,
                language, source_updated_at, last_synced_at, metadata_sources,
                confidence, raw_json, updated_at
            ) values (
                'openalex', :source_id, :doi, :title, :year,
                cast(:publication_date as date), :citations, :abstract, :venue,
                :work_type, :language, cast(:source_updated_at as timestamptz),
                now(), cast(:metadata_sources as jsonb), :confidence,
                cast(:raw_json as jsonb), now()
            )
            returning id
        """), params).scalar_one())

    identifiers = [
        ("openalex", value, "openalex")
        for value in dict.fromkeys([
            work["source_work_id"],
            *(work.get("external_openalex_ids") or []),
        ])
    ]
    doi = normalize_doi(work.get("doi"))
    if doi:
        identifiers.extend((("doi", doi, "openalex"), ("crossref", doi, "crossref")))
    for identifier_type, identifier_value, source in identifiers:
        conn.execute(text("""
            insert into public.work_external_ids (
                work_id, identifier_type, identifier_value, source, updated_at
            ) values (
                cast(:work_id as uuid), :identifier_type, :identifier_value,
                :source, now()
            )
            on conflict (identifier_type, identifier_value) do update set
                updated_at = now()
        """), {
            "work_id": work_id,
            "identifier_type": identifier_type,
            "identifier_value": identifier_value,
            "source": source,
        })
    return str(work_id)


def _upsert_topic(conn, topic: dict) -> str:
    normalized_name = " ".join(topic["display_name"].casefold().split())
    row = conn.execute(text("""
        insert into public.research_topics (
            source, source_topic_id, display_name, normalized_name,
            description, raw_json, updated_at
        ) values (
            :source, :source_topic_id, :display_name, :normalized_name,
            :description, cast(:raw_json as jsonb), now()
        )
        on conflict (normalized_name) do update set
            display_name = excluded.display_name,
            description = coalesce(excluded.description, research_topics.description),
            raw_json = excluded.raw_json,
            updated_at = now()
        returning id
    """), {
        "source": topic.get("source", "openalex"),
        "source_topic_id": topic["source_topic_id"],
        "display_name": topic["display_name"],
        "normalized_name": normalized_name,
        "description": topic.get("description"),
        "raw_json": _json(topic.get("raw") or {}),
    }).scalar_one()
    return str(row)


def _apply_postgres_batch(
    repository,
    batch: dict,
    *,
    force_rebuild: bool,
    warnings: list[str],
) -> dict:
    author_id = batch["target_author_id"]
    with repository.engine.begin() as conn:
        scholar_id = repository._upsert_scholar(
            conn, batch["author"], fallback_id=author_id
        )
        if force_rebuild:
            for statement in (
                """
                    delete from public.timeline_events
                    where scholar_id = cast(:scholar_id as uuid)
                """,
                """
                    delete from public.scholar_topics
                    where scholar_id = cast(:scholar_id as uuid)
                """,
                """
                    delete from public.collaborations
                    where scholar_a_id = cast(:scholar_id as uuid)
                       or scholar_b_id = cast(:scholar_id as uuid)
                """,
                """
                    delete from public.scholar_institutions
                    where scholar_id = cast(:scholar_id as uuid)
                """,
                """
                    delete from public.authorships
                    where scholar_id = cast(:scholar_id as uuid)
                """,
            ):
                conn.execute(text(statement), {"scholar_id": scholar_id})
        work_ids: dict[str, str] = {}
        topic_ids: dict[str, str] = {}
        author_ids: dict[str, str] = {author_id: scholar_id}
        institution_ids: dict[str, str] = {}

        for affiliation in batch["affiliations"]:
            institution_id = _upsert_affiliation(conn, scholar_id, affiliation)
            institution_ids[affiliation["institution"]["id"]] = institution_id

        for work in batch["works"]:
            work_id = _upsert_work(conn, work)
            work_ids[work["source_work_id"]] = work_id
            if force_rebuild:
                for statement in (
                    """
                        delete from public.work_citations
                        where citing_work_id = cast(:work_id as uuid)
                    """,
                    """
                        delete from public.work_topics
                        where work_id = cast(:work_id as uuid)
                    """,
                    """
                        delete from public.authorships
                        where work_id = cast(:work_id as uuid)
                    """,
                ):
                    conn.execute(text(statement), {"work_id": work_id})

            for authorship in work["authorships"]:
                raw_author = authorship["author"]
                source_author_id = raw_author["id"]
                related_scholar_id = repository._upsert_scholar(conn, raw_author)
                author_ids[source_author_id] = related_scholar_id
                conn.execute(text("""
                    insert into public.authorships (
                        work_id, scholar_id, author_position, position_index,
                        raw_author_name, is_corresponding, source, confidence,
                        updated_at
                    ) values (
                        cast(:work_id as uuid), cast(:scholar_id as uuid),
                        :author_position, :position_index, :raw_author_name,
                        :is_corresponding, :source, :confidence, now()
                    )
                    on conflict (work_id, scholar_id) do update set
                        author_position = excluded.author_position,
                        position_index = excluded.position_index,
                        raw_author_name = excluded.raw_author_name,
                        is_corresponding = excluded.is_corresponding,
                        source = excluded.source,
                        confidence = excluded.confidence,
                        updated_at = now()
                """), {
                    "work_id": work_id,
                    "scholar_id": related_scholar_id,
                    "author_position": authorship.get("author_position"),
                    "position_index": authorship.get("position_index"),
                    "raw_author_name": raw_author.get("display_name") or "?",
                    "is_corresponding": authorship.get("is_corresponding", False),
                    "source": authorship.get("source", "openalex"),
                    "confidence": authorship.get("confidence", 0.95),
                })
                for institution in authorship.get("institutions") or []:
                    _upsert_affiliation(conn, related_scholar_id, {
                        "institution": institution,
                        "years": institution.get("years") or [],
                        "start_year": min(institution.get("years") or [None]),
                        "end_year": max(institution.get("years") or [None]),
                        "is_last_known": False,
                        "is_current": False,
                        "source": "openalex",
                        "confidence": 0.8,
                        "source_records": [{"source": "openalex_work_authorship"}],
                    })

            for topic in work["topics"]:
                topic_id = _upsert_topic(conn, topic)
                topic_ids[topic["source_topic_id"]] = topic_id
                conn.execute(text("""
                    insert into public.work_topics (
                        work_id, topic_id, score, is_primary, source,
                        confidence, updated_at
                    ) values (
                        cast(:work_id as uuid), cast(:topic_id as uuid),
                        :score, :is_primary, :source, :confidence, now()
                    )
                    on conflict (work_id, topic_id) do update set
                        score = excluded.score,
                        is_primary = excluded.is_primary,
                        source = excluded.source,
                        confidence = excluded.confidence,
                        updated_at = now()
                """), {
                    "work_id": work_id,
                    "topic_id": topic_id,
                    "score": topic.get("score"),
                    "is_primary": topic.get("is_primary", False),
                    "source": topic.get("source", "openalex"),
                    "confidence": topic.get("confidence", 0.85),
                })

            insight = work["insight"]
            conn.execute(text("""
                insert into public.paper_insights (
                    work_id, problem, core_method, main_contribution,
                    topic_relationship, abstract_evidence, based_on_abstract,
                    analyzer_version, source, confidence, updated_at
                ) values (
                    cast(:work_id as uuid), :problem, :core_method,
                    :main_contribution, :topic_relationship,
                    cast(:abstract_evidence as jsonb), :based_on_abstract,
                    :analyzer_version, :source, :confidence, now()
                )
                on conflict (work_id) do update set
                    problem = excluded.problem,
                    core_method = excluded.core_method,
                    main_contribution = excluded.main_contribution,
                    topic_relationship = excluded.topic_relationship,
                    abstract_evidence = excluded.abstract_evidence,
                    based_on_abstract = excluded.based_on_abstract,
                    analyzer_version = excluded.analyzer_version,
                    source = excluded.source,
                    confidence = excluded.confidence,
                    updated_at = now()
                where excluded.based_on_abstract
            """), {
                "work_id": work_id,
                "problem": insight.get("problem"),
                "core_method": insight.get("core_method"),
                "main_contribution": insight.get("main_contribution"),
                "topic_relationship": insight.get("topic_relationship"),
                "abstract_evidence": _json(insight.get("abstract_evidence") or []),
                "based_on_abstract": insight.get("based_on_abstract", False),
                "analyzer_version": insight["analyzer_version"],
                "source": insight["source"],
                "confidence": insight.get("confidence", 0),
            })

        for work in batch["works"]:
            citing_work_id = work_ids[work["source_work_id"]]
            for cited_source_id in work["referenced_work_ids"]:
                cited_work_id = conn.execute(text("""
                    select work_id from public.work_external_ids
                    where identifier_type = 'openalex'
                      and identifier_value = :source_id
                """), {"source_id": cited_source_id}).scalar_one_or_none()
                if cited_work_id and str(cited_work_id) == citing_work_id:
                    continue
                conn.execute(text("""
                    insert into public.work_citations (
                        citing_work_id, cited_work_id, cited_source_work_id,
                        source, confidence, updated_at
                    ) values (
                        cast(:citing_work_id as uuid),
                        cast(:cited_work_id as uuid),
                        :cited_source_id, 'openalex', 0.950, now()
                    )
                    on conflict (citing_work_id, cited_source_work_id) do update set
                        cited_work_id = coalesce(
                            excluded.cited_work_id, work_citations.cited_work_id
                        ),
                        source = excluded.source,
                        confidence = excluded.confidence,
                        updated_at = now()
                """), {
                    "citing_work_id": citing_work_id,
                    "cited_work_id": str(cited_work_id) if cited_work_id else None,
                    "cited_source_id": cited_source_id,
                })

        conn.execute(text("""
            update public.work_citations c
            set cited_work_id = identifiers.work_id,
                updated_at = now()
            from public.work_external_ids identifiers
            where c.cited_work_id is null
              and identifiers.identifier_type = 'openalex'
              and identifiers.identifier_value = c.cited_source_work_id
              and identifiers.work_id <> c.citing_work_id
        """))

        for item in batch["scholar_topics"]:
            topic = item["topic"]
            topic_id = topic_ids.get(topic["source_topic_id"]) or _upsert_topic(conn, topic)
            conn.execute(text("""
                insert into public.scholar_topics (
                    scholar_id, topic_id, first_year, last_year, works_count,
                    source, confidence, updated_at
                ) values (
                    cast(:scholar_id as uuid), cast(:topic_id as uuid),
                    :first_year, :last_year, :works_count, :source,
                    :confidence, now()
                )
                on conflict (scholar_id, topic_id) do update set
                    first_year = case
                        when scholar_topics.first_year is null then excluded.first_year
                        when excluded.first_year is null then scholar_topics.first_year
                        else least(scholar_topics.first_year, excluded.first_year)
                    end,
                    last_year = case
                        when scholar_topics.last_year is null then excluded.last_year
                        when excluded.last_year is null then scholar_topics.last_year
                        else greatest(scholar_topics.last_year, excluded.last_year)
                    end,
                    works_count = excluded.works_count,
                    source = excluded.source,
                    confidence = greatest(
                        scholar_topics.confidence, excluded.confidence
                    ),
                    updated_at = now()
            """), {
                "scholar_id": scholar_id,
                "topic_id": topic_id,
                "first_year": item.get("first_year"),
                "last_year": item.get("last_year"),
                "works_count": item.get("works_count", 0),
                "source": item.get("source", "openalex"),
                "confidence": item.get("confidence", 0.85),
            })
            conn.execute(text("""
                update public.scholar_topics st
                set first_year = stats.first_year,
                    last_year = stats.last_year,
                    works_count = stats.works_count,
                    updated_at = now()
                from (
                    select min(w.publication_year) as first_year,
                           max(w.publication_year) as last_year,
                           count(distinct w.id)::integer as works_count
                    from public.authorships a
                    join public.works w on w.id = a.work_id
                    join public.work_topics wt on wt.work_id = w.id
                    where a.scholar_id = cast(:scholar_id as uuid)
                      and wt.topic_id = cast(:topic_id as uuid)
                ) stats
                where st.scholar_id = cast(:scholar_id as uuid)
                  and st.topic_id = cast(:topic_id as uuid)
            """), {"scholar_id": scholar_id, "topic_id": topic_id})

        collaboration_pairs: dict[str, tuple[str, str]] = {}
        for collaboration in batch["collaborations"]:
            coauthor_source_id = collaboration["author"]["id"]
            coauthor_id = author_ids.get(coauthor_source_id)
            if not coauthor_id:
                coauthor_id = repository._upsert_scholar(conn, collaboration["author"])
            scholar_a_id, scholar_b_id = sorted((scholar_id, coauthor_id))
            collaboration_pairs[coauthor_source_id] = (scholar_a_id, scholar_b_id)
            conn.execute(text("""
                insert into public.collaborations (
                    scholar_a_id, scholar_b_id, first_year, last_year,
                    works_count, source, confidence, updated_at
                ) values (
                    cast(:scholar_a_id as uuid), cast(:scholar_b_id as uuid),
                    :first_year, :last_year, :works_count, :source,
                    :confidence, now()
                )
                on conflict (scholar_a_id, scholar_b_id) do update set
                    first_year = excluded.first_year,
                    last_year = excluded.last_year,
                    works_count = excluded.works_count,
                    source = excluded.source,
                    confidence = greatest(
                        collaborations.confidence, excluded.confidence
                    ),
                    updated_at = now()
            """), {
                "scholar_a_id": scholar_a_id,
                "scholar_b_id": scholar_b_id,
                "first_year": collaboration.get("first_year"),
                "last_year": collaboration.get("last_year"),
                "works_count": collaboration.get("works_count", 0),
                "source": collaboration.get("source", "openalex"),
                "confidence": collaboration.get("confidence", 0.9),
            })
            for source_work_id in collaboration["work_ids"]:
                work_id = work_ids.get(source_work_id)
                if not work_id:
                    continue
                conn.execute(text("""
                    insert into public.collaboration_works (
                        scholar_a_id, scholar_b_id, work_id, source, confidence
                    ) values (
                        cast(:scholar_a_id as uuid),
                        cast(:scholar_b_id as uuid),
                        cast(:work_id as uuid), 'openalex', :confidence
                    )
                    on conflict do nothing
                """), {
                    "scholar_a_id": scholar_a_id,
                    "scholar_b_id": scholar_b_id,
                    "work_id": work_id,
                    "confidence": collaboration.get("confidence", 0.9),
                })
            conn.execute(text("""
                update public.collaborations c
                set first_year = stats.first_year,
                    last_year = stats.last_year,
                    works_count = stats.works_count,
                    updated_at = now()
                from (
                    select min(w.publication_year) as first_year,
                           max(w.publication_year) as last_year,
                           count(distinct cw.work_id)::integer as works_count
                    from public.collaboration_works cw
                    join public.works w on w.id = cw.work_id
                    where cw.scholar_a_id = cast(:scholar_a_id as uuid)
                      and cw.scholar_b_id = cast(:scholar_b_id as uuid)
                ) stats
                where c.scholar_a_id = cast(:scholar_a_id as uuid)
                  and c.scholar_b_id = cast(:scholar_b_id as uuid)
            """), {
                "scholar_a_id": scholar_a_id,
                "scholar_b_id": scholar_b_id,
            })

        for event in batch["timeline_events"]:
            work_id = work_ids.get(event.get("work_source_id", ""))
            topic_id = topic_ids.get(event.get("topic_source_id", ""))
            institution_id = institution_ids.get(
                event.get("institution_source_id", "")
            )
            collaborator_id = author_ids.get(
                event.get("collaborator_source_id", "")
            )
            conn.execute(text("""
                insert into public.timeline_events (
                    scholar_id, event_key, event_type, event_year, event_date,
                    title, description, work_id, topic_id, institution_id,
                    collaborator_id, source, confidence, updated_at
                ) values (
                    cast(:scholar_id as uuid), :event_key, :event_type,
                    :event_year, cast(:event_date as date), :title,
                    :description, cast(:work_id as uuid),
                    cast(:topic_id as uuid), cast(:institution_id as uuid),
                    cast(:collaborator_id as uuid), :source, :confidence, now()
                )
                on conflict (scholar_id, event_key) do update set
                    event_year = excluded.event_year,
                    event_date = excluded.event_date,
                    title = excluded.title,
                    description = excluded.description,
                    work_id = coalesce(excluded.work_id, timeline_events.work_id),
                    topic_id = coalesce(excluded.topic_id, timeline_events.topic_id),
                    institution_id = coalesce(
                        excluded.institution_id, timeline_events.institution_id
                    ),
                    collaborator_id = coalesce(
                        excluded.collaborator_id, timeline_events.collaborator_id
                    ),
                    source = excluded.source,
                    confidence = excluded.confidence,
                    updated_at = now()
            """), {
                "scholar_id": scholar_id,
                "event_key": event["event_key"],
                "event_type": event["event_type"],
                "event_year": event.get("event_year"),
                "event_date": event.get("event_date"),
                "title": event["title"],
                "description": event.get("description", ""),
                "work_id": work_id,
                "topic_id": topic_id,
                "institution_id": institution_id,
                "collaborator_id": collaborator_id,
                "source": event.get("source", "openalex"),
                "confidence": event.get("confidence", 0.85),
            })

        version = conn.execute(text("""
            insert into public.research_graph_sync_state (
                scholar_id, status, last_attempted_at, last_success_at,
                source_watermark, data_fingerprint, last_error, warnings,
                version, updated_at
            ) values (
                cast(:scholar_id as uuid), 'ready', now(), now(),
                cast(:source_watermark as timestamptz), :fingerprint, null,
                cast(:warnings as jsonb), 1, now()
            )
            on conflict (scholar_id) do update set
                status = 'ready',
                last_attempted_at = now(),
                last_success_at = now(),
                source_watermark = coalesce(
                    excluded.source_watermark,
                    research_graph_sync_state.source_watermark
                ),
                data_fingerprint = excluded.data_fingerprint,
                last_error = null,
                warnings = excluded.warnings,
                version = research_graph_sync_state.version + 1,
                updated_at = now()
            returning version
        """), {
            "scholar_id": scholar_id,
            "source_watermark": batch.get("source_watermark"),
            "fingerprint": batch["fingerprint"],
            "warnings": _json(warnings),
        }).scalar_one()

    return {
        "author_id": author_id,
        "version": int(version),
        "stored_works": len(batch["works"]),
    }


def apply_research_graph_batch(
    repository,
    batch: dict,
    *,
    force_rebuild: bool,
    warnings: list[str] | None = None,
) -> dict:
    """Atomically upsert one successful complete batch.

    A forced rebuild is still scholar-scoped. It replaces that scholar's graph
    relations only after a complete upstream batch has already been obtained.
    """
    if _is_postgres(repository):
        return _apply_postgres_batch(
            repository,
            batch,
            force_rebuild=force_rebuild,
            warnings=warnings or [],
        )
    return _apply_memory_batch(
        repository,
        batch,
        force_rebuild=force_rebuild,
        warnings=warnings or [],
    )


def _empty_graph(author_id: str, status: str = "never") -> dict:
    return {
        "author": {"source_id": author_id, "name": ""},
        "status": {
            "status": status,
            "version": 0,
            "last_success_at": None,
            "last_error": None,
            "warnings": [],
        },
        "timeline": [],
        "topic_evolution": [],
        "collaborations": [],
        "affiliations": [],
        "papers": [],
        "citations": [],
        "local_network": {"nodes": [], "edges": []},
    }


def _memory_graph(repository, author_id: str) -> dict:
    store = _memory_store(repository)
    author = store["authors"].get(author_id)
    state = store["sync"].get(author_id)
    if not author and not state:
        return _empty_graph(author_id)
    paper_ids = {
        work_id
        for (work_id, scholar_source_id) in store["authorships"]
        if scholar_source_id == author_id
    }
    topics_by_work: dict[str, list[dict]] = defaultdict(list)
    for (work_id, topic_id), relation in store["work_topics"].items():
        if work_id in paper_ids:
            topics_by_work[work_id].append({
                "id": topic_id,
                "name": store["topics"][topic_id]["display_name"],
                "is_primary": relation.get("is_primary", False),
                "source": relation.get("source", "openalex"),
                "confidence": relation.get("confidence", 0.85),
            })
    papers = []
    for work_id in paper_ids:
        work = store["works"][work_id]
        papers.append({
            "id": work_id,
            "source_id": work["source_work_id"],
            "title": work["title"],
            "year": work.get("publication_year"),
            "publication_date": work.get("publication_date"),
            "citations": work.get("cited_by_count", 0),
            "doi": work.get("doi"),
            "venue": work.get("venue"),
            "has_abstract": bool(work.get("abstract")),
            "topics": topics_by_work[work_id],
            "insight": deepcopy(store["insights"].get(work_id)),
            "source": work.get("metadata_sources", ["openalex"]),
            "confidence": work.get("confidence", 0.9),
        })
    papers.sort(key=lambda item: (item["citations"], item["year"] or 0), reverse=True)
    timeline = [
        {
            **deepcopy(event),
            "id": event["event_key"],
        }
        for (event_author_id, _), event in store["timeline"].items()
        if event_author_id == author_id
    ]
    timeline.sort(
        key=lambda item: (
            item.get("event_year") or 0,
            item.get("event_date") or "",
            item["event_key"],
        ),
        reverse=True,
    )
    affiliations = []
    for (relation_author_id, institution_id), relation in store["affiliations"].items():
        if relation_author_id != author_id:
            continue
        institution = store["institutions"][institution_id]
        affiliations.append({
            "id": institution_id,
            "name": institution.get("display_name", ""),
            "country_code": institution.get("country_code"),
            **{
                key: deepcopy(relation.get(key))
                for key in (
                    "start_year", "end_year", "years", "is_current",
                    "source", "confidence",
                )
            },
        })
    collaborations = []
    for pair, relation in store["collaborations"].items():
        if author_id not in pair:
            continue
        coauthor_id = pair[1] if pair[0] == author_id else pair[0]
        coauthor = store["authors"].get(coauthor_id, {})
        collaboration_papers = [
            store["works"][work_id]
            for left, right, work_id in store["collaboration_works"]
            if (left, right) == pair
        ]
        collaborations.append({
            "author": {
                "id": coauthor_id,
                "source_id": coauthor_id,
                "name": coauthor.get("display_name", coauthor_id),
            },
            "first_year": relation.get("first_year"),
            "last_year": relation.get("last_year"),
            "works_count": relation.get("works_count", 0),
            "papers": [
                {
                    "id": work.get("id"),
                    "title": work["title"],
                    "year": work.get("publication_year"),
                }
                for work in collaboration_papers
            ],
            "source": relation.get("source", "openalex"),
            "confidence": relation.get("confidence", 0.9),
        })
    topic_evolution = []
    for (relation_author_id, topic_id), relation in store["scholar_topics"].items():
        if relation_author_id != author_id:
            continue
        topic_evolution.append({
            "id": topic_id,
            "name": store["topics"][topic_id]["display_name"],
            "first_year": relation.get("first_year"),
            "last_year": relation.get("last_year"),
            "works_count": relation.get("works_count", 0),
            "years": relation.get("years", []),
            "source": relation.get("source", "openalex"),
            "confidence": relation.get("confidence", 0.85),
        })
    citations = []
    for (citing_work_id, cited_source_id), relation in store["citations"].items():
        if citing_work_id not in paper_ids:
            continue
        cited_work_id = relation.get("cited_work_id")
        if not cited_work_id or cited_work_id not in paper_ids:
            continue
        cited_work = store["works"].get(cited_work_id, {})
        citations.append({
            "citing": {
                "id": citing_work_id,
                "title": store["works"][citing_work_id]["title"],
            },
            "cited": {
                "id": cited_work_id,
                "source_id": cited_source_id,
                "title": cited_work.get("title") or cited_source_id,
            },
            "source": relation["source"],
            "confidence": relation["confidence"],
        })
    return _assemble_graph_payload(
        author_id=author_id,
        author_uuid=author_id,
        author_name=(author or {}).get("display_name", ""),
        state=state or {"status": "never", "version": 0},
        timeline=timeline,
        topics=topic_evolution,
        collaborations=collaborations,
        affiliations=affiliations,
        papers=papers,
        citations=citations,
    )


def _assemble_graph_payload(
    *,
    author_id: str,
    author_uuid: str,
    author_name: str,
    state: dict,
    timeline: list[dict],
    topics: list[dict],
    collaborations: list[dict],
    affiliations: list[dict],
    papers: list[dict],
    citations: list[dict],
) -> dict:
    nodes = [{
        "id": f"author:{author_uuid}",
        "object_id": author_uuid,
        "object_type": "author",
        "label": author_name,
        "group": "author",
        "detail_url": f"/api/research-graph/objects/author/{author_uuid}",
    }]
    edges = []
    for collaboration in collaborations[:10]:
        coauthor = collaboration["author"]
        node_id = f"author:{coauthor['id']}"
        nodes.append({
            "id": node_id,
            "object_id": coauthor["id"],
            "object_type": "author",
            "label": coauthor["name"],
            "group": "collaborator",
            "detail_url": f"/api/research-graph/objects/author/{coauthor['id']}",
        })
        edges.append({
            "from": f"author:{author_uuid}",
            "to": node_id,
            "type": "collaborates",
            "label": str(collaboration["works_count"]),
        })
    for paper in papers[:8]:
        node_id = f"paper:{paper['id']}"
        nodes.append({
            "id": node_id,
            "object_id": paper["id"],
            "object_type": "paper",
            "label": paper["title"],
            "group": "paper",
            "detail_url": f"/api/research-graph/objects/paper/{paper['id']}",
        })
        edges.append({
            "from": f"author:{author_uuid}",
            "to": node_id,
            "type": "authored",
            "label": str(paper.get("year") or ""),
        })
        for topic in paper.get("topics", [])[:2]:
            topic_node_id = f"topic:{topic['id']}"
            if not any(node["id"] == topic_node_id for node in nodes):
                nodes.append({
                    "id": topic_node_id,
                    "object_id": topic["id"],
                    "object_type": "topic",
                    "label": topic["name"],
                    "group": "topic",
                    "detail_url": f"/api/research-graph/objects/topic/{topic['id']}",
                })
            edges.append({
                "from": node_id,
                "to": topic_node_id,
                "type": "has_topic",
                "label": "",
            })
    for affiliation in affiliations[:4]:
        node_id = f"institution:{affiliation['id']}"
        nodes.append({
            "id": node_id,
            "object_id": affiliation["id"],
            "object_type": "institution",
            "label": affiliation["name"],
            "group": "institution",
            "detail_url": (
                f"/api/research-graph/objects/institution/{affiliation['id']}"
            ),
        })
        edges.append({
            "from": f"author:{author_uuid}",
            "to": node_id,
            "type": "affiliated",
            "label": "",
        })
    return {
        "author": {
            "id": author_uuid,
            "source_id": author_id,
            "name": author_name,
            "detail_url": f"/api/research-graph/objects/author/{author_uuid}",
        },
        "status": {
            "status": state.get("status", "never"),
            "version": int(state.get("version", 0)),
            "last_success_at": (
                _iso(state.get("last_success_at"))
                if state.get("last_success_at")
                else None
            ),
            "last_error": state.get("last_error"),
            "warnings": list(state.get("warnings") or []),
        },
        "timeline": timeline,
        "topic_evolution": sorted(
            topics,
            key=lambda item: (
                item.get("last_year") or 0,
                item.get("works_count") or 0,
            ),
            reverse=True,
        ),
        "collaborations": sorted(
            collaborations,
            key=lambda item: (
                item.get("last_year") or 0,
                item.get("works_count") or 0,
            ),
            reverse=True,
        ),
        "affiliations": sorted(
            affiliations,
            key=lambda item: (
                bool(item.get("is_current")),
                item.get("end_year") or 0,
                item.get("start_year") or 0,
            ),
            reverse=True,
        ),
        "papers": papers,
        "citations": citations,
        "local_network": {"nodes": nodes[:30], "edges": edges[:60]},
    }


def _postgres_graph(repository, author_id: str) -> dict:
    with repository.engine.connect() as conn:
        author = conn.execute(text("""
            select s.id, s.source_author_id, s.display_name, s.orcid,
                   gs.status, gs.version, gs.last_success_at, gs.last_error,
                   gs.warnings
            from public.scholars s
            left join public.research_graph_sync_state gs on gs.scholar_id = s.id
            where s.source = 'openalex' and s.source_author_id = :author_id
        """), {"author_id": author_id}).mappings().first()
        if not author:
            return _empty_graph(author_id)
        if author["status"] is None:
            empty = _empty_graph(author_id)
            empty["author"].update({
                "id": str(author["id"]),
                "name": author["display_name"],
            })
            return empty
        scholar_id = str(author["id"])
        if author["last_success_at"] is None:
            return _assemble_graph_payload(
                author_id=author_id,
                author_uuid=scholar_id,
                author_name=author["display_name"],
                state=dict(author),
                timeline=[],
                topics=[],
                collaborations=[],
                affiliations=[],
                papers=[],
                citations=[],
            )
        work_rows = conn.execute(text("""
            select distinct w.id, w.source_work_id, w.title,
                   w.publication_year, w.publication_date, w.cited_by_count,
                   w.doi, w.venue, w.abstract is not null as has_abstract,
                   w.metadata_sources, w.confidence,
                   pi.problem, pi.core_method, pi.main_contribution,
                   pi.topic_relationship, pi.abstract_evidence,
                   pi.based_on_abstract, pi.analyzer_version,
                   pi.source as insight_source, pi.confidence as insight_confidence
            from public.works w
            join public.authorships a on a.work_id = w.id
            join public.paper_insights pi on pi.work_id = w.id
            where a.scholar_id = cast(:scholar_id as uuid)
            order by w.cited_by_count desc, w.publication_year desc nulls last, w.id
            limit 1000
        """), {"scholar_id": scholar_id}).mappings().all()
        work_ids = [str(row["id"]) for row in work_rows]
        topic_rows = []
        if work_ids:
            topic_rows = conn.execute(text("""
                select wt.work_id, t.id, t.display_name, wt.is_primary,
                       wt.source, wt.confidence
                from public.work_topics wt
                join public.research_topics t on t.id = wt.topic_id
                where wt.work_id = any(cast(:work_ids as uuid[]))
                order by wt.is_primary desc, wt.score desc nulls last,
                         t.display_name
            """), {"work_ids": work_ids}).mappings().all()
        topics_by_work: dict[str, list[dict]] = defaultdict(list)
        for row in topic_rows:
            topics_by_work[str(row["work_id"])].append({
                "id": str(row["id"]),
                "name": row["display_name"],
                "is_primary": row["is_primary"],
                "source": row["source"],
                "confidence": float(row["confidence"]),
            })
        papers = []
        for row in work_rows:
            work_id = str(row["id"])
            insight = {
                "problem": row["problem"],
                "core_method": row["core_method"],
                "main_contribution": row["main_contribution"],
                "topic_relationship": row["topic_relationship"],
                "abstract_evidence": row["abstract_evidence"] or [],
                "based_on_abstract": bool(row["based_on_abstract"]),
                "analyzer_version": row["analyzer_version"],
                "source": row["insight_source"],
                "confidence": (
                    float(row["insight_confidence"])
                    if row["insight_confidence"] is not None
                    else 0
                ),
            }
            papers.append({
                "id": work_id,
                "source_id": row["source_work_id"],
                "title": row["title"],
                "year": row["publication_year"],
                "publication_date": (
                    row["publication_date"].isoformat()
                    if row["publication_date"]
                    else None
                ),
                "citations": row["cited_by_count"],
                "doi": normalize_doi(row["doi"]) or None,
                "venue": row["venue"],
                "has_abstract": row["has_abstract"],
                "topics": topics_by_work[work_id],
                "insight": insight,
                "source": row["metadata_sources"] or [],
                "confidence": float(row["confidence"]),
            })

        timeline_rows = conn.execute(text("""
            select id, event_key, event_type, event_year, event_date, title,
                   description, work_id, topic_id, institution_id,
                   collaborator_id, source, confidence
            from public.timeline_events
            where scholar_id = cast(:scholar_id as uuid)
            order by event_year desc nulls last, event_date desc nulls last,
                     event_key desc
        """), {"scholar_id": scholar_id}).mappings().all()
        timeline = []
        for row in timeline_rows:
            item = dict(row)
            for key in ("id", "work_id", "topic_id", "institution_id", "collaborator_id"):
                item[key] = str(item[key]) if item.get(key) else None
            item["event_date"] = (
                item["event_date"].isoformat() if item.get("event_date") else None
            )
            item["confidence"] = float(item["confidence"])
            timeline.append(item)

        topic_rows = conn.execute(text("""
            select t.id, t.display_name, st.first_year, st.last_year,
                   st.works_count, st.source, st.confidence,
                   coalesce((
                       select jsonb_agg(jsonb_build_object(
                           'year', yearly.publication_year,
                           'works_count', yearly.works_count
                       ) order by yearly.publication_year)
                       from (
                           select w.publication_year,
                                  count(distinct w.id)::integer as works_count
                           from public.authorships a
                           join public.works w on w.id = a.work_id
                           join public.work_topics wt on wt.work_id = w.id
                           where a.scholar_id = st.scholar_id
                             and wt.topic_id = st.topic_id
                             and w.publication_year is not null
                           group by w.publication_year
                       ) yearly
                   ), '[]'::jsonb) as years
            from public.scholar_topics st
            join public.research_topics t on t.id = st.topic_id
            where st.scholar_id = cast(:scholar_id as uuid)
            order by st.last_year desc nulls last, st.works_count desc
        """), {"scholar_id": scholar_id}).mappings().all()
        topics = [{
            "id": str(row["id"]),
            "name": row["display_name"],
            "first_year": row["first_year"],
            "last_year": row["last_year"],
            "works_count": row["works_count"],
            "years": row["years"] or [],
            "source": row["source"],
            "confidence": float(row["confidence"]),
        } for row in topic_rows]

        affiliation_rows = conn.execute(text("""
            select i.id, i.source_institution_id, i.display_name, i.country_code,
                   si.start_year, si.end_year, si.years, si.is_current,
                   si.is_last_known, si.source, si.confidence
            from public.scholar_institutions si
            join public.institutions i on i.id = si.institution_id
            where si.scholar_id = cast(:scholar_id as uuid)
            order by si.is_current desc, si.end_year desc nulls last,
                     si.start_year desc nulls last
        """), {"scholar_id": scholar_id}).mappings().all()
        affiliations = [{
            "id": str(row["id"]),
            "source_id": row["source_institution_id"],
            "name": row["display_name"],
            "country_code": row["country_code"],
            "start_year": row["start_year"],
            "end_year": row["end_year"],
            "years": list(row["years"] or []),
            "is_current": row["is_current"],
            "is_last_known": row["is_last_known"],
            "source": row["source"],
            "confidence": float(row["confidence"]),
        } for row in affiliation_rows]

        collaboration_rows = conn.execute(text("""
            select c.scholar_a_id, c.scholar_b_id, c.first_year, c.last_year,
                   c.works_count, c.source, c.confidence,
                   other.id as author_id,
                   other.source_author_id, other.display_name,
                   coalesce((
                       select jsonb_agg(jsonb_build_object(
                           'id', w.id,
                           'source_id', w.source_work_id,
                           'title', w.title,
                           'year', w.publication_year
                       ) order by w.publication_year desc nulls last,
                                  w.cited_by_count desc)
                       from public.collaboration_works cw
                       join public.works w on w.id = cw.work_id
                       where cw.scholar_a_id = c.scholar_a_id
                         and cw.scholar_b_id = c.scholar_b_id
                   ), '[]'::jsonb) as papers
            from public.collaborations c
            join public.scholars other on other.id = case
                when c.scholar_a_id = cast(:scholar_id as uuid)
                then c.scholar_b_id else c.scholar_a_id end
            where c.scholar_a_id = cast(:scholar_id as uuid)
               or c.scholar_b_id = cast(:scholar_id as uuid)
            order by c.last_year desc nulls last, c.works_count desc
            limit 50
        """), {"scholar_id": scholar_id}).mappings().all()
        collaborations = [{
            "author": {
                "id": str(row["author_id"]),
                "source_id": row["source_author_id"],
                "name": row["display_name"],
            },
            "first_year": row["first_year"],
            "last_year": row["last_year"],
            "works_count": row["works_count"],
            "papers": [
                {
                    **paper,
                    "id": str(paper["id"]),
                }
                for paper in row["papers"] or []
            ],
            "source": row["source"],
            "confidence": float(row["confidence"]),
        } for row in collaboration_rows]

        citation_rows = []
        if work_ids:
            citation_rows = conn.execute(text("""
                select c.citing_work_id, citing.title as citing_title,
                       c.cited_work_id, c.cited_source_work_id,
                       cited.title as cited_title, c.source, c.confidence
                from public.work_citations c
                join public.works citing on citing.id = c.citing_work_id
                left join public.works cited on cited.id = c.cited_work_id
                where c.citing_work_id = any(cast(:work_ids as uuid[]))
                  and c.cited_work_id = any(cast(:work_ids as uuid[]))
                order by citing.publication_year desc nulls last,
                         cited.publication_year desc nulls last,
                         citing.cited_by_count desc
                limit 100
            """), {"work_ids": work_ids}).mappings().all()
        citations = [{
            "citing": {
                "id": str(row["citing_work_id"]),
                "title": row["citing_title"],
            },
            "cited": {
                "id": str(row["cited_work_id"]) if row["cited_work_id"] else None,
                "source_id": row["cited_source_work_id"],
                "title": row["cited_title"] or row["cited_source_work_id"],
            },
            "source": row["source"],
            "confidence": float(row["confidence"]),
        } for row in citation_rows]

    return _assemble_graph_payload(
        author_id=author_id,
        author_uuid=scholar_id,
        author_name=author["display_name"],
        state=dict(author),
        timeline=timeline,
        topics=topics,
        collaborations=collaborations,
        affiliations=affiliations,
        papers=papers,
        citations=citations,
    )


def get_research_graph(repository, author_id: str) -> dict:
    if _is_postgres(repository):
        return _postgres_graph(repository, author_id)
    return _memory_graph(repository, author_id)


def get_research_graph_object(
    repository,
    object_type: str,
    object_id: str,
) -> dict | None:
    allowed = {"author", "paper", "institution", "topic"}
    if object_type not in allowed:
        return None
    if not _is_postgres(repository):
        store = _memory_store(repository)
        mapping = {
            "author": store["authors"],
            "paper": store["works"],
            "institution": store["institutions"],
            "topic": store["topics"],
        }[object_type]
        value = mapping.get(object_id)
        return (
            {"type": object_type, "id": object_id, "data": deepcopy(value)}
            if value
            else None
        )
    table_config = {
        "author": ("scholars", "id", "source_author_id, display_name, orcid, works_count, cited_by_count, h_index, raw_json"),
        "paper": ("works", "id", "source_work_id, doi, title, publication_year, publication_date, cited_by_count, abstract, venue, work_type, language, metadata_sources, confidence"),
        "institution": ("institutions", "id", "source_institution_id, display_name, country_code, raw_json"),
        "topic": ("research_topics", "id", "source_topic_id, display_name, description, raw_json"),
    }
    table, id_column, columns = table_config[object_type]
    with repository.engine.connect() as conn:
        row = conn.execute(text(f"""
            select {id_column} as id, {columns}
            from public.{table}
            where {id_column} = cast(:object_id as uuid)
        """), {"object_id": object_id}).mappings().first()
    if not row:
        return None
    data = dict(row)
    data["id"] = str(data["id"])
    for key, value in list(data.items()):
        if hasattr(value, "isoformat"):
            data[key] = value.isoformat()
        elif hasattr(value, "as_tuple"):
            data[key] = float(value)
    if object_type == "paper":
        data["abstract_basis_label"] = "基于摘要" if data.get("abstract") else None
    return {"type": object_type, "id": object_id, "data": data}


def maintain_research_graph_jobs(repository) -> dict:
    if not _is_postgres(repository):
        return {"enqueued": 0, "deleted": 0}
    with repository.engine.begin() as conn:
        conn.execute(text("""
            with expired as (
                update public.research_graph_refresh_jobs
                set status = case
                        when attempts < 3 then 'pending' else 'failed'
                    end,
                    scheduled_at = case
                        when attempts < 3 then now() else scheduled_at
                    end,
                    finished_at = case
                        when attempts < 3 then null else now()
                    end,
                    locked_at = null,
                    last_error = 'worker lease expired',
                    updated_at = now()
                where status = 'running'
                  and locked_at < now() - interval '30 minutes'
                returning scholar_id, status, last_error
            )
            update public.research_graph_sync_state gs
            set status = case
                    when expired.status = 'pending' then 'queued' else 'failed'
                end,
                last_error = expired.last_error,
                updated_at = now()
            from expired
            where gs.scholar_id = expired.scholar_id
        """))
        enqueued = conn.execute(text("""
            insert into public.research_graph_refresh_jobs (
                scholar_id, requested_by_user_id, reason, status, scheduled_at
            )
            select s.id, requester.user_id, 'stale_graph', 'pending', now()
            from public.scholars s
            cross join lateral (
                select candidate.user_id
                from (
                    select f.user_id, 0 as priority, f.created_at as activity_at
                    from public.favorites f
                    where f.scholar_id = s.id
                    union all
                    select h.user_id, 1 as priority, h.last_viewed_at as activity_at
                    from public.user_history h
                    where h.scholar_id = s.id
                ) candidate
                order by candidate.priority, candidate.activity_at desc
                limit 1
            ) requester
            left join public.research_graph_sync_state gs on gs.scholar_id = s.id
            where (gs.status is null or gs.status <> 'failed')
              and (
                  gs.last_success_at is null
                  or gs.last_success_at < now() - interval '7 days'
              )
            on conflict do nothing
        """)).rowcount
        conn.execute(text("""
            insert into public.research_graph_sync_state (
                scholar_id, status, updated_at
            )
            select scholar_id, 'queued', now()
            from public.research_graph_refresh_jobs
            where status = 'pending'
            on conflict (scholar_id) do update set
                status = case
                    when research_graph_sync_state.status = 'updating'
                    then 'updating' else 'queued' end,
                updated_at = now()
        """))
        deleted = conn.execute(text("""
            delete from public.research_graph_refresh_jobs
            where status in ('succeeded', 'failed')
              and updated_at < now() - interval '30 days'
        """)).rowcount
    return {"enqueued": enqueued, "deleted": deleted}
