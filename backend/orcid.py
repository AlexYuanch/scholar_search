"""ORCID 公共记录客户端，用于论文身份锚定。"""
from __future__ import annotations

import re
from typing import Any

import requests

from crossref import normalize_doi


BASE = "https://pub.orcid.org/v3.0"
TIMEOUT = 12
_SESSION = requests.Session()
_SESSION.headers.update({
    "Accept": "application/json",
    "User-Agent": "ScholarProfile/1.0 (public ORCID identity verification)",
})
_ORCID_RE = re.compile(r"\b\d{4}-\d{4}-\d{4}-[\dX]{4}\b", re.IGNORECASE)


def normalize_orcid(value: str | None) -> str:
    match = _ORCID_RE.search(str(value or "").strip())
    return match.group(0).upper() if match else ""


def parse_orcid_works(payload: dict[str, Any]) -> list[dict[str, Any]]:
    works: list[dict[str, Any]] = []
    seen: set[tuple[str, str, int | None]] = set()
    for group in payload.get("group") or []:
        summaries = group.get("work-summary") or []
        if not summaries:
            continue
        summary = summaries[0]
        title = str((((summary.get("title") or {}).get("title") or {}).get("value")) or "").strip()
        year_value = (((summary.get("publication-date") or {}).get("year") or {}).get("value"))
        try:
            year = int(year_value) if year_value else None
        except (TypeError, ValueError):
            year = None
        doi = ""
        for external_id in (summary.get("external-ids") or {}).get("external-id") or []:
            if str(external_id.get("external-id-type") or "").casefold() == "doi":
                doi = normalize_doi(external_id.get("external-id-value"))
                if doi:
                    break
        key = (doi, " ".join(title.casefold().split()), year)
        if (doi or title) and key not in seen:
            seen.add(key)
            works.append({"doi": doi, "title": title, "year": year})
    return works


def get_public_works(orcid: str | None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    normalized = normalize_orcid(orcid)
    if not normalized:
        return [], {"status": "unavailable", "orcid": "", "workCount": 0}
    try:
        response = _SESSION.get(f"{BASE}/{normalized}/works", timeout=TIMEOUT)
        response.raise_for_status()
        works = parse_orcid_works(response.json() or {})
        return works, {
            "status": "available",
            "orcid": normalized,
            "workCount": len(works),
        }
    except (requests.RequestException, ValueError):
        return [], {
            "status": "unavailable",
            "orcid": normalized,
            "workCount": 0,
        }
