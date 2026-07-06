"""OpenAlex API 客户端。封装所有与 OpenAlex 的 HTTP 通信。"""
import os
import time
from typing import List

import requests

BASE = "https://api.openalex.org"
HEADERS = {"User-Agent": "mailto:demo@example.com"}
MAX_RETRIES = 3
RETRY_STATUSES = {429, 500, 502, 503, 504}
DEFAULT_MAX_PAGES = int(os.getenv("OPENALEX_MAX_WORK_PAGES", "200"))
_SESSION = requests.Session()


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


def search_authors(name: str, per_page: int = 50) -> List[dict]:
    """按姓名搜索作者，返回候选列表。"""
    data = _get("/authors",
                filter=f"display_name.search:{name}",
                per_page=per_page,
                sort="cited_by_count:desc",
                select="id,display_name,works_count,cited_by_count,summary_stats,last_known_institutions")
    return data.get("results", [])


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
