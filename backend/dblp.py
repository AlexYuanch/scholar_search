"""DBLP 公共接口客户端，用于计算机领域论文与作者身份核验。"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import Any
from urllib.parse import quote

import requests

from crossref import normalize_doi


SEARCH_BASE = "https://dblp.org/search/author/api"
PERSON_BASE = "https://dblp.org/pid"
TIMEOUT = 15
MAX_CANDIDATES = 8
_SESSION = requests.Session()
_SESSION.headers.update({
    "Accept": "application/json, application/xml;q=0.9",
    "User-Agent": "ScholarProfile/1.0 (DBLP metadata verification)",
})
_ORCID_RE = re.compile(r"\b\d{4}-\d{4}-\d{4}-[\dX]{4}\b", re.IGNORECASE)


def _normalized(value: str | None) -> str:
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", " ", str(value or "").casefold()).strip()


def _normalized_name(value: str | None) -> str:
    return re.sub(r"\s+\d{4}$", "", _normalized(value)).strip()


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _text_values(value: Any) -> list[str]:
    values = []
    for item in _as_list(value):
        if isinstance(item, dict):
            text = item.get("text") or item.get("@value") or item.get("value")
        else:
            text = item
        if text:
            values.append(str(text).strip())
    return values


def _candidate(hit: dict[str, Any]) -> dict[str, Any]:
    info = hit.get("info") or {}
    url = str(info.get("url") or "")
    pid = url.split("/pid/", 1)[-1].strip("/") if "/pid/" in url else ""
    names = [str(info.get("author") or "").strip()]
    names.extend(_text_values((info.get("aliases") or {}).get("alias")))
    affiliations = _text_values((info.get("notes") or {}).get("note"))
    return {
        "pid": pid,
        "names": [name for name in names if name],
        "affiliations": affiliations,
        "url": url,
    }


def _search_candidates(name: str) -> list[dict[str, Any]]:
    response = _SESSION.get(
        SEARCH_BASE,
        params={"q": name, "format": "json", "h": MAX_CANDIDATES},
        timeout=TIMEOUT,
    )
    response.raise_for_status()
    hits = (((response.json() or {}).get("result") or {}).get("hits") or {}).get("hit")
    return [_candidate(hit) for hit in _as_list(hits) if isinstance(hit, dict)]


def _profile_institutions(profile: dict[str, Any]) -> list[str]:
    institutions = []
    for institution in profile.get("last_known_institutions") or []:
        name = str(institution.get("display_name") or "").strip()
        if name:
            institutions.append(name)
    return institutions


def _candidate_score(candidate: dict[str, Any], name: str, institutions: list[str]) -> tuple[int, int]:
    target_name = _normalized_name(name)
    exact_name = any(_normalized_name(value) == target_name for value in candidate["names"])
    institution_matches = sum(
        1
        for target in institutions
        for affiliation in candidate["affiliations"]
        if _normalized(target) and (
            _normalized(target) in _normalized(affiliation)
            or _normalized(affiliation) in _normalized(target)
        )
    )
    return (100 if exact_name else 0) + min(institution_matches, 3) * 20, institution_matches


def _person_xml(pid: str) -> ET.Element:
    response = _SESSION.get(f"{PERSON_BASE}/{quote(pid, safe='/')}.xml", timeout=TIMEOUT)
    response.raise_for_status()
    return ET.fromstring(response.content)


def _xml_orcids(root: ET.Element) -> set[str]:
    return {
        match.group(0).upper()
        for element in root.iter()
        for match in [_ORCID_RE.search(str(element.text or ""))]
        if match
    }


def _entry_text(entry: ET.Element, tag: str) -> str:
    element = entry.find(tag)
    return " ".join("".join(element.itertext()).split()) if element is not None else ""


def _entry_doi(entry: ET.Element) -> str:
    for ee in entry.findall("ee"):
        doi = normalize_doi(ee.text)
        if doi.startswith("10."):
            return doi
    return ""


def _person_records(root: ET.Element, pid: str) -> list[dict[str, Any]]:
    records = []
    for wrapper in root.findall(".//r"):
        entries = list(wrapper)
        if not entries:
            continue
        entry = entries[0]
        title = _entry_text(entry, "title")
        year_text = _entry_text(entry, "year")
        try:
            year = int(year_text) if year_text else None
        except ValueError:
            year = None
        authors = [_entry_text(author, ".") for author in entry.findall("author")]
        venue = _entry_text(entry, "journal") or _entry_text(entry, "booktitle")
        key = str(entry.attrib.get("key") or "")
        records.append({
            "source": "dblp",
            "id": key,
            "doi": _entry_doi(entry),
            "title": title,
            "publication_year": year,
            "journal": venue,
            "authors": [author for author in authors if author],
            "url": f"https://dblp.org/rec/{key}" if key else f"https://dblp.org/pid/{pid}",
        })
    return records


def _matching_records(records: list[dict[str, Any]], works: list[dict[str, Any]]) -> list[dict[str, Any]]:
    dois = {normalize_doi(work.get("doi")) for work in works if normalize_doi(work.get("doi"))}
    title_years = {
        (_normalized(work.get("title")), int(work.get("publication_year") or 0))
        for work in works
        if _normalized(work.get("title"))
    }
    matched = []
    for record in records:
        doi = normalize_doi(record.get("doi"))
        title_year = (_normalized(record.get("title")), int(record.get("publication_year") or 0))
        if (doi and doi in dois) or title_year in title_years:
            matched.append(record)
    return matched


def verify_author_works(
    profile: dict[str, Any],
    works: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    name = str(profile.get("display_name") or "").strip()
    if not name or not works:
        return [], {"status": "not_applicable", "requested": 0, "matched": 0}
    try:
        candidates = _search_candidates(name)
        institutions = _profile_institutions(profile)
        scored = sorted(
            ((candidate, *_candidate_score(candidate, name, institutions)) for candidate in candidates),
            key=lambda item: item[1],
            reverse=True,
        )
        exact_candidates = [
            item for item in scored
            if any(_normalized_name(value) == _normalized_name(name) for value in item[0]["names"])
        ]
        target_orcid_match = _ORCID_RE.search(str(profile.get("orcid") or ""))
        target_orcid = target_orcid_match.group(0).upper() if target_orcid_match else ""
        chosen = None
        chosen_root = None
        if target_orcid:
            for candidate, score, institution_matches in exact_candidates[:5]:
                root = _person_xml(candidate["pid"])
                if target_orcid in _xml_orcids(root):
                    chosen = (candidate, score, institution_matches, "orcid")
                    chosen_root = root
                    break
        if not chosen and exact_candidates:
            candidate, score, institution_matches = exact_candidates[0]
            if institution_matches or len(exact_candidates) == 1:
                chosen = (candidate, score, institution_matches, "affiliation" if institution_matches else "unique_name")
        if not chosen:
            return [], {
                "status": "identity_unresolved",
                "requested": len(works),
                "matched": 0,
                "candidateCount": len(candidates),
            }
        candidate, _score, _institution_matches, match_method = chosen
        root = chosen_root or _person_xml(candidate["pid"])
        all_records = _person_records(root, candidate["pid"])
        matched = _matching_records(all_records, works)
        return matched, {
            "status": "available",
            "requested": len(works),
            "matched": len(matched),
            "personPid": candidate["pid"],
            "personUrl": candidate["url"] or f"https://dblp.org/pid/{candidate['pid']}",
            "matchMethod": match_method,
            "recordCount": len(all_records),
        }
    except (requests.RequestException, ET.ParseError, ValueError):
        return [], {"status": "unavailable", "requested": len(works), "matched": 0}
