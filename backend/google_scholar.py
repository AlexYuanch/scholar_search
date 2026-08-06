"""可选的 Google Scholar 核验适配器。

Google Scholar 没有官方公共 API；配置 SERPAPI_API_KEY 后通过 SerpApi
用现有论文锚定 Scholar 作者档案，再匹配已有论文，不按姓名扩张画像论文集。
"""
from __future__ import annotations

import os
import re
from typing import Any

import requests


BASE = "https://serpapi.com/search.json"
TIMEOUT = 20
MAX_ANCHOR_QUERIES = 2
MAX_AUTHOR_PROFILES = 2
AUTHOR_ARTICLE_LIMIT = 100
_SESSION = requests.Session()
_SESSION.headers.update({
    "Accept": "application/json",
    "User-Agent": "ScholarProfile/1.0 (Google Scholar verification via SerpApi)",
})


def _api_key() -> str:
    return os.getenv("SERPAPI_API_KEY", "").strip()


def _normalized(value: str | None) -> str:
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", " ", str(value or "").casefold()).strip()


def _year(value: str | int | None) -> int | None:
    matches = re.findall(r"\b(?:19|20)\d{2}\b", str(value or ""))
    return int(matches[-1]) if matches else None


def _person_name_matches(target: str | None, candidate: str | None) -> bool:
    target_tokens = _normalized(target).split()
    candidate_tokens = _normalized(candidate).split()
    if not target_tokens or not candidate_tokens:
        return False
    if target_tokens == candidate_tokens or sorted(target_tokens) == sorted(candidate_tokens):
        return True

    def token_matches(left: str, right: str) -> bool:
        return (
            left == right
            or (len(left) == 1 and right.startswith(left))
            or (len(right) == 1 and left.startswith(right))
        )

    for candidate_surname_index in {0, len(candidate_tokens) - 1}:
        candidate_surname = candidate_tokens[candidate_surname_index]
        candidate_given = [
            token
            for index, token in enumerate(candidate_tokens)
            if index != candidate_surname_index
        ]
        for target_surname_index in {0, len(target_tokens) - 1}:
            target_surname = target_tokens[target_surname_index]
            if max(len(candidate_surname), len(target_surname)) <= 1:
                continue
            if not token_matches(candidate_surname, target_surname):
                continue
            target_given = [
                token
                for index, token in enumerate(target_tokens)
                if index != target_surname_index
            ]
            if candidate_given and target_given and all(
                any(token_matches(candidate_token, target_token) for target_token in target_given)
                for candidate_token in candidate_given
            ):
                return True
    return False


def _profile_institutions(profile: dict[str, Any]) -> list[str]:
    names = [
        str(item.get("display_name") or "").strip()
        for item in profile.get("last_known_institutions") or []
    ]
    names.extend(
        str((item.get("institution") or {}).get("display_name") or "").strip()
        for item in profile.get("affiliations") or []
    )
    return list(dict.fromkeys(name for name in names if name))


def _institution_score(profile: dict[str, Any], scholar_affiliation: str | None) -> int:
    scholar = _normalized(scholar_affiliation)
    if not scholar:
        return 0
    score = 0
    for institution in _profile_institutions(profile):
        normalized = _normalized(institution)
        if not normalized:
            continue
        if normalized in scholar or scholar in normalized:
            score = max(score, 2)
            continue
        meaningful = {
            token
            for token in normalized.split()
            if len(token) >= 5 and token not in {"university", "institute", "college"}
        }
        if meaningful.intersection(scholar.split()):
            score = max(score, 1)
    return score


def _cited_by(value: Any) -> int:
    if isinstance(value, dict):
        value = value.get("value") or value.get("total")
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _organic_record(result: dict[str, Any]) -> dict[str, Any]:
    publication = result.get("publication_info") or {}
    cited_by = ((result.get("inline_links") or {}).get("cited_by") or {}).get("total")
    return {
        "source": "google_scholar",
        "id": str(result.get("result_id") or ""),
        "title": str(result.get("title") or "").strip(),
        "publication_year": _year(publication.get("summary")),
        "publication_info": str(publication.get("summary") or "").strip(),
        "authors": [
            {
                "name": str(author.get("name") or "").strip(),
                "author_id": str(author.get("author_id") or "").strip(),
            }
            for author in publication.get("authors") or []
            if author.get("name")
        ],
        "cited_by": _cited_by(cited_by),
        "url": str(result.get("link") or ""),
    }


def _organic_records(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return [_organic_record(result) for result in payload.get("organic_results") or []]


def _author_records(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "source": "google_scholar",
            "id": str(article.get("citation_id") or ""),
            "title": str(article.get("title") or "").strip(),
            "publication_year": _year(article.get("year")),
            "publication_info": str(article.get("publication") or "").strip(),
            "cited_by": _cited_by(article.get("cited_by")),
            "url": str(article.get("link") or ""),
        }
        for article in payload.get("articles") or []
        if article.get("title")
    ]


def _title_matches(known_title: str, candidate_title: str) -> bool:
    known = _normalized(known_title)
    candidate = _normalized(candidate_title)
    if not known or not candidate:
        return False
    if known == candidate:
        return True
    known_tokens = known.split()
    candidate_tokens = candidate.split()
    return (
        len(known_tokens) >= 6
        and len(candidate_tokens) - len(known_tokens) <= 16
        and f" {known} " in f" {candidate} "
    )


def _matching_records(records: list[dict[str, Any]], works: list[dict[str, Any]]) -> list[dict[str, Any]]:
    known = [
        (str(work.get("title") or ""), int(work.get("publication_year") or 0))
        for work in works
        if _normalized(work.get("title"))
    ]
    return [
        record
        for record in records
        if any(
            _title_matches(title, str(record.get("title") or ""))
            and (
                not record.get("publication_year")
                or int(record.get("publication_year") or 0) == publication_year
            )
            for title, publication_year in known
        )
    ]


def _request(key: str, **params: Any) -> dict[str, Any]:
    response = _SESSION.get(
        BASE,
        params={**params, "api_key": key, "hl": "en"},
        timeout=TIMEOUT,
    )
    response.raise_for_status()
    payload = response.json() or {}
    if payload.get("error"):
        raise ValueError(str(payload["error"]))
    return payload


def _anchor_works(works: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unique: dict[str, dict[str, Any]] = {}
    for work in sorted(
        works,
        key=lambda item: int(item.get("cited_by_count") or 0),
        reverse=True,
    ):
        title = _normalized(work.get("title"))
        if title and title not in unique:
            unique[title] = work
        if len(unique) >= MAX_ANCHOR_QUERIES:
            break
    return list(unique.values())


def verify_author_works(
    profile: dict[str, Any],
    works: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    key = _api_key()
    if not key:
        return [], {
            "status": "disabled",
            "reason": "api_key_not_configured",
            "requested": 0,
            "matched": 0,
        }
    name = str(profile.get("display_name") or "").strip()
    if not name or not works:
        return [], {"status": "not_applicable", "requested": 0, "matched": 0}

    anchor_matches: list[dict[str, Any]] = []
    author_ids: list[str] = []
    anchor_queries = 0
    successful_requests = 0
    try:
        for work in _anchor_works(works):
            anchor_queries += 1
            payload = _request(
                key,
                engine="google_scholar",
                q=f'"{str(work.get("title") or "").strip()}"',
                num=10,
            )
            successful_requests += 1
            for record in _matching_records(_organic_records(payload), [work]):
                matching_authors = [
                    author
                    for author in record.get("authors") or []
                    if _person_name_matches(name, author.get("name"))
                ]
                if not matching_authors:
                    continue
                anchor_matches.append(record)
                author_ids.extend(
                    author["author_id"]
                    for author in matching_authors
                    if author.get("author_id")
                )

        best: tuple[int, int, list[dict[str, Any]], dict[str, Any]] | None = None
        profiles_checked = 0
        for author_id in list(dict.fromkeys(author_ids))[:MAX_AUTHOR_PROFILES]:
            payload = _request(
                key,
                engine="google_scholar_author",
                author_id=author_id,
                num=AUTHOR_ARTICLE_LIMIT,
            )
            successful_requests += 1
            profiles_checked += 1
            author = payload.get("author") or {}
            if not _person_name_matches(name, author.get("name")):
                continue
            records = _author_records(payload)
            matched = _matching_records(records, works)
            score = (
                len(matched),
                _institution_score(profile, author.get("affiliations")),
            )
            if matched and (best is None or score > best[:2]):
                best = (
                    *score,
                    matched,
                    {
                        "id": author_id,
                        "name": str(author.get("name") or ""),
                        "affiliations": str(author.get("affiliations") or ""),
                        "recordCount": len(records),
                    },
                )

        if best:
            matched_count, _institution_match, records, scholar_profile = best
            return records, {
                "status": "available",
                "requested": len(works),
                "matched": matched_count,
                "recordCount": scholar_profile["recordCount"],
                "anchorQueries": anchor_queries,
                "profilesChecked": profiles_checked,
                "verificationMethod": "paper_anchor_profile",
                "profileId": scholar_profile["id"],
                "profileName": scholar_profile["name"],
                "profileAffiliations": scholar_profile["affiliations"],
            }

        direct_matches = list({record["id"]: record for record in anchor_matches}.values())
        if direct_matches:
            return direct_matches, {
                "status": "available",
                "requested": len(works),
                "matched": len(direct_matches),
                "recordCount": len(direct_matches),
                "anchorQueries": anchor_queries,
                "profilesChecked": profiles_checked,
                "verificationMethod": "paper_title_author_anchor",
            }
        return [], {
            "status": "identity_unresolved",
            "reason": "no_matching_paper_anchor",
            "requested": len(works),
            "matched": 0,
            "anchorQueries": anchor_queries,
            "profilesChecked": profiles_checked,
        }
    except (requests.RequestException, ValueError):
        return [], {
            "status": "unavailable",
            "requested": len(works),
            "matched": 0,
            "anchorQueries": anchor_queries,
            "successfulRequests": successful_requests,
        }
