"""LangGraph 工作流定义。

DAG 结构（单数据源 + Agent 驱动）:

  fetch_profile → collect_works → dedup_works
                                                                ↓
                                          ┌──────────────────────┴──────────────────────┐
                                          ↓                                             ↓
                                  analyze_citations                          agent_analyze_topics
                                          ↓                                             ↓
                                          └─────────→ analyze_evolution ←──────────────┘
                                                          ↓
                                                analyze_coauthors
                                                          ↓
                                                   build_graph
                                                          ↓
                                                generate_report
                                                          ↓
                                                format_payload → END
"""
from langgraph.graph import StateGraph, END
from state import ScholarProfileState, default_state
from nodes import (
    fetch_author_profile,
    collect_works,
    deduplicate_works,
    analyze_citations,
    agent_analyze_topics,
    analyze_interest_evolution,
    analyze_coauthors,
    build_collaboration_graph,
    generate_profile_report,
    format_web_payload,
)

NODES = [
    ("fetch_profile", fetch_author_profile),
    ("collect_works", collect_works),

    ("dedup_works", deduplicate_works),
    ("analyze_citations", analyze_citations),
    ("agent_analyze_topics", agent_analyze_topics),
    ("analyze_evolution", analyze_interest_evolution),
    ("analyze_coauthors", analyze_coauthors),
    ("build_graph", build_collaboration_graph),
    ("generate_report", generate_profile_report),
    ("format_payload", format_web_payload),
]


def build() -> StateGraph:
    builder = StateGraph(ScholarProfileState)
    for name, func in NODES:
        builder.add_node(name, func)

    # 串行头
    builder.set_entry_point("fetch_profile")

    # 串行获取 → 去重
    builder.add_edge("fetch_profile", "collect_works")
    builder.add_edge("collect_works", "dedup_works")

    # 并行分析
    builder.add_edge("dedup_works", "analyze_citations")
    builder.add_edge("dedup_works", "agent_analyze_topics")

    # Agent 完成后 → 兴趣演化
    builder.add_edge("agent_analyze_topics", "analyze_evolution")

    # 汇聚后 → 合作网络
    builder.add_edge("analyze_citations", "analyze_coauthors")
    builder.add_edge("analyze_evolution", "analyze_coauthors")

    # 串行尾
    builder.add_edge("analyze_coauthors", "build_graph")
    builder.add_edge("build_graph", "generate_report")
    builder.add_edge("generate_report", "format_payload")
    builder.add_edge("format_payload", END)

    return builder.compile()


graph = build()
