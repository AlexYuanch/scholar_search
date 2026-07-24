"""Shared, persistent OpenAlex scholar search orchestration."""
from __future__ import annotations

import os
import time
import unicodedata
from collections.abc import Callable
from typing import Any

from nodes import dedup_authors
from openalex import OpenAlexError, enrich_authors_for_disambiguation, search_authors


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
AFFILIATION_SELECTION_VERSION = 2


class SearchCoalesceTimeout(RuntimeError):
    """Raised when another process owns a cold search for too long."""


def normalize_search_query(value: str) -> tuple[str, str]:
    query_text = " ".join(unicodedata.normalize("NFKC", value).strip().split())
    return query_text.casefold(), query_text


def _candidate_identity_evidence(author: dict) -> list[dict]:
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
    institutions = author.get("institutions") or []
    last_known = author.get("last_known_institutions") or [{}]
    primary_institution = (
        author.get("primary_institution")
        or author.get("current_institution")
        or (institutions or [last_known[0].get("display_name", "")])[0]
    )
    other_institutions = (
        author.get("other_institutions")
        or author.get("historical_institutions")
        or [institution for institution in institutions if institution != primary_institution]
    )
    return {
        "id": author["id"],
        "name": author["display_name"],
        "institution": primary_institution,
        "institutions": institutions,
        "primary_institution": primary_institution,
        "other_institutions": other_institutions,
        "affiliation_selection_version": AFFILIATION_SELECTION_VERSION,
        "works_count": author.get("works_count", 0),
        "cited_by_count": author.get("cited_by_count", 0),
        "h_index": (author.get("summary_stats") or {}).get("h_index", 0),
        "orcid": author.get("orcid"),
        "merged_count": author.get("merged_count", 1),
        "merged_ids": author.get("merged_ids", [author.get("id", "")]),
        "disambiguation": author.get("disambiguation", ""),
        "identity_confidence": author.get("identity_confidence", "single"),
        "identity_evidence": _candidate_identity_evidence(author),
    }


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
        if cached:
            candidate["identity_fingerprint"] = cached.get("fingerprint") or {}
            if not cached.get("fresh"):
                stale_fallbacks[author_id] = candidate["identity_fingerprint"]
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
    return [_candidate_payload(author) for author in merged], not incomplete


def build_local_candidate_payload(repository, query_text: str) -> list[dict]:
    """Use already-published real scholars when OpenAlex is unavailable."""
    candidates = repository.search_local_openalex_authors(query_text)
    author_ids = [str(candidate.get("id")) for candidate in candidates if candidate.get("id")]
    cached_by_id = repository.get_openalex_identity_caches(author_ids)
    for candidate in candidates:
        cached = cached_by_id.get(str(candidate.get("id") or ""))
        if cached:
            candidate["identity_fingerprint"] = cached.get("fingerprint") or {}
    merged = dedup_authors(candidates)
    for author in merged:
        known_merged_ids = list(dict.fromkeys(author.get("merged_author_ids") or []))
        if known_merged_ids:
            author["merged_ids"] = known_merged_ids
            author["merged_count"] = len(known_merged_ids)
            if len(known_merged_ids) > 1:
                author["identity_confidence"] = "high"
                author["published_profile_merged_count"] = len(known_merged_ids)
    return [_candidate_payload(author) for author in merged]


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
    return {
        "candidates": cached.get("candidates") or [],
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
