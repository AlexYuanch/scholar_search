"""LangGraph 工作流的节点函数。

每个节点接收当前 state，返回要更新的字段 dict。
节点按处理阶段分组，与 workflow.py 中的图定义一一对应。
"""
import json
import re
from collections import defaultdict
from state import ScholarProfileState


# ── 工具函数 ─────────────────────────────────────────────────

def dedup_authors(candidates):
    """仅按稳定的 OpenAlex 作者 ID 去重，绝不合并不同 ID 的同名作者。"""
    groups = defaultdict(list)
    for index, a in enumerate(candidates):
        key = a.get("id") or f"__missing_id_{index}"
        groups[key].append(a)
    result = []
    for group in groups.values():
        best = dict(max(group, key=lambda a: a.get("works_count", 0)))
        best["works_count"] = max(a.get("works_count", 0) for a in group)
        best["cited_by_count"] = max(a.get("cited_by_count", 0) for a in group)
        hs = [a.get("summary_stats", {}).get("h_index", 0) or 0 for a in group]
        best["summary_stats"] = {"h_index": max(hs)}
        institutions = []
        for item in group:
            for inst in item.get("last_known_institutions") or []:
                name = inst.get("display_name", "").strip()
                if name and name not in institutions:
                    institutions.append(name)
        best["institutions"] = institutions
        best["merged_ids"] = sorted({a.get("id", "") for a in group if a.get("id")})
        best["merged_count"] = len(best["merged_ids"])
        best["disambiguation"] = ""
        result.append(best)
    return result


def fetch_author_profile(state: ScholarProfileState) -> dict:
    """获取选定作者的详细信息。"""
    from openalex import get_author
    profile = get_author(state["target_author_id"])
    return {"target_author_profile": profile}


# ── 阶段二: 论文获取与去重 ──────────────────────────────────

def collect_works(state: ScholarProfileState) -> dict:
    """获取作者全部论文（游标分页）。"""
    from openalex import get_works
    warnings = []
    works_complete = True
    try:
        works, fetch_warnings = get_works(state["target_author_id"])
        warnings.extend(fetch_warnings)
        if fetch_warnings:
            works_complete = False
    except Exception as exc:
        works = []
        works_complete = False
        warnings.append(f"OpenAlex 论文获取失败，后续分析将基于空论文集: {exc}")
    if state["target_author_profile"]:
        expected = state["target_author_profile"].get("works_count", 0)
        if len(works) < expected:
            warnings.append(f"预期 {expected} 篇，实际获取 {len(works)} 篇（OpenAlex 限制）")
    return {"raw_works": works, "works_complete": works_complete, "warnings": warnings}




def deduplicate_works(state: ScholarProfileState) -> dict:
    """按 DOI 或 ID 去重论文。"""
    seen = set()
    deduped = []
    for w in state["raw_works"]:
        key = w.get("doi") or w.get("id")
        if key and key not in seen:
            seen.add(key)
            deduped.append(w)
    count = len(state["raw_works"]) - len(deduped)
    new_w = [f"去重移除 {count} 篇重复论文"] if count else []
    return {"deduped_works": deduped, "warnings": new_w}


# ── 阶段三: 并行分析 ────────────────────────────────────────

def analyze_citations(state: ScholarProfileState) -> dict:
    """统计总论文数、总引用数、h-index、年度趋势。"""
    works = state["deduped_works"]
    cites = sorted([w.get("cited_by_count", 0) for w in works], reverse=True)
    h = 0
    for i, c in enumerate(cites, 1):
        if c >= i:
            h = i
        else:
            break
    yearly = defaultdict(lambda: {"papers": 0, "citations": 0})
    for w in works:
        y = w.get("publication_year")
        if y:
            yearly[y]["papers"] += 1
            yearly[y]["citations"] += w.get("cited_by_count", 0)
    return {"citation_summary": {
        "total_papers": len(works),
        "total_citations": sum(cites),
        "h_index": h,
        "yearly_trend": [{"year": y, **v} for y, v in sorted(yearly.items())],
    }}


# ── 阶段四: Agent 驱动的方向分析 ──────────────────────────

def _fallback_topic_analysis(works: list) -> dict:
    """LLM 不可用时的回退方案 — 按 OpenAlex 概念聚合，排除 level-0 宽泛概念。"""
    # 只聚合 level >= 1 的概念，排除 "Computer Science" 等大词
    scores = defaultdict(float)
    paper_concepts = []
    for w in works:
        cs = {c["display_name"]: c["score"]
              for c in (w.get("concepts") or []) if c.get("level", 0) >= 1}
        paper_concepts.append(cs)
        for name, s in cs.items():
            scores[name] += s

    total = sum(scores.values()) or 1
    clusters = []
    for name, s in sorted(scores.items(), key=lambda x: -x[1])[:10]:
        clusters.append({
            "topic": name,
            "weight": round(s / total, 3),
            "score": round(s, 1),
            "paper_indices": [i for i, cs in enumerate(paper_concepts) if name in cs],
        })

    # 为每个 topic 选代表论文
    representative_papers = {}
    for t in clusters:
        name = t["topic"]
        indices = t["paper_indices"]
        # 先按引用数排序，取 top 3
        sorted_idx = sorted(indices, key=lambda i: -(works[i].get("cited_by_count") or 0))
        repr_list = []
        for idx in sorted_idx[:3]:
            w = works[idx]
            repr_list.append({
                "title": w.get("title", ""),
                "year": w.get("publication_year"),
                "citations": w.get("cited_by_count", 0),
                "journal": ((w.get("primary_location") or {}).get("source") or {}).get("display_name", ""),
                "doi": w.get("doi", ""),
                "id": w.get("id", ""),
            })
        representative_papers[name] = repr_list

    return {"topic_clusters": clusters, "representative_papers": representative_papers}


def agent_analyze_topics(state: ScholarProfileState) -> dict:
    """使用 LLM Agent 分析研究方向并选择代表论文（每个方向实事求是，不强制数量）。"""
    works = state["deduped_works"]
    if not works:
        return {"topic_clusters": [], "representative_papers": {}}

    # 准备论文摘要数据
    papers_data = []
    for i, w in enumerate(works):
        papers_data.append({
            "index": i,
            "title": w.get("title", ""),
            "year": w.get("publication_year"),
            "citations": w.get("cited_by_count", 0),
            "concepts": [c["display_name"] for c in (w.get("concepts") or [])],
        })

    try:
        from llm import analyze_topics
        result = analyze_topics(papers_data)

        topics = result.topics
        if not topics:
            raise ValueError("Agent 未返回任何方向")

        topic_clusters = []
        representative_papers = {}
        total = max(len(works), 1)

        for t in topics:
            all_idx = [i for i in t.all_paper_indices if 0 <= i < len(works)]
            if not all_idx:
                continue

            weight = round(len(all_idx) / total, 3)
            score = round(sum(works[i].get("cited_by_count", 0) for i in all_idx), 1)

            topic_clusters.append({
                "topic": t.name,
                "description": t.description,
                "weight": weight,
                "score": score,
                "paper_indices": all_idx,
            })

            # 代表论文：取 LLM 推荐的，若没有则按引用数取前 3
            repr_idx = [i for i in t.representative_paper_indices if 0 <= i < len(works)]
            chosen = repr_idx if repr_idx else sorted(all_idx, key=lambda i: -(works[i].get("cited_by_count") or 0))[:3]
            repr_list = []
            for idx in chosen:
                w = works[idx]
                repr_list.append({
                    "title": w.get("title", ""),
                    "year": w.get("publication_year"),
                    "citations": w.get("cited_by_count", 0),
                    "journal": ((w.get("primary_location") or {}).get("source") or {}).get("display_name", ""),
                    "doi": w.get("doi", ""),
                    "id": w.get("id", ""),
                })
            representative_papers[t.name] = repr_list

        if not topic_clusters:
            raise ValueError("Agent 未能产出有效方向")

        print(f"[AGENT] ✓ 成功，产出 {len(topic_clusters)} 个方向")
        return {"topic_clusters": topic_clusters, "representative_papers": representative_papers, "warnings": ["Agent驱动方向分析 ✓"]}

    except Exception as e:
        warnings = [f"LLM 分析失败，回退到规则模式: {e}"]
        fallback = _fallback_topic_analysis(works)
        fallback["warnings"] = warnings
        return fallback


# ── 阶段五: 兴趣演化 ────────────────────────────────────────

def analyze_interest_evolution(state: ScholarProfileState) -> dict:
    """按年度跟踪 Agent 定义的研究方向的活跃度变化。"""
    # 建立 paper_index → 方向名称 的映射
    paper_to_topics = defaultdict(list)
    for t in state["topic_clusters"]:
        name = t["topic"]
        indices = t.get("paper_indices")
        if indices is not None:
            for idx in indices:
                paper_to_topics[idx].append(name)
        else:
            # 回退：按概念名匹配
            for i, w in enumerate(state["deduped_works"]):
                for c in w.get("concepts") or []:
                    if c["display_name"] == name:
                        paper_to_topics[i].append(name)
                        break

    # 按年份统计 topic 出现频次
    yearly = defaultdict(lambda: defaultdict(int))
    for i, w in enumerate(state["deduped_works"]):
        y = w.get("publication_year")
        if y is None:
            continue
        for t in paper_to_topics.get(i, []):
            yearly[y][t] += 1

    timeline = []
    for y, scores in sorted(yearly.items()):
        timeline.append({
            "year": y,
            "topics": [{"topic": t, "count": c}
                      for t, c in sorted(scores.items(), key=lambda x: -x[1])[:5]],
        })

    return {"interest_timeline": timeline}


# ── 阶段六: 合作网络 ────────────────────────────────────────

def analyze_coauthors(state: ScholarProfileState) -> dict:
    """按 OpenAlex author id 统计合作作者，避免同名不同人被混合。"""
    paper_agent_topics = defaultdict(list)
    for t in state["topic_clusters"]:
        topic_name = t["topic"]
        for idx in t.get("paper_indices", []):
            paper_agent_topics[idx].append(topic_name)

    raw = defaultdict(lambda: {
        "names": set(),
        "institutions": set(),
        "paper_ids": set(),
        "paper_details": [],
    })

    for i, w in enumerate(state["deduped_works"]):
        agent_topics = paper_agent_topics.get(
            i,
            [c["display_name"] for c in (w.get("concepts") or [])[:3]],
        )
        paper_id = w.get("id", "")

        for au in w.get("authorships") or []:
            aid = (au.get("author") or {}).get("id")
            if aid and aid != state["target_author_id"]:
                name = (au.get("author") or {}).get("display_name", "?")
                entry = raw[aid]
                entry["names"].add(name)
                for institution in au.get("institutions") or []:
                    institution_name = institution.get("display_name", "").strip()
                    if institution_name:
                        entry["institutions"].add(institution_name)

                if paper_id and paper_id not in entry["paper_ids"]:
                    entry["paper_ids"].add(paper_id)
                    entry["paper_details"].append({
                        "title": w.get("title", ""),
                        "id": paper_id,
                        "topics": agent_topics,
                    })

    coauthors = []
    for aid, entry in raw.items():
        coauthors.append({
            "name": sorted(entry["names"])[0],
            "id": aid,
            "institution": sorted(entry["institutions"])[0] if entry["institutions"] else "",
            "papers": len(entry["paper_ids"]),
            "paper_titles": entry["paper_details"],
        })

    coauthors.sort(key=lambda x: -x["papers"])
    return {"coauthors": coauthors[:30]}


def build_collaboration_graph(state: ScholarProfileState) -> dict:
    """从合作作者数据构建网络图的节点和边（含合作论文列表）。"""
    profile = state["target_author_profile"] or {}
    center_id = state["target_author_id"]
    center_name = profile.get("display_name", "")
    nodes = [{"id": center_id, "name": center_name, "type": "center"}]
    edges = []
    for c in state["coauthors"][:20]:
        nodes.append({
            "id": c["id"],
            "name": c["name"],
            "institution": c.get("institution", ""),
            "type": "coauthor",
        })
        edges.append({
            "source": center_id,
            "target": c["id"],
            "weight": c["papers"],
            "papers": c.get("paper_titles", []),
        })
    return {"graph_nodes": nodes, "graph_edges": edges}


# ── 阶段七: 最终输出 ────────────────────────────────────────

def _flatten_representative_papers(representative_papers: dict) -> list[dict]:
    papers = []
    seen = set()
    for items in representative_papers.values():
        for paper in items:
            key = paper.get("doi") or paper.get("id") or paper.get("title")
            if key and key not in seen:
                seen.add(key)
                papers.append(paper)
    return papers


def _build_profile_evidence(state: ScholarProfileState, inst_name: str) -> list[dict]:
    cs = state["citation_summary"]
    evidence = [{
        "id": "1",
        "type": "metric",
        "text": (
            f"OpenAlex 统计显示该学者在 {inst_name} 关联档案下共有 "
            f"{cs.get('total_papers', 0)} 篇论文、{cs.get('total_citations', 0)} 次引用，"
            f"h-index 为 {cs.get('h_index', 0)}。"
        ),
    }]
    next_id = 2
    topics = [t["topic"] for t in state["topic_clusters"][:5]]
    if topics:
        evidence.append({
            "id": str(next_id),
            "type": "topic",
            "text": "核心研究方向来自论文标题与 OpenAlex concepts 聚合: " + "、".join(topics) + "。",
        })
        next_id += 1
    for paper in _flatten_representative_papers(state["representative_papers"])[:3]:
        evidence.append({
            "id": str(next_id),
            "type": "paper",
            "text": (
                f"代表论文《{paper.get('title', '')}》"
                f"({paper.get('year', '未知年份')})，引用 {paper.get('citations', 0)} 次。"
            ),
            "url": paper.get("id") or paper.get("doi") or "",
        })
        next_id += 1
    if state["coauthors"]:
        names = [f"{c['name']}({c['papers']} 篇)" for c in state["coauthors"][:3]]
        evidence.append({
            "id": str(next_id),
            "type": "coauthor",
            "text": "高频合作者包括 " + "、".join(names) + "。",
        })
    return evidence


def _summary_has_valid_evidence(summary: str, evidence: list[dict]) -> bool:
    valid_ids = {item["id"] for item in evidence}
    cited_ids = set(re.findall(r"\[(\d+)\]", summary or ""))
    return bool(summary and len(summary.strip()) >= 20 and cited_ids & valid_ids)


def _fallback_summary(profile: dict, inst_name: str, state: ScholarProfileState, evidence: list[dict]) -> str:
    cs = state["citation_summary"]
    topic_names = [t["topic"] for t in state["topic_clusters"][:5]]
    topic_text = "、".join(topic_names) if topic_names else "暂未形成稳定方向标签"
    metric_ref = "[1]" if evidence else ""
    topic_ref = "[2]" if len(evidence) >= 2 and evidence[1]["type"] == "topic" else metric_ref
    paper_refs = [f"[{item['id']}]" for item in evidence if item["type"] == "paper"]
    paper_text = "，代表性论文可见" + "".join(paper_refs[:2]) if paper_refs else ""
    coauthor_refs = [f"[{item['id']}]" for item in evidence if item["type"] == "coauthor"]
    coauthor_text = " 合作网络依据可见" + coauthor_refs[0] + "。" if coauthor_refs else ""
    return (
        f"{profile.get('display_name', '')} 是 {inst_name} 的研究人员，"
        f"OpenAlex 记录显示其发表 {cs.get('total_papers', 0)} 篇论文、"
        f"累计引用 {cs.get('total_citations', 0):,} 次，h-index 为 {cs.get('h_index', 0)}{metric_ref}。"
        f"其研究方向主要集中在 {topic_text}{topic_ref}{paper_text}。"
        f"{coauthor_text}"
    )


def generate_profile_report(state: ScholarProfileState) -> dict:
    """使用 LLM Agent 生成学者的学术总结（回退模板）。"""
    profile = state["target_author_profile"] or {}
    insts = [i.get("display_name", "") for i in (profile.get("last_known_institutions") or [])]
    inst_name = insts[0] if insts else "未知机构"
    cs = state["citation_summary"]
    topic_names = [t["topic"] for t in state["topic_clusters"][:5]]
    top_coauthors = [{"name": c["name"], "papers": c["papers"]} for c in state["coauthors"][:5]]
    evidence = _build_profile_evidence(state, inst_name)

    # 尝试用 LLM 生成
    from llm import report_llm

    try:
        representative = _flatten_representative_papers(state["representative_papers"])[:5]
        report_input = {
            "name": profile.get("display_name", ""),
            "institution": inst_name,
            "totalPapers": cs.get("total_papers", 0),
            "totalCitations": cs.get("total_citations", 0),
            "hIndex": cs.get("h_index", 0),
            "topics": topic_names,
            "top_coauthors": top_coauthors,
            "representative_papers": [p.get("title", "") for p in representative],
            "evidence": evidence,
            "trend": "活跃年份: " + ", ".join(str(t.get("year", "")) for t in cs.get("yearly_trend", [])[:5]),
        }
        summary = report_llm(report_input)
        if _summary_has_valid_evidence(summary, evidence):
            return {
                "profile_summary": summary,
                "profile_evidence": evidence,
                "warnings": ["Agent 生成总结 ✓"],
            }
    except Exception as e:
        pass  # fallback to template

    summary = _fallback_summary(profile, inst_name, state, evidence)
    return {"profile_summary": summary, "profile_evidence": evidence}


def format_web_payload(state: ScholarProfileState) -> dict:
    """组装前端渲染所需的 JSON 数据。"""
    profile = state["target_author_profile"] or {}
    insts = [i.get("display_name", "") for i in (profile.get("last_known_institutions") or [])]
    cs = state["citation_summary"]
    ws = state["deduped_works"]

    # top 50 高被引论文，避免大作者 payload 过大
    top_cited = sorted(ws, key=lambda w: -(w.get("cited_by_count") or 0))
    top_cited_list = [{
        "id": w.get("id", ""),
        "title": w.get("title", ""),
        "year": w.get("publication_year"),
        "citations": w.get("cited_by_count", 0),
        "journal": ((w.get("primary_location") or {}).get("source") or {}).get("display_name", ""),
    } for w in top_cited[:50]]

    # 平铺所有 representative papers 并去重
    all_repr = []
    for papers in state["representative_papers"].values():
        all_repr.extend(papers)
    seen = set()
    unique_repr = []
    for p in all_repr:
        key = p.get("doi") or p.get("id") or p["title"]
        if key not in seen:
            seen.add(key)
            unique_repr.append(p)

    payload = {
        "name": profile.get("display_name", ""),
        "authorId": state["target_author_id"],
        "institution": insts[0] if insts else "",
        "department": "",
        "totalPapers": cs.get("total_papers", 0),
        "totalCitations": cs.get("total_citations", 0),
        "hIndex": cs.get("h_index", 0),
        "topics": [t["topic"] for t in state["topic_clusters"][:8]],
        "yearlyTrend": cs.get("yearly_trend", []),
        "topicDistribution": [{"name": t["topic"], "value": t["weight"]}
                              for t in state["topic_clusters"]],
        "interestTimeline": state["interest_timeline"],
        "representativePapers": unique_repr,
        "topCitedPapers": top_cited_list,
        "coauthors": [{"name": c["name"], "institution": c.get("institution", ""), "papers": c["papers"]}
                      for c in state["coauthors"][:15]],
        "graphNodes": state["graph_nodes"],
        "graphEdges": state["graph_edges"],
        "profileSummary": state["profile_summary"],
        "profileEvidence": state["profile_evidence"],
    }
    return {"web_payload": payload}
