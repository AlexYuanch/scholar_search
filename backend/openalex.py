"""OpenAlex API 客户端。封装所有与 OpenAlex 的 HTTP 通信。"""
import requests
from typing import Any, List

BASE = "https://api.openalex.org"
HEADERS = {"User-Agent": "mailto:demo@example.com"}


def _get(endpoint: str, **params) -> dict:
    r = requests.get(f"{BASE}{endpoint}", params=params, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return r.json()


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


def get_works(author_id: str) -> List[dict]:
    """获取作者的全部论文（游标分页）。"""
    works = []
    cursor = "*"
    while cursor:
        data = _get("/works",
                    filter=f"authorships.author.id:{author_id}",
                    per_page=200,
                    cursor=cursor,
                    select="id,doi,title,publication_year,cited_by_count,authorships,concepts,primary_location,type")
        works.extend(data.get("results", []))
        cursor = data.get("meta", {}).get("next_cursor")
    return works
