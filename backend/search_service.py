"""Shared, persistent OpenAlex scholar search orchestration."""
from __future__ import annotations

import os
import time
import unicodedata
from collections.abc import Callable
from typing import Any

from nodes import dedup_authors
from openalex import (
    IDENTITY_FINGERPRINT_VERSION,
    OpenAlexError,
    enrich_authors_for_disambiguation,
    search_authors,
)


SEARCH_CACHE_TTL_SECONDS = int(os.getenv("OPENALEX_SEARCH_CACHE_TTL_SECONDS", "86400"))
EMPTY_SEARCH_CACHE_TTL_SECONDS = int(
    os.getenv("OPENALEX_EMPTY_SEARCH_CACHE_TTL_SECONDS", "900")
)
INCOMPLETE_SEARCH_CACHE_TTL_SECONDS = int(
    os.getenv("OPENALEX_INCOMPLETE_SEARCH_CACHE_TTL_SECONDS", "300")
)
LOCAL_SEARCH_CACHE_TTL_SECONDS = int(
    os.getenv("OPENALEX_LOCAL_SEARCH_CACHE_TTL_SECONDS", "3600")
)
IDENTITY_CACHE_TTL_SECONDS = int(
    os.getenv("OPENALEX_IDENTITY_CACHE_TTL_SECONDS", str(30 * 86400))
)
SEARCH_COALESCE_WAIT_SECONDS = float(
    os.getenv("OPENALEX_SEARCH_COALESCE_WAIT_SECONDS", "25")
)
SEARCH_COALESCE_POLL_SECONDS = float(
    os.getenv("OPENALEX_SEARCH_COALESCE_POLL_SECONDS", "0.1")
)
OPENALEX_MIN_REMAINING_CREDITS = int(
    os.getenv("OPENALEX_MIN_REMAINING_CREDITS", "200")
)
AFFILIATION_SELECTION_VERSION = 3

_IDENTITY_GROUP_ORDER = {"high": 0, "medium": 1, "review": 2}


class SearchCoalesceTimeout(RuntimeError):
    """Raised when another process owns a cold search for too long."""


def normalize_search_query(value: str) -> tuple[str, str]:
    query_text = " ".join(unicodedata.normalize("NFKC", value).strip().split())
    return query_text.casefold(), query_text


def _clean_affiliation_name(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def _clean_affiliation_years(values: list[Any]) -> list[int]:
    years = set()
    for value in values:
        try:
            year = int(value)
        except (TypeError, ValueError):
            continue
        if 1800 <= year <= 2100:
            years.add(year)
    return sorted(years, reverse=True)


def _has_consecutive_years(years: list[int]) -> bool:
    ordered = sorted(set(years))
    return any(current - previous == 1 for previous, current in zip(ordered, ordered[1:]))


def _candidate_affiliations(author: dict) -> tuple[str, list[dict]]:
    records_by_name: dict[str, dict] = {}

    def merge_record(name: Any, years: list[Any] | None = None, work_count: Any = 0) -> None:
        cleaned_name = _clean_affiliation_name(name)
        if not cleaned_name:
            return
        key = cleaned_name.casefold()
        row = records_by_name.setdefault(
            key,
            {"name": cleaned_name, "years": set(), "work_count": 0},
        )
        row["years"].update(_clean_affiliation_years(years or []))
        try:
            row["work_count"] = max(row["work_count"], max(0, int(work_count or 0)))
        except (TypeError, ValueError):
            pass

    for affiliation in author.get("affiliations") or []:
        institution = affiliation.get("institution") or {}
        merge_record(institution.get("display_name"), affiliation.get("years"))
    fingerprint = author.get("identity_fingerprint") or {}
    for affiliation in fingerprint.get("affiliations") or []:
        merge_record(
            affiliation.get("name"),
            affiliation.get("years"),
            affiliation.get("work_count"),
        )
    current_names = {
        _clean_affiliation_name(institution.get("display_name")).casefold()
        for institution in author.get("last_known_institutions") or []
        if _clean_affiliation_name(institution.get("display_name"))
    }
    for institution in author.get("last_known_institutions") or []:
        merge_record(institution.get("display_name"))

    normalized = [
        {
            "name": row["name"],
            "years": sorted(row["years"], reverse=True),
            "work_count": row["work_count"],
        }
        for row in records_by_name.values()
    ]
    eligible = [
        row for row in normalized
        if row["work_count"] >= 2 or _has_consecutive_years(row["years"])
    ]
    primary = max(
        eligible,
        key=lambda row: (
            row["name"].casefold() in current_names,
            max(row["years"], default=0),
            row["work_count"],
            len(row["years"]),
            row["name"].casefold(),
        ),
        default=None,
    )
    primary_name = primary["name"] if primary else ""

    historical = [row for row in normalized if row["name"] != primary_name]
    historical.sort(key=lambda row: (
        -max(row["years"], default=0),
        -row["work_count"],
        -len(row["years"]),
        row["name"].casefold(),
    ))
    return primary_name, historical


def _supports_current_fingerprint(fingerprint: dict | None) -> bool:
    return bool(fingerprint) and (
        fingerprint.get("version") == IDENTITY_FINGERPRINT_VERSION
    )


def _candidate_identity_evidence(author: dict) -> list[dict]:
    if isinstance(author.get("identity_evidence"), list):
        return author["identity_evidence"]
    evidence = []
    if author.get("orcid"):
        evidence.append({"type": "orcid", "value": author["orcid"]})
    if author.get("primary_institution"):
        evidence.append({
            "type": "primary_institution",
            "value": author["primary_institution"],
        })
    for match in author.get("identity_signals") or []:
        evidence.append({
            "type": "merged_profile",
            "reason": match.get("reason", ""),
            "shared_works": int(match.get("sharedWorks") or 0),
            "shared_coauthors": int(match.get("sharedCoauthors") or 0),
            "shared_topics": int(match.get("sharedTopics") or 0),
            "shared_institutions": int(match.get("sharedInstitutions") or 0),
        })
    published_merged_count = int(author.get("published_profile_merged_count") or 0)
    if not author.get("identity_signals") and published_merged_count > 1:
        evidence.append({
            "type": "published_profile",
            "merged_count": published_merged_count,
        })
    elif not author.get("identity_signals"):
        fingerprint = author.get("identity_fingerprint") or {}
        evidence.append({
            "type": "independent_profile",
            "sampled_works": int(fingerprint.get("sampled_works") or 0),
            "coauthor_count": len(fingerprint.get("coauthor_ids") or []),
            "topic_count": len(fingerprint.get("topic_ids") or []),
        })
    return evidence


def _candidate_payload(author: dict) -> dict:
    primary_institution, historical_affiliations = _candidate_affiliations(author)
    if not primary_institution and author.get("published_profile_merged_count"):
        primary_institution = _clean_affiliation_name(
            author.get("primary_institution") or author.get("current_institution")
        )
        historical_affiliations = [
            row for row in historical_affiliations
            if row["name"] != primary_institution
        ]
    other_institutions = [row["name"] for row in historical_affiliations]
    institutions = list(dict.fromkeys(
        [primary_institution, *other_institutions]
    ))
    institutions = [institution for institution in institutions if institution]
    identity_confidence = str(author.get("identity_confidence") or "single")
    fingerprint = author.get("identity_fingerprint") or {}
    evidence = _candidate_identity_evidence(author)
    evidence_types = {str(item.get("type")) for item in evidence}
    if identity_confidence == "high":
        identity_group = "high"
        identity_score = 90
    elif identity_confidence == "medium" or "orcid" in evidence_types:
        identity_group = "medium"
        identity_score = 65
    else:
        identity_group = "review"
        identity_score = 35

    match_reasons = []
    if author.get("orcid"):
        match_reasons.append({
            "code": "orcid",
            "label": "orcid",
            "value": str(author["orcid"]).replace("https://orcid.org/", ""),
        })
        identity_score += 10
    if primary_institution:
        match_reasons.append({
            "code": "primary_institution",
            "label": "primary_institution",
            "value": primary_institution,
        })
    for item in evidence:
        if item.get("type") == "merged_profile":
            details = {
                key: int(item.get(key) or 0)
                for key in ("shared_works", "shared_coauthors", "shared_topics", "shared_institutions")
            }
            match_reasons.append({"code": "merged_profile", "label": "merged_profile", "details": details})
            identity_score += min(details["shared_works"] * 4, 16)
            identity_score += min(details["shared_coauthors"] * 2, 12)
            identity_score += min(details["shared_topics"] * 2, 10)
            identity_score += min(details["shared_institutions"] * 4, 8)
        elif item.get("type") == "published_profile":
            match_reasons.append({
                "code": "published_profile",
                "label": "published_profile",
                "value": item.get("merged_count", 1),
            })
            identity_score += 8
        elif item.get("type") == "independent_profile":
            match_reasons.append({
                "code": "independent_profile",
                "label": "independent_profile",
                "details": {
                    "sampled_works": int(item.get("sampled_works") or 0),
                    "coauthor_count": int(item.get("coauthor_count") or 0),
                    "topic_count": int(item.get("topic_count") or 0),
                },
            })

    research_topics = list(dict.fromkeys(
        str(topic).strip()
        for topic in (fingerprint.get("topic_names") or author.get("research_topics") or [])
        if str(topic).strip()
    ))[:12]
    latest_publication_year = max(
        (int(year) for year in (fingerprint.get("publication_years") or []) if str(year).isdigit()),
        default=None,
    )
    identity_score = max(0, min(100, identity_score))
    return {
        "id": author["id"],
        "name": author.get("display_name") or author.get("name") or "",
        "institution": primary_institution,
        "institutions": institutions,
        "primary_institution": primary_institution,
        "other_institutions": other_institutions,
        "historical_affiliations": historical_affiliations,
        "affiliation_selection_version": AFFILIATION_SELECTION_VERSION,
        "works_count": author.get("works_count", 0),
        "cited_by_count": author.get("cited_by_count", 0),
        "h_index": (author.get("summary_stats") or {}).get("h_index", author.get("h_index", 0)),
        "orcid": author.get("orcid"),
        "merged_count": author.get("merged_count", 1),
        "merged_ids": author.get("merged_ids", [author.get("id", "")]),
        "disambiguation": author.get("disambiguation", ""),
        "identity_confidence": identity_confidence,
        "identity_evidence": evidence,
        "identity_group": identity_group,
        "identity_score": identity_score,
        "match_reasons": match_reasons,
        "latest_publication_year": latest_publication_year,
        "research_topics": research_topics,
    }


def _sort_candidate_payloads(candidates: list[dict]) -> list[dict]:
    """Default to identity confidence; keep the original order as a stable tie-breaker."""
    return [candidate for _, candidate in sorted(
        enumerate(candidates),
        key=lambda item: (
            _IDENTITY_GROUP_ORDER.get(item[1].get("identity_group"), 2),
            -int(item[1].get("identity_score") or 0),
            0 if item[1].get("orcid") else 1,
            -len(item[1].get("match_reasons") or []),
            item[0],
        ),
    )]


def _cache_supports_primary_affiliation(cached: dict | None) -> bool:
    return bool(cached) and all(
        candidate.get("affiliation_selection_version") == AFFILIATION_SELECTION_VERSION
        for candidate in cached.get("candidates") or []
    )


def build_live_candidate_payload(
    repository,
    query_text: str,
    *,
    api_key: str,
    budget_provider: str,
    search_fn: Callable[[str], list[dict]] | None = None,
    enrich_fn: Callable[[list[dict]], list[dict]] | None = None,
) -> tuple[list[dict], bool]:
    """Fetch candidates while reusing persistent identity fingerprints."""
    search_fn = search_fn or (
        lambda name: search_authors(
            name,
            api_key=api_key,
            budget_provider=budget_provider,
        )
    )
    enrich_fn = enrich_fn or (
        lambda candidates: enrich_authors_for_disambiguation(
            candidates,
            api_key=api_key,
            budget_provider=budget_provider,
        )
    )
    candidates = [dict(candidate) for candidate in search_fn(query_text)]
    author_ids = [str(candidate.get("id")) for candidate in candidates if candidate.get("id")]
    cached_by_id = repository.get_openalex_identity_caches(author_ids)
    refresh_candidates = []
    stale_fallbacks = {}

    for candidate in candidates:
        author_id = str(candidate.get("id") or "")
        cached = cached_by_id.get(author_id)
        cached_fingerprint = (cached or {}).get("fingerprint") or {}
        if cached and _supports_current_fingerprint(cached_fingerprint):
            candidate["identity_fingerprint"] = cached_fingerprint
            if not cached.get("fresh"):
                stale_fallbacks[author_id] = cached_fingerprint
                refresh_candidates.append(dict(candidate))
        elif author_id:
            refresh_candidates.append(dict(candidate))

    refreshed_by_id = {}
    if refresh_candidates:
        for refreshed in enrich_fn(refresh_candidates):
            author_id = str(refreshed.get("id") or "")
            if not author_id:
                continue
            fingerprint = refreshed.get("identity_fingerprint") or {}
            if fingerprint:
                repository.save_openalex_identity_cache(
                    author_id,
                    fingerprint,
                    IDENTITY_CACHE_TTL_SECONDS,
                )
            elif author_id in stale_fallbacks:
                refreshed["identity_fingerprint"] = stale_fallbacks[author_id]
            refreshed_by_id[author_id] = refreshed

    incomplete = False
    for index, candidate in enumerate(candidates):
        author_id = str(candidate.get("id") or "")
        if author_id in refreshed_by_id:
            candidates[index] = refreshed_by_id[author_id]
        if candidates[index].get("identity_warning"):
            incomplete = True

    merged = dedup_authors(candidates)
    return _sort_candidate_payloads([_candidate_payload(author) for author in merged]), not incomplete


def build_local_candidate_payload(repository, query_text: str) -> list[dict]:
    """Use already-published real scholars when OpenAlex is unavailable."""
    candidates = repository.search_local_openalex_authors(query_text)
    author_ids = [str(candidate.get("id")) for candidate in candidates if candidate.get("id")]
    cached_by_id = repository.get_openalex_identity_caches(author_ids)
    for candidate in candidates:
        cached = cached_by_id.get(str(candidate.get("id") or ""))
        fingerprint = (cached or {}).get("fingerprint") or {}
        if _supports_current_fingerprint(fingerprint):
            candidate["identity_fingerprint"] = fingerprint
    merged = dedup_authors(candidates)
    for author in merged:
        known_merged_ids = list(dict.fromkeys(author.get("merged_author_ids") or []))
        if known_merged_ids:
            author["merged_ids"] = known_merged_ids
            author["merged_count"] = len(known_merged_ids)
            if len(known_merged_ids) > 1:
                author["identity_confidence"] = "high"
                author["published_profile_merged_count"] = len(known_merged_ids)
    return _sort_candidate_payloads([_candidate_payload(author) for author in merged])


def _retry_after_seconds(exc: OpenAlexError) -> int | None:
    try:
        return max(1, int(exc.retry_after or ""))
    except ValueError:
        return None


def refresh_search_cache(
    repository,
    query_key: str,
    query_text: str,
    builder: Callable[[Any, str], tuple[list[dict], bool]] = build_live_candidate_payload,
) -> list[dict]:
    candidates, complete = builder(repository, query_text)
    ttl_seconds = (
        EMPTY_SEARCH_CACHE_TTL_SECONDS if not candidates else SEARCH_CACHE_TTL_SECONDS
    )
    if not complete:
        ttl_seconds = min(ttl_seconds, INCOMPLETE_SEARCH_CACHE_TTL_SECONDS)
    repository.save_openalex_search_cache(
        query_key,
        query_text,
        candidates,
        ttl_seconds,
    )
    return candidates


def run_claimed_search_job(
    repository,
    job: dict,
    builder: Callable[[Any, str], tuple[list[dict], bool]] = build_live_candidate_payload,
) -> list[dict]:
    try:
        candidates = refresh_search_cache(
            repository,
            job["query_key"],
            job["query_text"],
            builder,
        )
        repository.complete_openalex_search_job(str(job["id"]))
        return candidates
    except OpenAlexError as exc:
        retry_after = _retry_after_seconds(exc)
        retry = exc.status_code == 429 or int(job.get("attempts", 1)) < 3
        repository.fail_openalex_search_job(
            str(job["id"]),
            str(exc),
            retry=retry,
            retry_after_seconds=retry_after,
        )
        raise
    except Exception as exc:
        repository.fail_openalex_search_job(
            str(job["id"]),
            str(exc),
            retry=int(job.get("attempts", 1)) < 3,
        )
        raise


def _cached_response(cached: dict, source: str) -> dict:
    candidates = [
        candidate
        if candidate.get("identity_group") and "match_reasons" in candidate
        else _candidate_payload(candidate)
        for candidate in (cached.get("candidates") or [])
    ]
    return {
        "candidates": _sort_candidate_payloads(candidates),
        "source": source,
        "updated_at": cached.get("updated_at"),
    }


def _local_fallback(repository, query_key: str, query_text: str) -> dict | None:
    candidates = build_local_candidate_payload(repository, query_text)
    if not candidates:
        return None
    repository.save_openalex_search_cache(
        query_key,
        query_text,
        candidates,
        LOCAL_SEARCH_CACHE_TTL_SECONDS,
    )
    cached = repository.get_openalex_search_cache(query_key)
    return _cached_response(cached, "local") if cached else {
        "candidates": candidates,
        "source": "local",
        "updated_at": None,
    }


def search_with_cache(
    repository,
    name: str,
    builder: Callable[[Any, str], tuple[list[dict], bool]] = build_live_candidate_payload,
    *,
    budget_provider: str = "openalex",
    requested_by_user_id: str | None = None,
) -> dict:
    query_key, query_text = normalize_search_query(name)
    if not query_key:
        raise ValueError("Scholar name is required")

    cached = repository.get_openalex_search_cache(query_key)
    if not _cache_supports_primary_affiliation(cached):
        cached = None
    if cached and cached.get("fresh"):
        return _cached_response(cached, "cache")

    budget_retry_after = repository.get_upstream_retry_after(
        budget_provider,
        OPENALEX_MIN_REMAINING_CREDITS,
    )
    if cached:
        if budget_retry_after is None:
            repository.enqueue_openalex_search(
                query_key,
                query_text,
                requested_by_user_id=requested_by_user_id,
            )
        return _cached_response(cached, "stale")
    if budget_retry_after is not None:
        local = _local_fallback(repository, query_key, query_text)
        if local:
            return local
        raise OpenAlexError(
            "OpenAlex user budget reserve reached",
            status_code=429,
            retry_after=str(budget_retry_after),
        )

    repository.enqueue_openalex_search(
        query_key,
        query_text,
        requested_by_user_id=requested_by_user_id,
    )
    job = repository.claim_openalex_search_job(query_key)
    if job:
        try:
            candidates = run_claimed_search_job(repository, job, builder)
        except OpenAlexError:
            local = _local_fallback(repository, query_key, query_text)
            if local:
                return local
            raise
        refreshed = repository.get_openalex_search_cache(query_key)
        if refreshed:
            return _cached_response(refreshed, "live")
        return {"candidates": candidates, "source": "live", "updated_at": None}

    deadline = time.monotonic() + max(0.1, SEARCH_COALESCE_WAIT_SECONDS)
    while time.monotonic() < deadline:
        time.sleep(max(0.01, SEARCH_COALESCE_POLL_SECONDS))
        cached = repository.get_openalex_search_cache(query_key)
        if _cache_supports_primary_affiliation(cached):
            return _cached_response(cached, "coalesced")
        budget_retry_after = repository.get_upstream_retry_after(
            budget_provider,
            OPENALEX_MIN_REMAINING_CREDITS,
        )
        if budget_retry_after is not None:
            local = _local_fallback(repository, query_key, query_text)
            if local:
                return local
            raise OpenAlexError(
                "OpenAlex user budget reserve reached",
                status_code=429,
                retry_after=str(budget_retry_after),
            )
    local = _local_fallback(repository, query_key, query_text)
    if local:
        return local
    raise SearchCoalesceTimeout("Scholar search refresh is still running")
