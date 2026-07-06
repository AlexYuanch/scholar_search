"""学者画像工作流的状态定义。"""
import operator
from typing import Annotated, TypedDict, List, Dict, Any, Optional


class ScholarProfileState(TypedDict):
    """LangGraph 工作流的全局状态。字段按处理阶段分组。"""

    # ── 用户输入 ──
    query_name: str
    optional_institution: Optional[str]

    # ── 学者身份 ──
    candidate_authors: List[Dict[str, Any]]
    target_author_id: Optional[str]
    target_author_profile: Optional[Dict[str, Any]]

    # ── 论文数据 ──
    raw_works: List[Dict[str, Any]]
    deduped_works: List[Dict[str, Any]]

    # ── 引用分析（含年度趋势） ──
    citation_summary: Dict[str, Any]

    # ── 研究方向 ──
    topic_clusters: List[Dict[str, Any]]

    # ── 兴趣演化 ──
    interest_timeline: List[Dict[str, Any]]

    # ── 代表论文 ──
    representative_papers: Dict[str, List[Dict[str, Any]]]

    # ── 合作网络 ──
    coauthors: List[Dict[str, Any]]
    graph_nodes: List[Dict[str, Any]]
    graph_edges: List[Dict[str, Any]]

    # ── 最终输出 ──
    profile_summary: str
    profile_evidence: List[Dict[str, Any]]
    web_payload: Dict[str, Any]

    # ── 运行信息 ──
    warnings: Annotated[List[str], operator.add]
    errors: List[str]


def default_state() -> Dict[str, Any]:
    """创建一个初始空状态，方便 FastAPI 调用。"""
    return {
        "query_name": "",
        "optional_institution": None,
        "candidate_authors": [],
        "target_author_id": None,
        "target_author_profile": None,
        "raw_works": [],
        "deduped_works": [],
        "citation_summary": {},
        "topic_clusters": [],
        "interest_timeline": [],
        "representative_papers": {},
        "coauthors": [],
        "graph_nodes": [],
        "graph_edges": [],
        "profile_summary": "",
        "profile_evidence": [],
        "web_payload": {},
        "warnings": [],
        "errors": [],
    }
