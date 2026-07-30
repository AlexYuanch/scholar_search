"""Evidence-bounded construction and incremental refresh of a scholar research graph."""
from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from typing import Any

from crossref import normalize_doi, verify_dois
from openalex import (
    get_author,
    get_graph_works,
    get_provisional_author_bundle,
    is_provisional_author_id,
)


GRAPH_ANALYZER_VERSION = "abstract-extractive-v1"
GRAPH_INCREMENTAL_OVERLAP_DAYS = 30


class IncompleteGraphSync(RuntimeError):
    """Raised before persistence when an OpenAlex page sequence is incomplete."""


def _text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _year(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if 1000 <= parsed <= 3000 else None


def _iso_datetime(value: Any) -> str | None:
    if not value:
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()


def reconstruct_openalex_abstract(inverted_index: Any) -> str | None:
    """Reconstruct OpenAlex's inverted abstract without adding any words."""
    if not isinstance(inverted_index, dict) or not inverted_index:
        return None
    positioned: list[tuple[int, str]] = []
    for word, positions in inverted_index.items():
        if not isinstance(positions, list):
            continue
        for position in positions:
            try:
                positioned.append((int(position), str(word)))
            except (TypeError, ValueError):
                continue
    if not positioned:
        return None
    positioned.sort(key=lambda item: item[0])
    return " ".join(word for _, word in positioned).strip() or None


def _sentences(abstract: str) -> list[str]:
    values = [
        _text(item)
        for item in re.split(r"(?<=[.!?。！？])\s+", abstract)
        if _text(item)
    ]
    if len(values) == 1 and len(values[0]) > 900:
        values = [_text(item) for item in re.split(r"[;；]\s*", values[0]) if _text(item)]
    return values[:40]


def _select_sentence(sentences: list[str], patterns: tuple[str, ...]) -> str | None:
    for sentence in sentences:
        normalized = sentence.casefold()
        if any(pattern in normalized for pattern in patterns):
            return sentence[:800]
    return None


def understand_abstract(abstract: str | None, topics: list[dict]) -> dict:
    """Return extractive fields only; missing abstract yields no inferred content."""
    if not abstract:
        return {
            "problem": None,
            "core_method": None,
            "main_contribution": None,
            "topic_relationship": None,
            "abstract_evidence": [],
            "based_on_abstract": False,
            "analyzer_version": GRAPH_ANALYZER_VERSION,
            "source": "openalex_abstract",
            "confidence": 0.0,
        }

    sentences = _sentences(abstract)
    problem = _select_sentence(sentences, (
        "we address", "this paper addresses", "challenge", "problem", "we aim",
        "our goal", "研究问题", "问题", "挑战", "目标",
    )) or (sentences[0][:800] if sentences else None)
    method = _select_sentence(sentences, (
        "we propose", "we present", "our method", "approach", "framework",
        "algorithm", "model", "方法", "提出", "框架", "算法", "模型",
    ))
    contribution = _select_sentence(sentences, (
        "we show", "we demonstrate", "results show", "our results", "outperform",
        "contribution", "结果表明", "实验表明", "贡献", "优于",
    ))

    abstract_folded = abstract.casefold()
    matched_topics = [
        _text(topic.get("display_name"))
        for topic in topics
        if _text(topic.get("display_name"))
        and _text(topic.get("display_name")).casefold() in abstract_folded
    ]
    unique_matched_topics = list(dict.fromkeys(matched_topics))
    topic_relationship = (
        "摘要直接提及：" + "、".join(unique_matched_topics[:5])
        if matched_topics
        else None
    )

    evidence = []
    for field, sentence in (
        ("problem", problem),
        ("core_method", method),
        ("main_contribution", contribution),
    ):
        if sentence and not any(item["text"] == sentence for item in evidence):
            evidence.append({"field": field, "text": sentence})
    if matched_topics:
        evidence.append({
            "field": "topic_relationship",
            "text": "；".join(unique_matched_topics[:5]),
        })
    return {
        "problem": problem,
        "core_method": method,
        "main_contribution": contribution,
        "topic_relationship": topic_relationship,
        "abstract_evidence": evidence,
        "based_on_abstract": True,
        "analyzer_version": GRAPH_ANALYZER_VERSION,
        "source": "openalex_abstract",
        "confidence": 0.7,
    }


def _topic_records(work: dict) -> list[dict]:
    primary_id = str((work.get("primary_topic") or {}).get("id") or "")
    values = []
    seen = set()
    candidates = [work.get("primary_topic") or {}, *(work.get("topics") or [])]
    for topic in candidates:
        source_id = str(topic.get("id") or "")
        name = _text(topic.get("display_name"))
        key = source_id or name.casefold()
        if not key or not name or key in seen:
            continue
        seen.add(key)
        values.append({
            "source": "openalex",
            "source_topic_id": source_id or f"name:{name.casefold()}",
            "display_name": name,
            "description": _text(topic.get("description")) or None,
            "score": topic.get("score"),
            "is_primary": bool(source_id and source_id == primary_id),
            "confidence": 0.9 if source_id else 0.7,
            "raw": deepcopy(topic),
        })
    return values


def _authorship_records(
    work: dict,
    *,
    target_author_ids: set[str],
    target_author: dict,
) -> list[dict]:
    values = []
    for index, authorship in enumerate(work.get("authorships") or []):
        author = authorship.get("author") or {}
        author_id = str(author.get("id") or "")
        if not author_id:
            continue
        normalized_author = (
            {
                "id": target_author["id"],
                "display_name": target_author.get("display_name")
                or author.get("display_name")
                or "?",
                "orcid": target_author.get("orcid"),
            }
            if author_id in target_author_ids
            else deepcopy(author)
        )
        institutions = []
        for institution in authorship.get("institutions") or []:
            if institution.get("id"):
                institutions.append({
                    **deepcopy(institution),
                    "years": [_year(work.get("publication_year"))]
                    if _year(work.get("publication_year"))
                    else [],
                })
        values.append({
            "author": normalized_author,
            "source_author_id": author_id,
            "author_position": authorship.get("author_position"),
            "position_index": index,
            "is_corresponding": bool(authorship.get("is_corresponding")),
            "institutions": institutions,
            "source": "openalex",
            "confidence": 0.95,
        })
    return values


def _author_affiliations(author: dict) -> list[dict]:
    by_id: dict[str, dict] = {}
    last_known_ids = {
        str(item.get("id"))
        for item in author.get("last_known_institutions") or []
        if item.get("id")
    }
    for affiliation in author.get("affiliations") or []:
        institution = deepcopy(affiliation.get("institution") or {})
        source_id = str(institution.get("id") or "")
        if not source_id:
            continue
        years = sorted(set(filter(None, (_year(value) for value in affiliation.get("years") or []))))
        by_id[source_id] = {
            "institution": institution,
            "years": years,
            "start_year": min(years) if years else None,
            "end_year": max(years) if years else None,
            "is_last_known": source_id in last_known_ids,
            "is_current": source_id in last_known_ids,
            "source": "openalex",
            "confidence": 0.9 if years else 0.8,
            "source_records": [{"source": "openalex_author_affiliations", "years": years}],
        }
    for institution in author.get("last_known_institutions") or []:
        source_id = str(institution.get("id") or "")
        if not source_id:
            continue
        row = by_id.setdefault(source_id, {
            "institution": deepcopy(institution),
            "years": [],
            "start_year": None,
            "end_year": None,
            "source": "openalex",
            "confidence": 0.8,
            "source_records": [{"source": "openalex_last_known_institutions"}],
        })
        row["is_last_known"] = True
        row["is_current"] = True
    return list(by_id.values())


def _merge_work(left: dict, right: dict) -> dict:
    """Merge duplicate stable identifiers without replacing populated evidence."""
    richer, other = (
        (left, right)
        if len(json.dumps(left, ensure_ascii=False)) >= len(json.dumps(right, ensure_ascii=False))
        else (right, left)
    )
    merged = deepcopy(richer)
    for key, value in other.items():
        if key not in merged or merged[key] in (None, "", [], {}):
            merged[key] = deepcopy(value)
    return merged


def deduplicate_graph_works(works: list[dict]) -> list[dict]:
    by_key: dict[str, dict] = {}
    aliases: dict[str, str] = {}
    for work in works:
        openalex_id = str(work.get("id") or "").strip()
        doi = normalize_doi(work.get("doi"))
        candidate = deepcopy(work)
        candidate["_openalex_ids"] = [openalex_id] if openalex_id else []
        candidate["_normalized_dois"] = [doi] if doi else []
        keys = [key for key in (f"doi:{doi}" if doi else "", f"openalex:{openalex_id}" if openalex_id else "") if key]
        if not keys:
            continue
        matched_canonicals = list(dict.fromkeys(
            aliases[key] for key in keys if key in aliases
        ))
        canonical = matched_canonicals[0] if matched_canonicals else keys[0]
        matched_records = [
            by_key.pop(matched)
            for matched in matched_canonicals
            if matched in by_key
        ]
        all_openalex_ids = list(candidate["_openalex_ids"])
        all_normalized_dois = list(candidate["_normalized_dois"])
        merged = candidate
        for matched_record in matched_records:
            all_openalex_ids.extend(matched_record.get("_openalex_ids") or [])
            all_normalized_dois.extend(
                matched_record.get("_normalized_dois") or []
            )
            merged = _merge_work(matched_record, merged)
        merged["_openalex_ids"] = list(dict.fromkeys(all_openalex_ids))
        merged["_normalized_dois"] = list(dict.fromkeys(all_normalized_dois))
        by_key[canonical] = merged
        if matched_canonicals:
            matched_set = set(matched_canonicals)
            for alias, target in list(aliases.items()):
                if target in matched_set:
                    aliases[alias] = canonical
        for key in keys:
            aliases[key] = canonical
    return list(by_key.values())


def build_research_graph_batch(
    author: dict,
    works: list[dict],
    crossref_records: dict[str, dict] | None = None,
    crossref_report: dict[str, int] | None = None,
    target_author_ids: list[str] | None = None,
) -> dict:
    """Build a deterministic persistence batch from complete upstream responses."""
    target_author_id = str(author.get("id") or "")
    if not target_author_id:
        raise ValueError("OpenAlex author id is required")
    normalized_target_author_ids = set(target_author_ids or [target_author_id])
    normalized_target_author_ids.add(target_author_id)
    verified_crossref = crossref_records or {}
    normalized_works = []
    topic_aggregate: dict[str, dict] = {}
    collaboration_aggregate: dict[str, dict] = {}
    timeline = []
    source_watermarks = []

    for raw_work in deduplicate_graph_works(works):
        openalex_id = str(raw_work.get("id") or "")
        if not openalex_id:
            continue
        doi = normalize_doi(raw_work.get("doi"))
        crossref = verified_crossref.get(doi, {})
        topics = _topic_records(raw_work)
        abstract = reconstruct_openalex_abstract(raw_work.get("abstract_inverted_index"))
        publication_year = _year(
            raw_work.get("publication_year") or crossref.get("publication_year")
        )
        publication_date = raw_work.get("publication_date")
        venue = (
            _text(crossref.get("journal"))
            or _text(((raw_work.get("primary_location") or {}).get("source") or {}).get("display_name"))
        )
        metadata_sources = ["openalex"]
        if crossref:
            metadata_sources.append("crossref")
        source_updated_at = _iso_datetime(raw_work.get("updated_date"))
        if source_updated_at:
            source_watermarks.append(source_updated_at)
        authorships = _authorship_records(
            raw_work,
            target_author_ids=normalized_target_author_ids,
            target_author=author,
        )
        insight = understand_abstract(abstract, topics)
        normalized_work = {
            "source_work_id": openalex_id,
            "external_openalex_ids": list(dict.fromkeys([
                openalex_id,
                *(raw_work.get("_openalex_ids") or []),
            ])),
            "doi": doi or None,
            "title": _text(crossref.get("title")) or _text(raw_work.get("title")) or openalex_id,
            "publication_year": publication_year,
            "publication_date": publication_date,
            "cited_by_count": max(0, int(raw_work.get("cited_by_count") or 0)),
            "abstract": abstract,
            "venue": venue or None,
            "work_type": _text(raw_work.get("type")) or _text(crossref.get("type")) or None,
            "language": _text(raw_work.get("language")) or None,
            "source_updated_at": source_updated_at,
            "metadata_sources": metadata_sources,
            "confidence": 0.95 if crossref else 0.9,
            "raw": deepcopy(raw_work),
            "authorships": authorships,
            "topics": topics,
            "referenced_work_ids": list(dict.fromkeys(
                str(value) for value in raw_work.get("referenced_works") or [] if value
            )),
            "insight": insight,
        }
        normalized_works.append(normalized_work)

        if publication_year:
            timeline.append({
                "event_key": f"paper:{openalex_id}",
                "event_type": "paper_published",
                "event_year": publication_year,
                "event_date": publication_date,
                "title": normalized_work["title"],
                "description": venue or "",
                "work_source_id": openalex_id,
                "source": "openalex",
                "confidence": 0.95,
            })

        for topic in topics:
            key = topic["source_topic_id"]
            aggregate = topic_aggregate.setdefault(key, {
                **deepcopy(topic),
                "years": set(),
                "work_ids": set(),
            })
            aggregate["work_ids"].add(openalex_id)
            if publication_year:
                aggregate["years"].add(publication_year)

        for authorship in authorships:
            coauthor = authorship["author"]
            coauthor_id = str(coauthor.get("id") or "")
            if not coauthor_id or coauthor_id in normalized_target_author_ids:
                continue
            aggregate = collaboration_aggregate.setdefault(coauthor_id, {
                "author": deepcopy(coauthor),
                "years": set(),
                "work_ids": set(),
                "source": "openalex",
                "confidence": 0.95,
            })
            aggregate["work_ids"].add(openalex_id)
            if publication_year:
                aggregate["years"].add(publication_year)

    scholar_topics = []
    for aggregate in topic_aggregate.values():
        years = sorted(aggregate.pop("years"))
        work_ids = sorted(aggregate.pop("work_ids"))
        scholar_topics.append({
            "topic": aggregate,
            "first_year": min(years) if years else None,
            "last_year": max(years) if years else None,
            "years": years,
            "work_ids": work_ids,
            "works_count": len(work_ids),
            "source": "openalex",
            "confidence": aggregate.get("confidence", 0.85),
        })
        if years:
            timeline.append({
                "event_key": f"topic:{aggregate['source_topic_id']}:{min(years)}",
                "event_type": "topic_started",
                "event_year": min(years),
                "event_date": None,
                "title": aggregate["display_name"],
                "description": f"{len(work_ids)} 篇关联论文",
                "topic_source_id": aggregate["source_topic_id"],
                "source": "openalex",
                "confidence": aggregate.get("confidence", 0.85),
            })

    collaborations = []
    for coauthor_id, aggregate in collaboration_aggregate.items():
        years = sorted(aggregate.pop("years"))
        work_ids = sorted(aggregate.pop("work_ids"))
        row = {
            **aggregate,
            "first_year": min(years) if years else None,
            "last_year": max(years) if years else None,
            "years": years,
            "work_ids": work_ids,
            "works_count": len(work_ids),
        }
        collaborations.append(row)
        if years:
            timeline.append({
                "event_key": f"collaboration:{coauthor_id}:{min(years)}",
                "event_type": "collaboration_started",
                "event_year": min(years),
                "event_date": None,
                "title": _text(row["author"].get("display_name")) or coauthor_id,
                "description": f"{len(work_ids)} 篇合作论文",
                "collaborator_source_id": coauthor_id,
                "source": "openalex",
                "confidence": 0.95,
            })

    affiliations = _author_affiliations(author)
    for affiliation in affiliations:
        institution = affiliation["institution"]
        source_id = str(institution.get("id") or "")
        start_year = affiliation.get("start_year")
        end_year = affiliation.get("end_year")
        if start_year:
            timeline.append({
                "event_key": f"institution:{source_id}:start:{start_year}",
                "event_type": "institution_started",
                "event_year": start_year,
                "event_date": None,
                "title": _text(institution.get("display_name")) or source_id,
                "description": "",
                "institution_source_id": source_id,
                "source": "openalex",
                "confidence": affiliation["confidence"],
            })
        if end_year and not affiliation.get("is_current"):
            timeline.append({
                "event_key": f"institution:{source_id}:end:{end_year}",
                "event_type": "institution_ended",
                "event_year": end_year,
                "event_date": None,
                "title": _text(institution.get("display_name")) or source_id,
                "description": "",
                "institution_source_id": source_id,
                "source": "openalex",
                "confidence": affiliation["confidence"],
            })

    fingerprint_facts = sorted(
        (
            work["doi"] or work["source_work_id"],
            work["source_updated_at"],
            work["cited_by_count"],
        )
        for work in normalized_works
    )
    fingerprint = hashlib.sha256(
        json.dumps(fingerprint_facts, ensure_ascii=False).encode()
    ).hexdigest()
    return {
        "author": deepcopy(author),
        "target_author_id": target_author_id,
        "target_author_ids": sorted(normalized_target_author_ids),
        "works": normalized_works,
        "affiliations": affiliations,
        "scholar_topics": scholar_topics,
        "collaborations": collaborations,
        "timeline_events": sorted(
            timeline,
            key=lambda item: (
                item.get("event_year") or 0,
                item.get("event_date") or "",
                item["event_key"],
            ),
        ),
        "fingerprint": fingerprint,
        "source_watermark": max(source_watermarks) if source_watermarks else None,
        "crossref_report": crossref_report or {
            "requested": 0,
            "verified": 0,
            "missing": 0,
            "failed": 0,
        },
    }


def _incremental_since(last_success_at: str | None, force_rebuild: bool) -> str | None:
    if force_rebuild or not last_success_at:
        return None
    try:
        value = datetime.fromisoformat(str(last_success_at).replace("Z", "+00:00"))
    except ValueError:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return (value.astimezone(timezone.utc) - timedelta(
        days=GRAPH_INCREMENTAL_OVERLAP_DAYS
    )).date().isoformat()


def _published_profile_work_ids(repository, author_id: str, cached_profile: dict) -> set[str] | None:
    analysis_version = int(((cached_profile.get("payload") or {}).get("analysisVersion")) or 0)
    if analysis_version < 2:
        return None
    work_ids: set[str] = set()
    offset = 0
    while True:
        page = repository.list_works(
            author_id,
            limit=1000,
            offset=offset,
            sort="citations",
        )
        items = page.get("items") or []
        work_ids.update(str(item.get("id") or "") for item in items if item.get("id"))
        offset += len(items)
        if not items or offset >= int(page.get("total") or 0):
            break
    return work_ids


def sync_scholar_research_graph(
    repository,
    author_id: str,
    *,
    api_key: str,
    budget_provider: str,
    force_rebuild: bool = False,
) -> dict:
    """Fetch a complete incremental batch and commit it atomically."""
    from research_graph_repository import (
        apply_research_graph_batch,
        get_research_graph_sync_state,
    )

    state = get_research_graph_sync_state(repository, author_id) or {}
    published_since = _incremental_since(
        state.get("last_success_at"),
        force_rebuild,
    )
    cached_profile = repository.get_profile(author_id) or {}
    published_work_ids = _published_profile_work_ids(
        repository,
        author_id,
        cached_profile,
    )
    merged_author_ids = (
        (((cached_profile.get("payload") or {}).get("identityAudit") or {}).get(
            "mergedAuthorIds"
        ))
        or []
    )
    target_author_ids = list(dict.fromkeys([
        author_id,
        *(str(value) for value in merged_author_ids if value),
    ]))[:8]
    works = []
    warnings = []
    if is_provisional_author_id(author_id):
        author, works = get_provisional_author_bundle(
            author_id,
            api_key=api_key,
            budget_provider=budget_provider,
        )
        target_author_ids = [author_id]
        published_since = None
    else:
        author = get_author(author_id, api_key=api_key, budget_provider=budget_provider)
        for source_author_id in target_author_ids:
            author_works, author_warnings, complete = get_graph_works(
                source_author_id,
                published_since=published_since,
                api_key=api_key,
                budget_provider=budget_provider,
            )
            warnings.extend(
                f"{source_author_id}: {warning}" for warning in author_warnings
            )
            if not complete:
                raise IncompleteGraphSync(
                    "; ".join(warnings) or "OpenAlex graph fetch incomplete"
                )
            works.extend(author_works)

    source_fetched_works = len(works)
    if published_work_ids is not None:
        works = [
            work
            for work in works
            if str(work.get("id") or "") in published_work_ids
        ]
        excluded = source_fetched_works - len(works)
        if excluded:
            warnings.append(
                f"研究图谱跳过 {excluded} 篇未进入身份裁决后画像的论文"
            )

    dois = [normalize_doi(work.get("doi")) for work in works]
    crossref_records, crossref_report = verify_dois([doi for doi in dois if doi])
    if crossref_report.get("failed"):
        warnings.append(
            f"Crossref {crossref_report['failed']} 条记录暂时不可用；已保留既有成功数据"
        )
    batch = build_research_graph_batch(
        author,
        works,
        crossref_records=crossref_records,
        crossref_report=crossref_report,
        target_author_ids=target_author_ids,
    )
    result = apply_research_graph_batch(
        repository,
        batch,
        force_rebuild=force_rebuild,
        warnings=warnings,
    )
    return {
        **result,
        "mode": "full" if published_since is None else "incremental",
        "fetched_works": len(works),
        "source_fetched_works": source_fetched_works,
        "warnings": warnings,
    }
