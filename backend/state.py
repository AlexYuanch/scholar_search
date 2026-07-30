"""学者画像工作流的状态定义。"""
import operator
from typing import Annotated, TypedDict, List, Dict, Any, Optional


class ScholarProfileState(TypedDict):
    """LangGraph 工作流的全局状态。字段按处理阶段分组。"""

    # ── 学者身份 ──
    target_author_id: Optional[str]
    target_author_ids: List[str]
    target_author_profile: Optional[Dict[str, Any]]
    identity_audit: Dict[str, Any]
    provisional_works: List[Dict[str, Any]]
    orcid_works: List[Dict[str, Any]]
    orcid_audit: Dict[str, Any]

    # ── 论文数据 ──
    raw_works: List[Dict[str, Any]]
    deduped_works: List[Dict[str, Any]]
    source_works: Dict[str, List[Dict[str, Any]]]
    source_audit: Dict[str, Any]
    adjudicated_works: List[Dict[str, Any]]
    data_audit: Dict[str, Any]
    works_complete: bool

    # ── 引用分析（含年度趋势） ──
    citation_summary: Dict[str, Any]

    # ── 研究方向 ──
    topic_clusters: List[Dict[str, Any]]
    agent_plan: Dict[str, Any]
    agent_runs: Annotated[List[Dict[str, Any]], operator.add]
    orchestrator_tasks: List[Dict[str, Any]]
    worker_task: Dict[str, Any]
    worker_context: Dict[str, Any]
    worker_outputs: Annotated[List[Dict[str, Any]], operator.add]
    orchestrator_analysis: Dict[str, Any]

    # ── 兴趣演化 ──
    interest_timeline: List[Dict[str, Any]]
    trajectory_analysis: Dict[str, Any]

    # ── 代表论文 ──
    representative_papers: Dict[str, List[Dict[str, Any]]]

    # ── 合作网络 ──
    coauthors: List[Dict[str, Any]]
    graph_nodes: List[Dict[str, Any]]
    graph_edges: List[Dict[str, Any]]

    # ── 最终输出 ──
    profile_summary: str
    profile_summary_i18n: Dict[str, str]
    profile_evidence: List[Dict[str, Any]]
    analysis_claims: List[Dict[str, Any]]
    agent_review: Dict[str, Any]
    review_iteration: int
    review_history: Annotated[List[Dict[str, Any]], operator.add]
    evidence_review: Dict[str, Any]
    web_payload: Dict[str, Any]

    # ── 运行信息 ──
    openalex_api_key: str
    openalex_budget_provider: str
    warnings: Annotated[List[str], operator.add]
    errors: List[str]


def default_state() -> Dict[str, Any]:
    """创建一个初始空状态，方便 FastAPI 调用。"""
    return {
        "target_author_id": None,
        "target_author_ids": [],
        "target_author_profile": None,
        "identity_audit": {},
        "provisional_works": [],
        "orcid_works": [],
        "orcid_audit": {},
        "raw_works": [],
        "deduped_works": [],
        "source_works": {},
        "source_audit": {},
        "adjudicated_works": [],
        "data_audit": {},
        "works_complete": False,
        "citation_summary": {},
        "topic_clusters": [],
        "agent_plan": {},
        "agent_runs": [],
        "orchestrator_tasks": [],
        "worker_task": {},
        "worker_context": {},
        "worker_outputs": [],
        "orchestrator_analysis": {},
        "interest_timeline": [],
        "trajectory_analysis": {},
        "representative_papers": {},
        "coauthors": [],
        "graph_nodes": [],
        "graph_edges": [],
        "profile_summary": "",
        "profile_summary_i18n": {},
        "profile_evidence": [],
        "analysis_claims": [],
        "agent_review": {},
        "review_iteration": 0,
        "review_history": [],
        "evidence_review": {},
        "web_payload": {},
        "openalex_api_key": "",
        "openalex_budget_provider": "",
        "warnings": [],
        "errors": [],
    }
