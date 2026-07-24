"""Build traceable professional-identity details from public scholarly metadata."""
from __future__ import annotations

import re
from collections import defaultdict
from typing import Any, Iterable


_DEPARTMENT_MARKERS = (
    "college of ",
    "department of ",
    "faculty of ",
    "school of ",
    "学院",
    "学部",
    "系",
)
_LABORATORY_MARKERS = (
    "laboratory",
    " lab ",
    "key lab",
    "实验室",
)
_RESEARCH_UNIT_MARKERS = (
    "research institute",
    "research center",
    "research centre",
    "研究院",
    "研究所",
    "研究中心",
)


def _clean_text(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def _years(values: Iterable[Any]) -> list[int]:
    years = set()
    for value in values:
        try:
            year = int(value)
        except (TypeError, ValueError):
            continue
        if 1800 <= year <= 2100:
            years.add(year)
    return sorted(years, reverse=True)


def _institution_history(author_profile: dict) -> list[dict]:
    by_key: dict[str, dict] = {}
    for affiliation in author_profile.get("affiliations") or []:
        institution = affiliation.get("institution") or {}
        name = _clean_text(institution.get("display_name"))
        if not name:
            continue
        key = _clean_text(institution.get("id") or name).casefold()
        row = by_key.setdefault(key, {"name": name, "years": set()})
        row["years"].update(_years(affiliation.get("years") or []))

    for institution in author_profile.get("last_known_institutions") or []:
        name = _clean_text(institution.get("display_name"))
        if not name:
            continue
        key = _clean_text(institution.get("id") or name).casefold()
        by_key.setdefault(key, {"name": name, "years": set()})

    rows = [
        {"name": row["name"], "years": sorted(row["years"], reverse=True)}
        for row in by_key.values()
    ]
    return sorted(
        rows,
        key=lambda row: (max(row["years"], default=0), row["name"].casefold()),
        reverse=True,
    )


def _authorship_statements(
    works: Iterable[dict],
    target_author_ids: set[str],
) -> list[dict]:
    statements: dict[str, dict] = {}
    for work in works:
        try:
            publication_year = int(work.get("publication_year"))
        except (TypeError, ValueError):
            publication_year = 0
        for authorship in work.get("authorships") or []:
            author_id = _clean_text((authorship.get("author") or {}).get("id"))
            if author_id not in target_author_ids:
                continue
            for raw_statement in authorship.get("raw_affiliation_strings") or []:
                text = _clean_text(raw_statement)
                if not text:
                    continue
                key = text.casefold()
                row = statements.setdefault(key, {"text": text, "years": set()})
                if 1800 <= publication_year <= 2100:
                    row["years"].add(publication_year)
    rows = [
        {"text": row["text"], "years": sorted(row["years"], reverse=True)}
        for row in statements.values()
    ]
    return sorted(
        rows,
        key=lambda row: (max(row["years"], default=0), row["text"].casefold()),
        reverse=True,
    )


def _current_statements(statements: list[dict], current_institution: str) -> list[dict]:
    if not statements:
        return []
    latest_year = max(
        (max(row["years"], default=0) for row in statements),
        default=0,
    )
    latest = [
        row for row in statements
        if max(row["years"], default=0) == latest_year
    ]
    institution_key = current_institution.casefold()
    matching = [
        row for row in latest
        if institution_key and institution_key in row["text"].casefold()
    ]
    return matching or latest


def _unit_segment(statements: list[dict], markers: tuple[str, ...]) -> str | None:
    for row in statements:
        parts = [
            _clean_text(part)
            for part in re.split(r"[,;，；]", row["text"])
            if _clean_text(part)
        ]
        for part in parts:
            normalized = f" {part.casefold()} "
            if any(marker in normalized for marker in markers):
                return part
    return None


def build_professional_identity(
    author_profile: dict,
    works: Iterable[dict],
    target_author_ids: Iterable[str],
) -> dict:
    """Return only directly traceable affiliation facts.

    OpenAlex authorship strings can establish organizational units, but they do
    not establish academic rank or degree status. Those fields intentionally
    remain null until a dedicated public source supplies them.
    """
    author_ids = {
        _clean_text(author_id)
        for author_id in target_author_ids
        if _clean_text(author_id)
    }
    primary_author_id = _clean_text(author_profile.get("id"))
    if primary_author_id:
        author_ids.add(primary_author_id)

    history = _institution_history(author_profile)
    last_known = author_profile.get("last_known_institutions") or []
    current_institution = _clean_text(
        author_profile.get("current_institution")
        or ((last_known[0] if last_known else {}).get("display_name"))
        or (history[0]["name"] if history else "")
    )
    statements = _authorship_statements(works, author_ids)
    current_statements = _current_statements(statements, current_institution)
    department = _unit_segment(current_statements, _DEPARTMENT_MARKERS)
    laboratory = _unit_segment(current_statements, _LABORATORY_MARKERS)
    research_unit = _unit_segment(current_statements, _RESEARCH_UNIT_MARKERS)

    source_links = []
    if primary_author_id:
        source_links.append({"label": "OpenAlex", "url": primary_author_id})
    orcid = _clean_text(author_profile.get("orcid"))
    if orcid:
        source_links.append({"label": "ORCID", "url": orcid})

    return {
        "currentInstitution": current_institution,
        "institutionHistory": history,
        "currentAffiliationStatements": current_statements,
        "affiliationStatements": statements,
        "department": department,
        "laboratory": laboratory,
        "researchUnit": research_unit,
        "academicRole": None,
        "degreeStatus": None,
        "orcid": orcid or None,
        "sourceLinks": source_links,
        "sources": [
            "OpenAlex author affiliations",
            *(
                ["OpenAlex publication authorship strings"]
                if statements else []
            ),
        ],
    }
