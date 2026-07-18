"""OpenAlex API 客户端。封装所有与 OpenAlex 的 HTTP 通信。"""
import os
import re
import time
from typing import List

import requests

try:
    from pypinyin import Style, lazy_pinyin
except ImportError:  # 允许未同步依赖的开发环境先正常启动
    Style = None
    lazy_pinyin = None

PINYIN_AVAILABLE = lazy_pinyin is not None and Style is not None

BASE = "https://api.openalex.org"
HEADERS = {"User-Agent": "mailto:demo@example.com"}
MAX_RETRIES = 3
RETRY_STATUSES = {429, 500, 502, 503, 504}
DEFAULT_MAX_PAGES = int(os.getenv("OPENALEX_MAX_WORK_PAGES", "200"))
_SESSION = requests.Session()
_CHINESE_RE = re.compile(r"[\u3400-\u9fff]")


class OpenAlexError(RuntimeError):
    """Raised when OpenAlex cannot satisfy a request."""


def _get(endpoint: str, **params) -> dict:
    """GET JSON from OpenAlex with retry for transient failures."""
    last_error: Exception | None = None
    url = f"{BASE}{endpoint}"
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = _SESSION.get(url, params=params, headers=HEADERS, timeout=30)
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
    raise OpenAlexError(f"OpenAlex 请求失败: {endpoint}; {last_error}") from last_error


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


def search_authors(name: str, per_page: int = 50) -> List[dict]:
    """按姓名搜索作者；中文姓名会同时搜索常见的两种拼音顺序。"""
    authors_by_id = {}
    for variant in _name_query_variants(name):
        data = _get(
            "/authors",
            filter=f"display_name.search:{variant}",
            per_page=per_page,
            sort="cited_by_count:desc",
            select=(
                "id,display_name,display_name_alternatives,orcid,works_count,"
                "cited_by_count,summary_stats,last_known_institutions"
            ),
        )
        for author in data.get("results", []):
            author_id = author.get("id")
            if author_id and author_id not in authors_by_id:
                authors_by_id[author_id] = author

    return sorted(authors_by_id.values(), key=_author_search_rank, reverse=True)[:100]


def get_author(author_id: str) -> dict:
    """获取单个作者的详细信息。"""
    return _get(f"/authors/{author_id}")


def get_works(author_id: str, max_pages: int = DEFAULT_MAX_PAGES) -> tuple[List[dict], list[str]]:
    """获取作者的全部论文（游标分页），失败时尽量返回已取得的部分结果。"""
    works = []
    warnings = []
    cursor = "*"
    page = 0
    while cursor and page < max_pages:
        page += 1
        try:
            data = _get("/works",
                        filter=f"authorships.author.id:{author_id}",
                        per_page=200,
                        cursor=cursor,
                        sort="cited_by_count:desc",
                        select="id,doi,title,publication_year,cited_by_count,authorships,concepts,primary_location,type")
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
