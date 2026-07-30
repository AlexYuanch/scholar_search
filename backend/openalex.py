"""OpenAlex API 客户端。封装所有与 OpenAlex 的 HTTP 通信。"""
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
from typing import Callable, List

import requests

try:
    from pypinyin import Style, lazy_pinyin
except ImportError:  # 允许未同步依赖的开发环境先正常启动
    Style = None
    lazy_pinyin = None

PINYIN_AVAILABLE = lazy_pinyin is not None and Style is not None

BASE = "https://api.openalex.org"
HEADERS = {"User-Agent": "ScholarSearch/1.0"}
MAX_RETRIES = 3
RETRY_STATUSES = {429, 500, 502, 503, 504}
DEFAULT_MAX_PAGES = int(os.getenv("OPENALEX_MAX_WORK_PAGES", "200"))
IDENTITY_FINGERPRINT_WORKS = int(os.getenv("OPENALEX_IDENTITY_FINGERPRINT_WORKS", "100"))
IDENTITY_MAX_WORKERS = int(os.getenv("OPENALEX_IDENTITY_MAX_WORKERS", "8"))
IDENTITY_FINGERPRINT_VERSION = 2
PROVISIONAL_AUTHOR_PREFIX = "provisional"
_SESSION = requests.Session()
_CHINESE_RE = re.compile(r"[\u3400-\u9fff]")
_BUDGET_GUARD: Callable[[str], int | None] | None = None
_BUDGET_REPORTER: Callable[[str, dict], None] | None = None


def _entity_id(value: str) -> str:
    """Return the stable OpenAlex entity id accepted by paths and filters."""
    return str(value or "").strip().rstrip("/").rsplit("/", 1)[-1]


class OpenAlexError(RuntimeError):
    """Raised when OpenAlex cannot satisfy a request."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        retry_after: str | None = None,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.retry_after = retry_after


def configure_budget_control(
    guard: Callable[[str], int | None] | None,
    reporter: Callable[[str, dict], None] | None,
) -> None:
    """Configure per-provider budget protection without coupling the client to storage."""
    global _BUDGET_GUARD, _BUDGET_REPORTER
    _BUDGET_GUARD = guard
    _BUDGET_REPORTER = reporter


def _integer_header(response, name: str) -> int | None:
    try:
        return max(0, int(response.headers.get(name, "")))
    except (TypeError, ValueError):
        return None


def _report_budget(response, budget_provider: str) -> None:
    if _BUDGET_REPORTER is None:
        return
    snapshot = {
        "limit_credits": _integer_header(response, "X-RateLimit-Limit"),
        "remaining_credits": _integer_header(response, "X-RateLimit-Remaining"),
        "reset_after_seconds": _integer_header(response, "X-RateLimit-Reset"),
    }
    if all(value is None for value in snapshot.values()):
        return
    try:
        _BUDGET_REPORTER(budget_provider, snapshot)
    except Exception:
        return


def _get(
    endpoint: str,
    *,
    api_key: str,
    budget_provider: str,
    apply_budget_guard: bool = True,
    **params,
) -> dict:
    """GET JSON from OpenAlex with retry for transient failures."""
    if not api_key.strip():
        raise OpenAlexError("OpenAlex API key is required", status_code=428)
    if apply_budget_guard and _BUDGET_GUARD is not None:
        try:
            budget_retry_after = _BUDGET_GUARD(budget_provider)
        except Exception:
            budget_retry_after = None
        if budget_retry_after is not None:
            raise OpenAlexError(
                "OpenAlex user budget reserve reached",
                status_code=429,
                retry_after=str(max(1, budget_retry_after)),
            )
    last_error: Exception | None = None
    last_status: int | None = None
    last_retry_after: str | None = None
    url = f"{BASE}{endpoint}"
    request_params = dict(params)
    request_params["api_key"] = api_key.strip()
    for attempt in range(1, MAX_RETRIES + 1):
        last_status = None
        last_retry_after = None
        try:
            response = _SESSION.get(url, params=request_params, headers=HEADERS, timeout=30)
            last_status = response.status_code
            last_retry_after = response.headers.get("Retry-After")
            _report_budget(response, budget_provider)
            if response.status_code in RETRY_STATUSES and attempt < MAX_RETRIES:
                time.sleep(min(2 ** (attempt - 1), 8))
                continue
            response.raise_for_status()
            return response.json()
        except (requests.Timeout, requests.ConnectionError, requests.HTTPError) as exc:
            last_error = exc
            status = getattr(getattr(exc, "response", None), "status_code", None)
            retryable = status in RETRY_STATUSES or isinstance(
                exc, (requests.Timeout, requests.ConnectionError)
            )
            if retryable and attempt < MAX_RETRIES:
                time.sleep(min(2 ** (attempt - 1), 8))
                continue
            break
        except requests.RequestException as exc:
            last_error = exc
            break
    error_type = type(last_error).__name__ if last_error else "UnknownError"
    raise OpenAlexError(
        f"OpenAlex 请求失败: {endpoint}; {error_type}",
        status_code=last_status,
        retry_after=last_retry_after,
    ) from None


def validate_openalex_api_key(
    api_key: str,
    budget_provider: str = "openalex:validation",
) -> dict:
    """Validate a user-owned key against OpenAlex without exposing it."""
    data = _get(
        "/rate-limit",
        api_key=api_key,
        budget_provider=budget_provider,
        apply_budget_guard=False,
    )
    rate_limit = data.get("rate_limit") or {}
    return {
        "daily_budget_usd": rate_limit.get("daily_budget_usd"),
        "daily_used_usd": rate_limit.get("daily_used_usd"),
        "daily_remaining_usd": rate_limit.get("daily_remaining_usd"),
        "prepaid_remaining_usd": rate_limit.get("prepaid_remaining_usd"),
        "resets_at": rate_limit.get("resets_at"),
    }


def _name_query_variants(name: str) -> list[str]:
    """为中文姓名补充姓在前、姓在后的拼音检索形式。"""
    normalized = " ".join(name.strip().split())
    variants = [normalized]
    if not _CHINESE_RE.search(normalized) or not PINYIN_AVAILABLE:
        return variants

    syllables = lazy_pinyin(normalized, style=Style.NORMAL, errors="ignore")
    if len(syllables) < 2:
        return variants

    surname = syllables[0].capitalize()
    given_name = "".join(syllables[1:]).capitalize()
    for variant in (f"{surname} {given_name}", f"{given_name} {surname}"):
        if variant not in variants:
            variants.append(variant)
    return variants


def _author_search_rank(author: dict) -> tuple[int, int, int]:
    """优先展示有机构信息、引用较多且论文较多的候选。"""
    institutions = author.get("last_known_institutions") or []
    return (
        1 if institutions else 0,
        author.get("cited_by_count", 0) or 0,
        author.get("works_count", 0) or 0,
    )


def search_authors(
    name: str,
    per_page: int = 50,
    *,
    api_key: str,
    budget_provider: str,
) -> List[dict]:
    """按姓名搜索作者；中文姓名会同时搜索常见的两种拼音顺序。"""
    authors_by_id = {}
    for variant in _name_query_variants(name):
        data = _get(
            "/authors",
            api_key=api_key,
            budget_provider=budget_provider,
            filter=f"display_name.search:{variant}",
            per_page=per_page,
            sort="cited_by_count:desc",
            select=(
                "id,display_name,display_name_alternatives,orcid,works_count,"
                "cited_by_count,summary_stats,last_known_institutions,affiliations"
            ),
        )
        for author in data.get("results", []):
            author_id = author.get("id")
            if author_id and author_id not in authors_by_id:
                authors_by_id[author_id] = author

    return sorted(authors_by_id.values(), key=_author_search_rank, reverse=True)[:100]


def is_provisional_author_id(author_id: str | None) -> bool:
    return str(author_id or "").startswith(f"{PROVISIONAL_AUTHOR_PREFIX}:")


def _parse_provisional_author_id(author_id: str) -> tuple[str, int]:
    parts = str(author_id or "").split(":")
    if len(parts) != 3 or parts[0] != PROVISIONAL_AUTHOR_PREFIX:
        raise ValueError("Invalid provisional author id")
    try:
        authorship_index = int(parts[2])
    except ValueError as exc:
        raise ValueError("Invalid provisional authorship index") from exc
    if not parts[1] or authorship_index < 0:
        raise ValueError("Invalid provisional author id")
    return _entity_id(parts[1]), authorship_index


def _person_name_tokens(value: str) -> tuple[str, ...]:
    return tuple(re.findall(r"[a-z0-9\u3400-\u9fff]+", str(value or "").casefold()))


def _exact_person_name_match(query: str, candidate: str) -> bool:
    query_tokens = _person_name_tokens(query)
    candidate_tokens = _person_name_tokens(candidate)
    return bool(
        query_tokens
        and candidate_tokens
        and (
            query_tokens == candidate_tokens
            or query_tokens == tuple(reversed(candidate_tokens))
            or sorted(query_tokens) == sorted(candidate_tokens)
        )
    )


def _raw_author_query_variants(name: str) -> list[str]:
    normalized = " ".join(name.strip().split())
    variants = [normalized]
    tokens = normalized.split()
    if len(tokens) in {2, 3}:
        reversed_name = " ".join(reversed(tokens))
        if reversed_name.casefold() != normalized.casefold():
            variants.append(reversed_name)
    return variants


_PROVISIONAL_WORK_SELECT = (
    "id,doi,title,publication_year,publication_date,cited_by_count,authorships,"
    "abstract_inverted_index,referenced_works,concepts,primary_topic,topics,"
    "keywords,primary_location,type,language,updated_date"
)


def _search_works_by_raw_author(
    name: str,
    *,
    api_key: str,
    budget_provider: str,
    max_pages: int = 2,
) -> list[dict]:
    """Find exact paper authorships, including authorships without an Author ID."""
    works_by_id: dict[str, dict] = {}
    for variant in _raw_author_query_variants(name):
        cursor = "*"
        page = 0
        escaped = variant.replace('"', "")
        while cursor and page < max_pages:
            page += 1
            data = _get(
                "/works",
                api_key=api_key,
                budget_provider=budget_provider,
                filter=f'raw_author_name.search:"{escaped}"',
                per_page=100,
                cursor=cursor,
                sort="cited_by_count:desc",
                select=_PROVISIONAL_WORK_SELECT,
            )
            for work in data.get("results", []):
                work_id = str(work.get("id") or "")
                if work_id:
                    works_by_id.setdefault(work_id, work)
            cursor = (data.get("meta") or {}).get("next_cursor")
    return list(works_by_id.values())


def get_work(
    work_id: str,
    *,
    api_key: str,
    budget_provider: str,
) -> dict:
    return _get(
        f"/works/{_entity_id(work_id)}",
        api_key=api_key,
        budget_provider=budget_provider,
        select=_PROVISIONAL_WORK_SELECT,
    )


def _authorship_name(authorship: dict) -> str:
    author = authorship.get("author") or {}
    return str(
        authorship.get("raw_author_name")
        or author.get("display_name")
        or author.get("raw_name")
        or ""
    ).strip()


def _provisional_authorship_records(name: str, works: list[dict]) -> list[dict]:
    records = []
    for work in works:
        for index, authorship in enumerate(work.get("authorships") or []):
            author = authorship.get("author") or {}
            if author.get("id") or not _exact_person_name_match(name, _authorship_name(authorship)):
                continue
            coauthor_keys = set()
            coauthor_names = []
            for other_index, other_authorship in enumerate(work.get("authorships") or []):
                if other_index == index:
                    continue
                other_author = other_authorship.get("author") or {}
                other_name = _authorship_name(other_authorship)
                other_key = str(other_author.get("id") or "").strip()
                if other_key:
                    coauthor_keys.add(other_key)
                if other_name and other_name not in coauthor_names:
                    coauthor_names.append(other_name)
            institution_keys = set()
            institution_names = []
            for institution in authorship.get("institutions") or []:
                institution_name = str(institution.get("display_name") or "").strip()
                institution_key = str(institution.get("id") or institution_name).strip().casefold()
                if institution_key:
                    institution_keys.add(institution_key)
                if institution_name and institution_name not in institution_names:
                    institution_names.append(institution_name)
            records.append({
                "work": work,
                "authorship_index": index,
                "name": _authorship_name(authorship),
                "authorship": authorship,
                "coauthor_keys": coauthor_keys,
                "coauthor_names": coauthor_names,
                "institution_keys": institution_keys,
                "institution_names": institution_names,
            })
    return records


def _provisional_components(records: list[dict]) -> list[set[int]]:
    """Join records only through duplicated works or stable coauthors.

    A shared institution alone is deliberately insufficient because common
    institutions routinely contain multiple same-name researchers.
    """
    def linked(left: int, right: int) -> bool:
        left_work = records[left]["work"]
        right_work = records[right]["work"]
        left_key = str(left_work.get("doi") or left_work.get("id") or "")
        right_key = str(right_work.get("doi") or right_work.get("id") or "")
        return bool(
            left_key
            and left_key == right_key
            or records[left]["coauthor_keys"] & records[right]["coauthor_keys"]
        )

    remaining = set(range(len(records)))
    components: list[set[int]] = []
    while remaining:
        component = {remaining.pop()}
        frontier = list(component)
        while frontier:
            current = frontier.pop()
            matches = {candidate for candidate in remaining if linked(current, candidate)}
            component.update(matches)
            remaining.difference_update(matches)
            frontier.extend(matches)
        components.append(component)
    return components


def _h_index(works: list[dict]) -> int:
    citations = sorted(
        (max(0, int(work.get("cited_by_count") or 0)) for work in works),
        reverse=True,
    )
    return max((index for index, count in enumerate(citations, 1) if count >= index), default=0)


def _build_provisional_candidate(
    component: set[int],
    records: list[dict],
    *,
    requested_id: str | None = None,
) -> dict:
    component_records = [records[index] for index in sorted(component)]
    anchor = max(
        component_records,
        key=lambda record: (
            int(record["work"].get("cited_by_count") or 0),
            int(record["work"].get("publication_year") or 0),
            str(record["work"].get("id") or ""),
        ),
    )
    anchor_work = anchor["work"]
    candidate_id = requested_id or (
        f"{PROVISIONAL_AUTHOR_PREFIX}:{_entity_id(anchor_work.get('id'))}:"
        f"{anchor['authorship_index']}"
    )
    works_by_id = {}
    for record in component_records:
        work = deepcopy(record["work"])
        work_id = str(work.get("id") or work.get("doi") or len(works_by_id))
        works_by_id.setdefault(work_id, work)
    works = list(works_by_id.values())
    publication_years = sorted({
        int(work.get("publication_year"))
        for work in works
        if work.get("publication_year")
    })
    topic_ids = set()
    topic_names = set()
    for work in works:
        for topic in [work.get("primary_topic") or {}, *(work.get("topics") or [])]:
            if topic.get("id"):
                topic_ids.add(str(topic["id"]))
            if topic.get("display_name"):
                topic_names.add(str(topic["display_name"]).strip())
    affiliation_rows: dict[str, dict] = {}
    for record in component_records:
        year = int(record["work"].get("publication_year") or 0)
        work_key = str(record["work"].get("doi") or record["work"].get("id") or "")
        for institution in record["authorship"].get("institutions") or []:
            name = str(institution.get("display_name") or "").strip()
            if not name:
                continue
            key = str(institution.get("id") or name).strip().casefold()
            row = affiliation_rows.setdefault(key, {
                "institution": deepcopy(institution),
                "years": set(),
                "work_ids": set(),
            })
            if year:
                row["years"].add(year)
            if work_key:
                row["work_ids"].add(work_key)
    affiliations = [
        {
            "institution": row["institution"],
            "years": sorted(row["years"], reverse=True),
        }
        for row in affiliation_rows.values()
    ]
    fingerprint_affiliations = [
        {
            "id": row["institution"].get("id"),
            "name": row["institution"].get("display_name", ""),
            "years": sorted(row["years"], reverse=True),
            "work_count": len(row["work_ids"]),
        }
        for row in affiliation_rows.values()
    ]
    latest_record = max(
        component_records,
        key=lambda record: int(record["work"].get("publication_year") or 0),
    )
    last_known_institutions = deepcopy(
        latest_record["authorship"].get("institutions") or []
    )
    coauthor_keys = sorted(set().union(
        *(record["coauthor_keys"] for record in component_records)
    ))
    anchor_data = {
        "work_id": str(anchor_work.get("id") or ""),
        "title": str(anchor_work.get("title") or ""),
        "doi": str(anchor_work.get("doi") or ""),
        "year": anchor_work.get("publication_year"),
        "authorship_index": anchor["authorship_index"],
        "coauthors": anchor["coauthor_names"],
        "institutions": anchor["institution_names"],
    }
    return {
        "id": candidate_id,
        "display_name": anchor["name"],
        "works_count": len(works),
        "cited_by_count": sum(int(work.get("cited_by_count") or 0) for work in works),
        "summary_stats": {"h_index": _h_index(works)},
        "orcid": None,
        "last_known_institutions": last_known_institutions,
        "affiliations": affiliations,
        "provisional": True,
        "provisional_anchor": anchor_data,
        "identity_confidence": "review",
        "identity_evidence": [{
            "type": "paper_anchor",
            "work_id": anchor_data["work_id"],
            "title": anchor_data["title"],
            "doi": anchor_data["doi"],
            "coauthors": anchor_data["coauthors"],
            "institutions": anchor_data["institutions"],
        }],
        "identity_fingerprint": {
            "version": IDENTITY_FINGERPRINT_VERSION,
            "work_ids": sorted(
                str(work.get("doi") or work.get("id") or "")
                for work in works
                if work.get("doi") or work.get("id")
            ),
            "coauthor_ids": coauthor_keys,
            "topic_ids": sorted(topic_ids),
            "topic_names": sorted(topic_names, key=str.casefold),
            "publication_years": publication_years,
            "sampled_works": len(works),
            "affiliations": fingerprint_affiliations,
        },
        "_provisional_work_ids": [
            str(work.get("id") or "") for work in works if work.get("id")
        ],
        "_provisional_works": works,
    }


def discover_provisional_authors(
    name: str,
    *,
    api_key: str,
    budget_provider: str,
) -> list[dict]:
    """Create review-only candidates from exact paper authorships lacking IDs."""
    works = _search_works_by_raw_author(
        name,
        api_key=api_key,
        budget_provider=budget_provider,
    )
    records = _provisional_authorship_records(name, works)
    candidates = [
        _build_provisional_candidate(component, records)
        for component in _provisional_components(records)
    ]
    for candidate in candidates:
        candidate.pop("_provisional_work_ids", None)
        candidate.pop("_provisional_works", None)
    return sorted(candidates, key=_author_search_rank, reverse=True)[:20]


def get_provisional_author_bundle(
    author_id: str,
    *,
    api_key: str,
    budget_provider: str,
) -> tuple[dict, list[dict]]:
    """Resolve a publication-anchored candidate into a conservative paper cluster."""
    work_id, authorship_index = _parse_provisional_author_id(author_id)
    anchor_work = get_work(
        work_id,
        api_key=api_key,
        budget_provider=budget_provider,
    )
    authorships = anchor_work.get("authorships") or []
    if authorship_index >= len(authorships):
        raise OpenAlexError("OpenAlex anchor authorship no longer exists", status_code=404)
    name = _authorship_name(authorships[authorship_index])
    works = _search_works_by_raw_author(
        name,
        api_key=api_key,
        budget_provider=budget_provider,
    )
    if not any(_entity_id(work.get("id")) == work_id for work in works):
        works.append(anchor_work)
    records = _provisional_authorship_records(name, works)
    anchor_record_index = next(
        (
            index
            for index, record in enumerate(records)
            if _entity_id(record["work"].get("id")) == work_id
            and record["authorship_index"] == authorship_index
        ),
        None,
    )
    if anchor_record_index is None:
        raise OpenAlexError("OpenAlex anchor authorship cannot be matched", status_code=404)
    component = next(
        component
        for component in _provisional_components(records)
        if anchor_record_index in component
    )
    candidate = _build_provisional_candidate(
        component,
        records,
        requested_id=author_id,
    )
    provisional_works = candidate.pop("_provisional_works")
    candidate.pop("_provisional_work_ids", None)
    for work in provisional_works:
        for index, authorship in enumerate(work.get("authorships") or []):
            if not _exact_person_name_match(name, _authorship_name(authorship)):
                continue
            author = dict(authorship.get("author") or {})
            if author.get("id"):
                continue
            author["id"] = author_id
            author["display_name"] = name
            authorship["author"] = author
    candidate["merged_author_ids"] = [author_id]
    candidate["provisional"] = True
    return candidate, provisional_works


def get_author(author_id: str, *, api_key: str, budget_provider: str) -> dict:
    """获取单个作者的详细信息。"""
    return _get(
        f"/authors/{_entity_id(author_id)}",
        api_key=api_key,
        budget_provider=budget_provider,
    )


def group_works(
    *,
    topic_ids: list[str],
    group_by: str,
    published_since: str | None,
    api_key: str,
    budget_provider: str,
    per_page: int = 200,
) -> list[dict]:
    """Group works for a bounded topic set without persisting scholarly facts.

    The grouping response is used only to choose which existing stage-2 graph
    entities should be enriched next. Recommendations never use these counts
    directly.
    """
    normalized_topic_ids = list(dict.fromkeys(
        _entity_id(value)
        for value in topic_ids
        if _entity_id(value)
    ))
    if not normalized_topic_ids:
        return []
    filters = [f"topics.id:{'|'.join(normalized_topic_ids)}"]
    if published_since:
        filters.append(f"from_publication_date:{published_since}")
    data = _get(
        "/works",
        api_key=api_key,
        budget_provider=budget_provider,
        filter=",".join(filters),
        group_by=group_by,
        per_page=min(max(1, per_page), 200),
    )
    rows = data.get("group_by") or data.get("groups") or []
    return [
        {
            "key": str(row.get("key") or ""),
            "name": str(
                row.get("key_display_name")
                or row.get("display_name")
                or row.get("key")
                or ""
            ),
            "count": max(0, int(row.get("count") or 0)),
        }
        for row in rows
        if row.get("key")
    ]


def count_works(
    *,
    topic_ids: list[str],
    institution_id: str,
    published_since: str | None,
    api_key: str,
    budget_provider: str,
) -> int:
    """Count topic-matching works for one institution.

    Field discovery normally gets institution counts from a bounded grouping.
    This focused query fills the current scholar's primary institution when it
    falls outside that grouping, so institution comparison always has two
    evidence-bearing sides.
    """
    normalized_topic_ids = list(dict.fromkeys(
        _entity_id(value)
        for value in topic_ids
        if _entity_id(value)
    ))
    normalized_institution_id = _entity_id(institution_id)
    if not normalized_topic_ids or not normalized_institution_id:
        return 0
    filters = [
        f"topics.id:{'|'.join(normalized_topic_ids)}",
        f"institutions.id:{normalized_institution_id}",
    ]
    if published_since:
        filters.append(f"from_publication_date:{published_since}")
    data = _get(
        "/works",
        api_key=api_key,
        budget_provider=budget_provider,
        filter=",".join(filters),
        per_page=1,
        select="id",
    )
    return int((data.get("meta") or {}).get("count") or 0)


def get_author_identity_fingerprint(
    author_id: str,
    per_page: int = IDENTITY_FINGERPRINT_WORKS,
    *,
    api_key: str,
    budget_provider: str,
) -> dict:
    """获取用于身份消歧的轻量论文、合作者和主题指纹。"""
    normalized_author_id = _entity_id(author_id)
    data = _get(
        "/works",
        api_key=api_key,
        budget_provider=budget_provider,
        filter=f"authorships.author.id:{normalized_author_id}",
        per_page=min(max(per_page, 1), 200),
        sort="cited_by_count:desc",
        select="id,doi,publication_year,authorships,primary_topic,topics",
    )
    work_ids = set()
    coauthor_ids = set()
    topic_ids = set()
    topic_names = set()
    publication_years = []
    affiliations_by_key = {}
    for work in data.get("results", []):
        work_key = work.get("doi") or work.get("id")
        if work_key:
            work_ids.add(str(work_key))
        publication_year = int(work["publication_year"]) if work.get("publication_year") else 0
        if publication_year:
            publication_years.append(publication_year)
        for authorship in work.get("authorships") or []:
            coauthor_id = (authorship.get("author") or {}).get("id")
            if coauthor_id and _entity_id(coauthor_id) != normalized_author_id:
                coauthor_ids.add(str(coauthor_id))
            if _entity_id(coauthor_id) != normalized_author_id:
                continue
            for institution in authorship.get("institutions") or []:
                name = str(institution.get("display_name") or "").strip()
                if not name:
                    continue
                key = str(institution.get("id") or name).strip().casefold()
                row = affiliations_by_key.setdefault(
                    key,
                    {
                        "id": institution.get("id"),
                        "name": name,
                        "years": set(),
                        "work_ids": set(),
                    },
                )
                if publication_year:
                    row["years"].add(publication_year)
                if work_key:
                    row["work_ids"].add(str(work_key))
        primary_topic = work.get("primary_topic") or {}
        if primary_topic.get("id"):
            topic_ids.add(str(primary_topic["id"]))
        if primary_topic.get("display_name"):
            topic_names.add(str(primary_topic["display_name"]).strip())
        for topic in work.get("topics") or []:
            if topic.get("id"):
                topic_ids.add(str(topic["id"]))
            if topic.get("display_name"):
                topic_names.add(str(topic["display_name"]).strip())
    affiliations = [
        {
            "id": row["id"],
            "name": row["name"],
            "years": sorted(row["years"], reverse=True),
            "work_count": len(row["work_ids"]),
        }
        for row in affiliations_by_key.values()
    ]
    affiliations.sort(
        key=lambda row: (
            max(row["years"], default=0),
            row["work_count"],
            row["name"].casefold(),
        ),
        reverse=True,
    )
    return {
        "version": IDENTITY_FINGERPRINT_VERSION,
        "work_ids": sorted(work_ids),
        "coauthor_ids": sorted(coauthor_ids),
        "topic_ids": sorted(topic_ids),
        "topic_names": sorted(topic_names, key=str.casefold),
        "publication_years": sorted(set(publication_years)),
        "sampled_works": len(data.get("results", [])),
        "affiliations": affiliations,
    }


def enrich_authors_for_disambiguation(
    candidates: List[dict],
    *,
    api_key: str,
    budget_provider: str,
) -> List[dict]:
    """并发补充身份指纹；单个请求失败时保留候选但不自动合并。"""
    enriched = [dict(candidate) for candidate in candidates]
    pending = {
        index: candidate
        for index, candidate in enumerate(enriched)
        if candidate.get("id") and not candidate.get("identity_fingerprint")
    }
    if not pending:
        return enriched
    workers = min(max(1, IDENTITY_MAX_WORKERS), len(pending))
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(
                get_author_identity_fingerprint,
                candidate["id"],
                api_key=api_key,
                budget_provider=budget_provider,
            ): index
            for index, candidate in pending.items()
        }
        for future in as_completed(futures):
            index = futures[future]
            try:
                enriched[index]["identity_fingerprint"] = future.result()
            except Exception as exc:
                enriched[index]["identity_fingerprint"] = {}
                enriched[index]["identity_warning"] = str(exc)
    return enriched


def get_works(
    author_id: str,
    max_pages: int = DEFAULT_MAX_PAGES,
    *,
    api_key: str,
    budget_provider: str,
) -> tuple[List[dict], list[str]]:
    """获取作者的全部论文（游标分页），失败时尽量返回已取得的部分结果。"""
    works = []
    warnings = []
    cursor = "*"
    page = 0
    while cursor and page < max_pages:
        page += 1
        try:
            data = _get("/works",
                        api_key=api_key,
                        budget_provider=budget_provider,
                        filter=f"authorships.author.id:{_entity_id(author_id)}",
                        per_page=200,
                        cursor=cursor,
                        sort="cited_by_count:desc",
                        select=(
                            "id,doi,title,publication_year,cited_by_count,authorships,concepts,"
                            "primary_topic,topics,keywords,primary_location,type"
                        ))
        except OpenAlexError as exc:
            if works:
                warnings.append(f"OpenAlex 部分论文获取失败，已保留 {len(works)} 篇部分结果: {exc}")
                return works, warnings
            raise
        works.extend(data.get("results", []))
        cursor = data.get("meta", {}).get("next_cursor")
    if cursor:
        warnings.append(f"OpenAlex 论文分页达到上限 {max_pages} 页，结果可能不完整")
    return works, warnings


def get_graph_works(
    author_id: str,
    *,
    published_since: str | None,
    api_key: str,
    budget_provider: str,
    max_pages: int = DEFAULT_MAX_PAGES,
) -> tuple[List[dict], list[str], bool]:
    """Fetch graph fields, optionally only recently published works.

    Unlike the profile collector, this function never presents a partial page
    sequence as successful because graph persistence is an atomic batch.
    Publication-date filtering is used because OpenAlex free plans reject
    ``from_updated_date`` and ``sort=updated_date`` as paid capabilities.
    """
    works: List[dict] = []
    warnings: list[str] = []
    cursor = "*"
    page = 0
    filters = [f"authorships.author.id:{_entity_id(author_id)}"]
    if published_since:
        filters.append(f"from_publication_date:{published_since}")

    while cursor and page < max_pages:
        page += 1
        try:
            data = _get(
                "/works",
                api_key=api_key,
                budget_provider=budget_provider,
                filter=",".join(filters),
                per_page=200,
                cursor=cursor,
                sort="publication_date:desc",
                select=(
                    "id,doi,title,publication_year,publication_date,cited_by_count,"
                    "authorships,abstract_inverted_index,referenced_works,primary_topic,"
                    "topics,keywords,primary_location,type,language,updated_date"
                ),
            )
        except OpenAlexError as exc:
            warnings.append(
                f"OpenAlex 图谱批次在第 {page} 页失败；本批次未写入: {exc}"
            )
            return works, warnings, False
        works.extend(data.get("results", []))
        cursor = data.get("meta", {}).get("next_cursor")

    if cursor:
        warnings.append(
            f"OpenAlex 图谱分页达到上限 {max_pages} 页；本批次未写入"
        )
        return works, warnings, False
    return works, warnings, True
