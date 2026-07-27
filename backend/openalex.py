"""OpenAlex API 客户端。封装所有与 OpenAlex 的 HTTP 通信。"""
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
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
    for work in data.get("results", []):
        work_key = work.get("doi") or work.get("id")
        if work_key:
            work_ids.add(str(work_key))
        if work.get("publication_year"):
            publication_years.append(int(work["publication_year"]))
        for authorship in work.get("authorships") or []:
            coauthor_id = (authorship.get("author") or {}).get("id")
            if coauthor_id and _entity_id(coauthor_id) != normalized_author_id:
                coauthor_ids.add(str(coauthor_id))
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
    return {
        "work_ids": sorted(work_ids),
        "coauthor_ids": sorted(coauthor_ids),
        "topic_ids": sorted(topic_ids),
        "topic_names": sorted(topic_names, key=str.casefold),
        "publication_years": sorted(set(publication_years)),
        "sampled_works": len(data.get("results", [])),
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
