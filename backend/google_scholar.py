"""可选的 Google Scholar 核验适配器。

Google Scholar 没有官方公共 API；配置 SERPAPI_API_KEY 后仅通过 SerpApi
匹配已有论文，不按姓名扩张画像论文集。
"""
from __future__ import annotations

import os
import re
from typing import Any

import requests


BASE = "https://serpapi.com/search.json"
TIMEOUT = 20
_SESSION = requests.Session()
_SESSION.headers.update({
    "Accept": "application/json",
    "User-Agent": "ScholarProfile/1.0 (Google Scholar verification via SerpApi)",
})


def _api_key() -> str:
    return os.getenv("SERPAPI_API_KEY", "").strip()


def _normalized(value: str | None) -> str:
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", " ", str(value or "").casefold()).strip()


def _year(value: str | None) -> int | None:
    matches = re.findall(r"\b(?:19|20)\d{2}\b", str(value or ""))
    return int(matches[-1]) if matches else None


def _records(payload: dict[str, Any]) -> list[dict[str, Any]]:
    records = []
    for result in payload.get("organic_results") or []:
        publication = result.get("publication_info") or {}
        cited_by = ((result.get("inline_links") or {}).get("cited_by") or {}).get("total")
        records.append({
            "source": "google_scholar",
            "id": str(result.get("result_id") or ""),
            "title": str(result.get("title") or "").strip(),
            "publication_year": _year(publication.get("summary")),
            "publication_info": str(publication.get("summary") or "").strip(),
            "cited_by": int(cited_by or 0),
            "url": str(result.get("link") or ""),
        })
    return records


def _matching_records(records: list[dict[str, Any]], works: list[dict[str, Any]]) -> list[dict[str, Any]]:
    known = {
        (_normalized(work.get("title")), int(work.get("publication_year") or 0))
        for work in works
        if _normalized(work.get("title"))
    }
    known_titles = {title for title, _year_value in known}
    return [
        record
        for record in records
        if (
            (_normalized(record.get("title")), int(record.get("publication_year") or 0)) in known
            or (
                not record.get("publication_year")
                and _normalized(record.get("title")) in known_titles
            )
        )
    ]


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
    try:
        response = _SESSION.get(
            BASE,
            params={
                "engine": "google_scholar",
                "q": f'author:"{name}"',
                "num": 20,
                "api_key": key,
            },
            timeout=TIMEOUT,
        )
        response.raise_for_status()
        records = _records(response.json() or {})
        matched = _matching_records(records, works)
        return matched, {
            "status": "available",
            "requested": len(works),
            "matched": len(matched),
            "recordCount": len(records),
        }
    except (requests.RequestException, ValueError):
        return [], {"status": "unavailable", "requested": len(works), "matched": 0}
