"""Crossref REST 客户端，用 DOI 核验出版元数据。"""
from __future__ import annotations

import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from html import unescape
from typing import Any
from urllib.parse import quote

import requests


BASE = "https://api.crossref.org"
TIMEOUT = 12
MAX_RETRIES = 2
DEFAULT_MAX_WORKERS = 4
_SESSION = requests.Session()
_SESSION.headers.update({
    "Accept": "application/json",
    "User-Agent": "ScholarProfile/1.0 (multi-source metadata verification)",
})


def normalize_doi(value: str | None) -> str:
    normalized = str(value or "").strip().lower()
    normalized = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", normalized)
    normalized = re.sub(r"^doi:\s*", "", normalized)
    return normalized.strip()


def _publication_year(message: dict[str, Any]) -> int | None:
    for key in ("published-print", "published-online", "published", "issued"):
        parts = ((message.get(key) or {}).get("date-parts") or [])
        if parts and parts[0]:
            try:
                return int(parts[0][0])
            except (TypeError, ValueError):
                continue
    return None


def _author_names(message: dict[str, Any]) -> list[str]:
    names = []
    for author in message.get("author") or []:
        name = " ".join(part for part in (author.get("given", ""), author.get("family", "")) if part).strip()
        if name:
            names.append(name)
    return names


def _record(message: dict[str, Any], fallback_doi: str) -> dict[str, Any]:
    doi = normalize_doi(message.get("DOI") or fallback_doi)
    titles = message.get("title") or []
    journals = message.get("container-title") or []
    title = re.sub(r"<[^>]+>", " ", unescape(str(titles[0]))) if titles else ""
    title = " ".join(title.split())
    return {
        "source": "crossref",
        "id": doi,
        "doi": doi,
        "title": title,
        "publication_year": _publication_year(message),
        "journal": str(journals[0]).strip() if journals else "",
        "authors": _author_names(message),
        "type": message.get("type") or "",
        "raw": message,
    }


def _fetch_doi(doi: str) -> tuple[str, dict[str, Any] | None, str]:
    url = f"{BASE}/works/{quote(doi, safe='')}"
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = _SESSION.get(url, timeout=TIMEOUT)
            if response.status_code == 404:
                return doi, None, "missing"
            if response.status_code == 429 or response.status_code >= 500:
                if attempt < MAX_RETRIES:
                    time.sleep(attempt)
                    continue
            response.raise_for_status()
            message = (response.json() or {}).get("message") or {}
            return doi, _record(message, doi), "verified"
        except (requests.Timeout, requests.ConnectionError, requests.HTTPError, ValueError):
            if attempt < MAX_RETRIES:
                time.sleep(attempt)
                continue
    return doi, None, "failed"


def verify_dois(
    dois: list[str],
    max_workers: int = DEFAULT_MAX_WORKERS,
) -> tuple[dict[str, dict[str, Any]], dict[str, int]]:
    normalized = list(dict.fromkeys(filter(None, (normalize_doi(value) for value in dois))))
    records: dict[str, dict[str, Any]] = {}
    report = {"requested": len(normalized), "verified": 0, "missing": 0, "failed": 0}
    if not normalized:
        return records, report

    first_doi, first_record, first_status = _fetch_doi(normalized[0])
    report[first_status] += 1
    if first_record:
        records[first_doi] = first_record
    if first_status == "failed":
        report["failed"] = len(normalized)
        return records, report
    remaining = normalized[1:]
    if not remaining:
        return records, report

    with ThreadPoolExecutor(max_workers=max(1, min(max_workers, len(remaining)))) as executor:
        futures = [executor.submit(_fetch_doi, doi) for doi in remaining]
        for future in as_completed(futures):
            doi, record, status = future.result()
            report[status] += 1
            if record:
                records[doi] = record
    return records, report
