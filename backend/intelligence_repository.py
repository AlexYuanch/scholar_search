"""Read-only projection of the dynamic research graph for intelligence analysis.

The projection deliberately contains no independently persisted scholarly facts.
It is assembled from the stage-2 graph tables (or their in-memory test mirror)
on every request.  The only write in this module is user-owned usefulness
feedback.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import text

from affiliation_evidence import select_primary_affiliation


MAX_FIELD_CANDIDATES = 160
MAX_WORKS_PER_SCHOLAR = 300


def _iso(value: Any = None) -> str:
    if isinstance(value, str):
        return value
    return (value or datetime.now(timezone.utc)).isoformat()


def _revision_value(value: Any) -> str:
    return value.isoformat() if hasattr(value, "isoformat") else str(value or "")


def _discovery_revision(author_id: str, state: dict) -> tuple:
    return (
        author_id,
        str(state.get("status") or ""),
        int(state.get("version") or 0),
        _revision_value(state.get("updated_at")),
        int(state.get("analyzed_count") or 0),
        int(state.get("attempted_count") or 0),
    )


def _memory_snapshot_token(repository, requested_ids: tuple[str, ...]) -> tuple:
    graph_states = (
        (getattr(repository, "_research_graph_store", None) or {})
        .get("sync", {})
    )
    graph_token = tuple(sorted(
        (
            author_id,
            str(state.get("status") or ""),
            int(state.get("version") or 0),
            str(state.get("updated_at") or ""),
            str(state.get("data_fingerprint") or ""),
        )
        for author_id, state in graph_states.items()
    ))
    discovery_states = (
        (getattr(repository, "_field_discovery_store", None) or {})
        .get("states", {})
    )
    discovery_token = tuple(
        _discovery_revision(
            author_id,
            discovery_states.get(author_id) or {},
        )
        for author_id in requested_ids
    )
    return ("memory", graph_token, discovery_token)


def _postgres_snapshot_token(repository, requested_ids: tuple[str, ...]) -> tuple:
    with repository.engine.connect() as conn:
        graph = conn.execute(text("""
            select count(*)::integer as state_count,
                   coalesce(sum(version), 0)::bigint as version_total,
                   max(updated_at) as latest_update,
                   count(*) filter (where status = 'ready')::integer as ready_count,
                   count(*) filter (
                       where status in ('queued', 'updating')
                   )::integer as active_count,
                   count(*) filter (where status = 'failed')::integer as failed_count
            from public.research_graph_sync_state
        """)).mappings().one()
        discovery_rows = []
        if requested_ids:
            placeholders = ", ".join(
                f":author_id_{index}"
                for index in range(len(requested_ids))
            )
            discovery_rows = conn.execute(text(f"""
                select s.source_author_id as author_id, fds.status, fds.version,
                       fds.updated_at, fds.analyzed_count, fds.attempted_count
                from public.scholars s
                left join public.field_discovery_state fds
                    on fds.focus_scholar_id = s.id
                where s.source = 'openalex'
                  and s.source_author_id in ({placeholders})
                order by s.source_author_id
            """), {
                f"author_id_{index}": author_id
                for index, author_id in enumerate(requested_ids)
            }).mappings().all()
    graph_token = (
        int(graph["state_count"] or 0),
        int(graph["version_total"] or 0),
        _revision_value(graph["latest_update"]),
        int(graph["ready_count"] or 0),
        int(graph["active_count"] or 0),
        int(graph["failed_count"] or 0),
    )
    rows_by_author = {
        row["author_id"]: row
        for row in discovery_rows
    }
    discovery_token = tuple(
        _discovery_revision(
            author_id,
            rows_by_author.get(author_id) or {},
        )
        for author_id in requested_ids
    )
    return ("postgres", graph_token, discovery_token)


def intelligence_snapshot_token(
    repository,
    author_ids: list[str] | tuple[str, ...],
) -> tuple:
    """Return a cheap revision token for deterministic intelligence inputs."""
    requested_ids = tuple(sorted(set(author_ids)))
    if hasattr(repository, "engine"):
        return _postgres_snapshot_token(repository, requested_ids)
    return _memory_snapshot_token(repository, requested_ids)


def _empty_scholar(
    author_id: str,
    *,
    scholar_id: str = "",
    name: str = "",
    orcid: str | None = None,
    graph_ready: bool = False,
    graph_version: int = 0,
) -> dict:
    return {
        "id": scholar_id or author_id,
        "author_id": author_id,
        "name": name or author_id,
        "orcid": orcid,
        "graph_ready": graph_ready,
        "graph_version": graph_version,
        "work_ids": [],
        "authorships": {},
        "affiliations": [],
        "collaborations": {},
    }


def _finalize_dataset(dataset: dict, focus_author_id: str) -> dict:
    years = [
        work.get("year")
        for work in dataset["works"].values()
        if isinstance(work.get("year"), int)
    ]
    dataset["as_of_year"] = max(years) if years else None
    dataset["focus_author_id"] = focus_author_id
    for scholar in dataset["scholars"].values():
        scholar["work_ids"] = sorted(set(scholar["work_ids"]))
        primary_affiliation = select_primary_affiliation(
            scholar["affiliations"]
        )
        scholar["affiliations"].sort(
            key=lambda item: (
                (item.get("name") or "") == primary_affiliation,
                bool(item.get("is_current") or item.get("is_last_known")),
                item.get("end_year") or 0,
                len(item.get("years") or []),
                item.get("name") or "",
            ),
            reverse=True,
        )
    return dataset


def _memory_dataset(repository, focus_author_id: str) -> dict:
    store = getattr(repository, "_research_graph_store", None) or {}
    authors = store.get("authors", {})
    sync = store.get("sync", {})
    scholars: dict[str, dict] = {}

    authored_counts = Counter(author_id for _, author_id in store.get("authorships", {}))
    for author_id, author in authors.items():
        if not authored_counts.get(author_id) and author_id != focus_author_id:
            continue
        state = sync.get(author_id, {})
        scholars[author_id] = _empty_scholar(
            author_id,
            scholar_id=(
                (getattr(repository, "scholars", {}).get(author_id) or {}).get("id")
                or author_id
            ),
            name=author.get("display_name") or author_id,
            orcid=author.get("orcid"),
            graph_ready=bool(state.get("last_success_at")),
            graph_version=int(state.get("version") or 0),
        )

    if focus_author_id not in scholars:
        author = authors.get(focus_author_id, {})
        state = sync.get(focus_author_id, {})
        scholars[focus_author_id] = _empty_scholar(
            focus_author_id,
            scholar_id=(
                (getattr(repository, "scholars", {}).get(focus_author_id) or {}).get("id")
                or focus_author_id
            ),
            name=author.get("display_name") or focus_author_id,
            orcid=author.get("orcid"),
            graph_ready=bool(state.get("last_success_at")),
            graph_version=int(state.get("version") or 0),
        )

    author_counts_by_work = Counter(work_id for work_id, _ in store.get("authorships", {}))
    works: dict[str, dict] = {}
    for work_id, raw in store.get("works", {}).items():
        insight = deepcopy(store.get("insights", {}).get(work_id) or {})
        topics = []
        for related_work_id, topic_id in store.get("work_topics", {}):
            if related_work_id != work_id:
                continue
            topic = store.get("topics", {}).get(topic_id) or {}
            topics.append({
                "id": topic_id,
                "source_id": topic.get("source_topic_id") or topic_id,
                "name": topic.get("display_name") or topic_id,
                "is_primary": bool(
                    store["work_topics"][(related_work_id, topic_id)].get("is_primary")
                ),
                "confidence": float(
                    store["work_topics"][(related_work_id, topic_id)].get("confidence")
                    or 0
                ),
            })
        works[work_id] = {
            "id": work_id,
            "source_id": raw.get("source_work_id") or work_id,
            "title": raw.get("title") or raw.get("source_work_id") or work_id,
            "year": raw.get("publication_year"),
            "publication_date": raw.get("publication_date"),
            "citations": max(0, int(raw.get("cited_by_count") or 0)),
            "venue": raw.get("venue"),
            "work_type": raw.get("work_type"),
            "topics": sorted(
                topics,
                key=lambda item: (
                    not item["is_primary"],
                    item["name"].casefold(),
                ),
            ),
            "insight": insight,
            "author_count": int(author_counts_by_work.get(work_id) or 0),
        }

    for (work_id, author_id), authorship in store.get("authorships", {}).items():
        scholar = scholars.get(author_id)
        if not scholar or work_id not in works:
            continue
        scholar["work_ids"].append(work_id)
        scholar["authorships"][work_id] = {
            "author_position": authorship.get("author_position"),
            "position_index": authorship.get("position_index"),
            "is_corresponding": bool(authorship.get("is_corresponding")),
            "author_count": works[work_id]["author_count"],
        }

    for (author_id, institution_id), relation in store.get("affiliations", {}).items():
        if author_id not in scholars:
            continue
        institution = store.get("institutions", {}).get(institution_id) or {}
        scholars[author_id]["affiliations"].append({
            "id": institution_id,
            "source_id": institution.get("id") or institution_id,
            "name": institution.get("display_name") or institution_id,
            "country_code": institution.get("country_code"),
            "years": list(relation.get("years") or []),
            "start_year": relation.get("start_year"),
            "end_year": relation.get("end_year"),
            "is_current": bool(relation.get("is_current")),
            "is_last_known": bool(relation.get("is_last_known")),
        })

    for pair, relation in store.get("collaborations", {}).items():
        left, right = pair
        for author_id, other_id in ((left, right), (right, left)):
            if author_id not in scholars:
                continue
            other = authors.get(other_id) or {}
            scholars[author_id]["collaborations"][other_id] = {
                "author_id": other_id,
                "name": other.get("display_name") or other_id,
                "works_count": int(relation.get("works_count") or 0),
                "first_year": relation.get("first_year"),
                "last_year": relation.get("last_year"),
            }

    citations = []
    for relation in store.get("citations", {}).values():
        cited_work_id = relation.get("cited_work_id")
        citing_work_id = relation.get("citing_work_id")
        if citing_work_id in works and cited_work_id in works:
            citations.append({
                "citing_work_id": citing_work_id,
                "cited_work_id": cited_work_id,
            })

    field_candidates = getattr(
        repository,
        "_field_discovery_store",
        {},
    ).get("candidates", {})
    return _finalize_dataset({
        "scholars": scholars,
        "works": works,
        "citations": citations,
        "field_candidate_ids": [
            candidate_id
            for (related_focus_id, candidate_id) in field_candidates
            if related_focus_id == focus_author_id
        ],
        "source": "dynamic_research_graph",
    }, focus_author_id)


def _postgres_dataset(
    repository,
    focus_author_id: str,
    extra_author_ids: list[str] | None,
) -> dict:
    required_source_ids = list(dict.fromkeys([
        focus_author_id,
        *(extra_author_ids or []),
    ]))
    with repository.engine.connect() as conn:
        required_rows = conn.execute(text("""
            select id, source_author_id
            from public.scholars
            where source = 'openalex'
              and source_author_id = any(cast(:source_ids as text[]))
        """), {"source_ids": required_source_ids}).mappings().all()
        required_ids = [str(row["id"]) for row in required_rows]
        focus_row = next(
            (row for row in required_rows if row["source_author_id"] == focus_author_id),
            None,
        )
        if not focus_row:
            return _finalize_dataset({
                "scholars": {
                    focus_author_id: _empty_scholar(focus_author_id),
                },
                "works": {},
                "citations": [],
                "source": "dynamic_research_graph",
            }, focus_author_id)
        focus_id = str(focus_row["id"])

        topic_ids = [
            str(row[0])
            for row in conn.execute(text("""
                select topic_id
                from public.scholar_topics
                where scholar_id = cast(:focus_id as uuid)
                order by works_count desc, last_year desc nulls last, topic_id
                limit 10
            """), {"focus_id": focus_id}).all()
        ]
        if not topic_ids:
            topic_ids = [
                str(row[0])
                for row in conn.execute(text("""
                    select wt.topic_id
                    from public.authorships a
                    join public.work_topics wt on wt.work_id = a.work_id
                    where a.scholar_id = cast(:focus_id as uuid)
                    group by wt.topic_id
                    order by count(distinct a.work_id) desc, wt.topic_id
                    limit 10
                """), {"focus_id": focus_id}).all()
            ]

        candidate_ids = set(required_ids)
        discovery_rows = conn.execute(text("""
            select fdc.candidate_scholar_id, candidate.source_author_id
            from public.field_discovery_candidates fdc
            join public.scholars candidate
                on candidate.id = fdc.candidate_scholar_id
            where fdc.focus_scholar_id = cast(:focus_id as uuid)
            order by fdc.discovery_rank
            limit :limit
        """), {
            "focus_id": focus_id,
            "limit": MAX_FIELD_CANDIDATES,
        }).mappings().all()
        candidate_ids.update(
            str(row["candidate_scholar_id"])
            for row in discovery_rows
        )
        field_candidate_ids = [
            str(row["source_author_id"])
            for row in discovery_rows
        ]
        if topic_ids:
            rows = conn.execute(text("""
                select a.scholar_id, count(distinct a.work_id) as matched_works
                from public.authorships a
                join public.work_topics wt on wt.work_id = a.work_id
                join public.paper_insights pi on pi.work_id = a.work_id
                where wt.topic_id = any(cast(:topic_ids as uuid[]))
                group by a.scholar_id
                order by matched_works desc, a.scholar_id
                limit :limit
            """), {
                "topic_ids": topic_ids,
                "limit": MAX_FIELD_CANDIDATES,
            }).mappings().all()
            candidate_ids.update(str(row["scholar_id"]) for row in rows)

        direct_rows = conn.execute(text("""
            select case
                when scholar_a_id = cast(:focus_id as uuid)
                then scholar_b_id else scholar_a_id
            end as scholar_id
            from public.collaborations
            where scholar_a_id = cast(:focus_id as uuid)
               or scholar_b_id = cast(:focus_id as uuid)
            order by works_count desc, last_year desc nulls last
            limit 80
        """), {"focus_id": focus_id}).all()
        candidate_ids.update(str(row[0]) for row in direct_rows)
        candidate_ids_list = sorted(candidate_ids)

        author_rows = conn.execute(text("""
            select s.id, s.source_author_id, s.display_name, s.orcid,
                   gs.last_success_at, coalesce(gs.version, 0) as graph_version
            from public.scholars s
            left join public.research_graph_sync_state gs on gs.scholar_id = s.id
            where s.id = any(cast(:candidate_ids as uuid[]))
            order by s.source_author_id
        """), {"candidate_ids": candidate_ids_list}).mappings().all()
        scholars = {
            row["source_author_id"]: _empty_scholar(
                row["source_author_id"],
                scholar_id=str(row["id"]),
                name=row["display_name"],
                orcid=row["orcid"],
                graph_ready=bool(row["last_success_at"]),
                graph_version=int(row["graph_version"] or 0),
            )
            for row in author_rows
        }
        source_by_uuid = {
            str(row["id"]): row["source_author_id"]
            for row in author_rows
        }

        work_rows = conn.execute(text("""
            with ranked as (
                select a.scholar_id, a.work_id, a.author_position,
                       a.position_index, a.is_corresponding,
                       w.source_work_id, w.title, w.publication_year,
                       w.publication_date, w.cited_by_count, w.venue,
                       w.work_type,
                       pi.problem, pi.core_method, pi.main_contribution,
                       pi.topic_relationship, pi.abstract_evidence,
                       pi.based_on_abstract, pi.confidence as insight_confidence,
                       (
                           select count(*)::integer
                           from public.authorships all_authors
                           where all_authors.work_id = a.work_id
                       ) as author_count,
                       row_number() over (
                           partition by a.scholar_id
                           order by w.publication_year desc nulls last,
                                    w.cited_by_count desc, w.id
                       ) as row_number
                from public.authorships a
                join public.works w on w.id = a.work_id
                join public.paper_insights pi on pi.work_id = w.id
                where a.scholar_id = any(cast(:candidate_ids as uuid[]))
            )
            select *
            from ranked
            where row_number <= :max_works
            order by scholar_id, row_number
        """), {
            "candidate_ids": candidate_ids_list,
            "max_works": MAX_WORKS_PER_SCHOLAR,
        }).mappings().all()

        works: dict[str, dict] = {}
        for row in work_rows:
            work_id = str(row["work_id"])
            works.setdefault(work_id, {
                "id": work_id,
                "source_id": row["source_work_id"],
                "title": row["title"],
                "year": row["publication_year"],
                "publication_date": (
                    row["publication_date"].isoformat()
                    if row["publication_date"]
                    else None
                ),
                "citations": max(0, int(row["cited_by_count"] or 0)),
                "venue": row["venue"],
                "work_type": row["work_type"],
                "topics": [],
                "insight": {
                    "problem": row["problem"],
                    "core_method": row["core_method"],
                    "main_contribution": row["main_contribution"],
                    "topic_relationship": row["topic_relationship"],
                    "abstract_evidence": row["abstract_evidence"] or [],
                    "based_on_abstract": bool(row["based_on_abstract"]),
                    "confidence": float(row["insight_confidence"] or 0),
                },
                "author_count": int(row["author_count"] or 0),
            })
            author_id = source_by_uuid.get(str(row["scholar_id"]))
            if not author_id:
                continue
            scholars[author_id]["work_ids"].append(work_id)
            scholars[author_id]["authorships"][work_id] = {
                "author_position": row["author_position"],
                "position_index": row["position_index"],
                "is_corresponding": bool(row["is_corresponding"]),
                "author_count": int(row["author_count"] or 0),
            }

        work_ids = sorted(works)
        if work_ids:
            topic_rows = conn.execute(text("""
                select wt.work_id, t.id, t.source_topic_id, t.display_name, wt.is_primary,
                       wt.confidence
                from public.work_topics wt
                join public.research_topics t on t.id = wt.topic_id
                where wt.work_id = any(cast(:work_ids as uuid[]))
                order by wt.work_id, wt.is_primary desc,
                         wt.score desc nulls last, t.display_name
            """), {"work_ids": work_ids}).mappings().all()
            for row in topic_rows:
                works[str(row["work_id"])]["topics"].append({
                    "id": str(row["id"]),
                    "source_id": row["source_topic_id"],
                    "name": row["display_name"],
                    "is_primary": bool(row["is_primary"]),
                    "confidence": float(row["confidence"] or 0),
                })

        affiliation_rows = conn.execute(text("""
            select si.scholar_id, i.id, i.source_institution_id,
                   i.display_name, i.country_code, si.years, si.start_year,
                   si.end_year, si.is_current, si.is_last_known
            from public.scholar_institutions si
            join public.institutions i on i.id = si.institution_id
            where si.scholar_id = any(cast(:candidate_ids as uuid[]))
            order by si.scholar_id, si.is_current desc,
                     si.end_year desc nulls last, i.display_name
        """), {"candidate_ids": candidate_ids_list}).mappings().all()
        for row in affiliation_rows:
            author_id = source_by_uuid.get(str(row["scholar_id"]))
            if not author_id:
                continue
            scholars[author_id]["affiliations"].append({
                "id": str(row["id"]),
                "source_id": row["source_institution_id"],
                "name": row["display_name"],
                "country_code": row["country_code"],
                "years": list(row["years"] or []),
                "start_year": row["start_year"],
                "end_year": row["end_year"],
                "is_current": bool(row["is_current"]),
                "is_last_known": bool(row["is_last_known"]),
            })

        collaboration_rows = conn.execute(text("""
            select c.scholar_a_id, a.source_author_id as author_a_id,
                   a.display_name as author_a_name,
                   c.scholar_b_id, b.source_author_id as author_b_id,
                   b.display_name as author_b_name,
                   c.works_count, c.first_year, c.last_year
            from public.collaborations c
            join public.scholars a on a.id = c.scholar_a_id
            join public.scholars b on b.id = c.scholar_b_id
            where c.scholar_a_id = any(cast(:candidate_ids as uuid[]))
               or c.scholar_b_id = any(cast(:candidate_ids as uuid[]))
        """), {"candidate_ids": candidate_ids_list}).mappings().all()
        for row in collaboration_rows:
            for author_id, other_id, other_name in (
                (row["author_a_id"], row["author_b_id"], row["author_b_name"]),
                (row["author_b_id"], row["author_a_id"], row["author_a_name"]),
            ):
                if author_id not in scholars:
                    continue
                scholars[author_id]["collaborations"][other_id] = {
                    "author_id": other_id,
                    "name": other_name,
                    "works_count": int(row["works_count"] or 0),
                    "first_year": row["first_year"],
                    "last_year": row["last_year"],
                }

        citations = []
        if work_ids:
            citation_rows = conn.execute(text("""
                select citing_work_id, cited_work_id
                from public.work_citations
                where citing_work_id = any(cast(:work_ids as uuid[]))
                  and cited_work_id = any(cast(:work_ids as uuid[]))
                  and cited_work_id is not null
            """), {"work_ids": work_ids}).mappings().all()
            citations = [{
                "citing_work_id": str(row["citing_work_id"]),
                "cited_work_id": str(row["cited_work_id"]),
            } for row in citation_rows]

    return _finalize_dataset({
        "scholars": scholars,
        "works": works,
        "citations": citations,
        "field_candidate_ids": field_candidate_ids,
        "source": "dynamic_research_graph",
    }, focus_author_id)


def load_intelligence_dataset(
    repository,
    focus_author_id: str,
    *,
    extra_author_ids: list[str] | None = None,
) -> dict:
    if hasattr(repository, "engine"):
        return _postgres_dataset(repository, focus_author_id, extra_author_ids)
    return _memory_dataset(repository, focus_author_id)


def save_intelligence_feedback(
    repository,
    *,
    user_id: str,
    target_author_id: str,
    candidate_author_id: str | None,
    analysis_key: str,
    verdict: str,
    analysis_version: str,
    context: dict | None = None,
) -> dict:
    candidate_key = candidate_author_id or ""
    if not hasattr(repository, "engine"):
        store = getattr(repository, "_intelligence_feedback", None)
        if store is None:
            store = {}
            repository._intelligence_feedback = store
        key = (
            user_id,
            target_author_id,
            candidate_key,
            analysis_key,
            analysis_version,
        )
        row = store.get(key) or {
            "id": str(uuid4()),
            "created_at": _iso(),
        }
        row.update({
            "user_id": user_id,
            "target_author_id": target_author_id,
            "candidate_author_id": candidate_key,
            "analysis_key": analysis_key,
            "verdict": verdict,
            "analysis_version": analysis_version,
            "context": deepcopy(context or {}),
            "updated_at": _iso(),
        })
        store[key] = row
        return deepcopy(row)

    import json

    with repository.engine.begin() as conn:
        row = conn.execute(text("""
            insert into public.scholar_intelligence_feedback (
                user_id, target_author_id, candidate_author_id, analysis_key,
                verdict, analysis_version, context, updated_at
            ) values (
                cast(:user_id as uuid), :target_author_id,
                :candidate_author_id, :analysis_key, :verdict,
                :analysis_version, cast(:context as jsonb), now()
            )
            on conflict (
                user_id, target_author_id, candidate_author_id,
                analysis_key, analysis_version
            ) do update set
                verdict = excluded.verdict,
                context = excluded.context,
                updated_at = now()
            returning id, created_at, updated_at
        """), {
            "user_id": user_id,
            "target_author_id": target_author_id,
            "candidate_author_id": candidate_key,
            "analysis_key": analysis_key,
            "verdict": verdict,
            "analysis_version": analysis_version,
            "context": json.dumps(context or {}, ensure_ascii=False),
        }).mappings().one()
    return {
        "id": str(row["id"]),
        "user_id": user_id,
        "target_author_id": target_author_id,
        "candidate_author_id": candidate_key,
        "analysis_key": analysis_key,
        "verdict": verdict,
        "analysis_version": analysis_version,
        "created_at": _iso(row["created_at"]),
        "updated_at": _iso(row["updated_at"]),
    }
