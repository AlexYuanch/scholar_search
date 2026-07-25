"""LangGraph 工作流定义。

DAG 结构（多来源裁决 + Agent 分析 + 证据审查）:

  fetch_profile → collect_works → dedup_works → collect_crossref → adjudicate_sources
                                                                ↓
                                                        plan_agents
                                                                ↓
                                          ┌──────────────────────┴──────────────────────┐
                                          ↓                                             ↓
                                  analyze_citations                          agent_analyze_topics
                                          ↓                                             ↓
                                          └─────────→ analyze_evolution ←──────────────┘
                                                          ↓
                                                analyze_trajectory_agent
                                                          ↓
                                                analyze_coauthors
                                                          ↓
                                                   build_graph
                                                          ↓
                                                generate_report → review_report_agent
                                                                          ↓
                                                                  review_evidence
                                                          ↓
                                                format_payload → END
"""
from langgraph.graph import StateGraph, END
from state import ScholarProfileState, default_state
from nodes import (
    fetch_author_profile,
    collect_works,
    deduplicate_works,
    collect_crossref_records,
    adjudicate_sources,
    plan_agent_analysis,
    analyze_citations,
    agent_analyze_topics,
    analyze_interest_evolution,
    agent_analyze_trajectory,
    analyze_coauthors,
    build_collaboration_graph,
    generate_profile_report,
    agent_review_profile,
    review_profile_evidence,
    format_web_payload,
)

NODES = [
    ("fetch_profile", fetch_author_profile),
    ("collect_works", collect_works),

    ("dedup_works", deduplicate_works),
    ("collect_crossref", collect_crossref_records),
    ("adjudicate_sources", adjudicate_sources),
    ("plan_agents", plan_agent_analysis),
    ("analyze_citations", analyze_citations),
    ("agent_analyze_topics", agent_analyze_topics),
    ("analyze_evolution", analyze_interest_evolution),
    ("agent_analyze_trajectory", agent_analyze_trajectory),
    ("analyze_coauthors", analyze_coauthors),
    ("build_graph", build_collaboration_graph),
    ("generate_report", generate_profile_report),
    ("agent_review_report", agent_review_profile),
    ("review_evidence", review_profile_evidence),
    ("format_payload", format_web_payload),
]


def build() -> StateGraph:
    builder = StateGraph(ScholarProfileState)
    for name, func in NODES:
        builder.add_node(name, func)

    # 串行头
    builder.set_entry_point("fetch_profile")

    # 串行获取 → 去重 → 跨来源核验与裁决
    builder.add_edge("fetch_profile", "collect_works")
    builder.add_edge("collect_works", "dedup_works")
    builder.add_edge("dedup_works", "collect_crossref")
    builder.add_edge("collect_crossref", "adjudicate_sources")

    # 并行分析
    builder.add_edge("adjudicate_sources", "plan_agents")
    builder.add_edge("plan_agents", "analyze_citations")
    builder.add_edge("plan_agents", "agent_analyze_topics")

    # Agent 完成后 → 兴趣演化
    builder.add_edge("agent_analyze_topics", "analyze_evolution")
    builder.add_edge("analyze_evolution", "agent_analyze_trajectory")

    # 汇聚后 → 合作网络
    builder.add_edge(["analyze_citations", "agent_analyze_trajectory"], "analyze_coauthors")

    # 串行尾
    builder.add_edge("analyze_coauthors", "build_graph")
    builder.add_edge("build_graph", "generate_report")
    builder.add_edge("generate_report", "agent_review_report")
    builder.add_edge("agent_review_report", "review_evidence")
    builder.add_edge("review_evidence", "format_payload")
    builder.add_edge("format_payload", END)

    return builder.compile()


graph = build()
