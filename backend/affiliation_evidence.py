"""Build publication-affiliation evidence without inferring employment."""
from __future__ import annotations

from typing import Any, Iterable


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


def _openalex_affiliation_history(author_profile: dict) -> list[dict]:
    """Return affiliations OpenAlex derived from the author's publications."""
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


def _publication_affiliation_statements(
    works: Iterable[dict],
    target_author_ids: set[str],
) -> list[dict]:
    """Collect raw strings only from the target author's work authorships."""
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


def build_affiliation_evidence(
    author_profile: dict,
    works: Iterable[dict],
    target_author_ids: Iterable[str],
) -> dict:
    """Return OpenAlex publication-affiliation evidence with explicit semantics.

    Publication bylines can help distinguish namesakes. They do not establish
    current employment, academic rank, degree status, department membership,
    or laboratory membership, so this function never emits those claims.
    """
    author_ids = {
        _clean_text(author_id)
        for author_id in target_author_ids
        if _clean_text(author_id)
    }
    primary_author_id = _clean_text(author_profile.get("id"))
    if primary_author_id:
        author_ids.add(primary_author_id)

    source_links = []
    if primary_author_id:
        source_links.append({"label": "OpenAlex", "url": primary_author_id})
    orcid = _clean_text(author_profile.get("orcid"))
    if orcid:
        source_links.append({"label": "ORCID", "url": orcid})

    return {
        "openAlexAffiliationHistory": _openalex_affiliation_history(author_profile),
        "publicationAffiliationStatements": _publication_affiliation_statements(
            works,
            author_ids,
        ),
        "verifiedEmployment": None,
        "verifiedEducation": [],
        "orcid": orcid or None,
        "sourceLinks": source_links,
        "sources": [
            "OpenAlex author publication affiliations",
            "OpenAlex work authorship affiliation strings",
        ],
    }
