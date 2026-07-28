"""Deterministic scholar and team intelligence over the stage-2 graph.

No score in this module is produced by an LLM.  Scores are transparent,
request-time indices over the locally covered dynamic research graph and are
never described as absolute quality or causal effects.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from math import log1p, sqrt
from statistics import median
import re
from typing import Any

from field_discovery import (
    build_field_institutions,
    compare_field_institutions,
    get_field_discovery_state,
)
from intelligence_repository import load_intelligence_dataset


ANALYSIS_VERSION = "deterministic-graph-v1"
INSUFFICIENT_ZH = "无法可靠判断"
INSUFFICIENT_EN = "Insufficient data for a reliable assessment"

METHOD_KEYWORDS = {
    "method": {
        "algorithm", "method", "model", "framework", "optimization",
        "learning", "inference", "estimation", "theory", "theoretical",
        "算法", "方法", "模型", "框架", "优化", "学习", "推理", "估计", "理论",
    },
    "system": {
        "system", "platform", "architecture", "pipeline", "engine",
        "deployment", "prototype", "tool", "系统", "平台", "架构", "流程",
        "引擎", "部署", "原型", "工具",
    },
    "data": {
        "dataset", "benchmark", "corpus", "database", "knowledge graph",
        "data", "annotation", "survey", "数据集", "基准", "语料", "数据库",
        "知识图谱", "数据", "标注", "调查",
    },
    "application": {
        "application", "clinical", "medical", "industrial", "education",
        "recommendation", "diagnosis", "robot", "traffic", "应用", "临床",
        "医学", "工业", "教育", "推荐", "诊断", "机器人", "交通",
    },
}


def _i18n(zh: str, en: str) -> dict:
    return {"zh": zh, "en": en}


def _round(value: float, digits: int = 1) -> float:
    return round(max(0.0, min(100.0, value)), digits)


def _safe_ratio(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator else 0.0


def _percentile(value: float, values: list[float]) -> float:
    if not values:
        return 0.0
    below = sum(item < value for item in values)
    equal = sum(item == value for item in values)
    return (below + 0.5 * equal) / len(values)


def _normalized_topic(value: str) -> str:
    return " ".join((value or "").casefold().split())


def _topic_names(work: dict) -> list[str]:
    return [
        topic["name"]
        for topic in work.get("topics") or []
        if topic.get("name")
    ]


def _tokens(value: str | None) -> set[str]:
    text = (value or "").casefold()
    latin = set(re.findall(r"[a-z0-9][a-z0-9_-]{2,}", text))
    cjk_sequences = re.findall(r"[\u3400-\u9fff]+", text)
    cjk = {
        sequence[index:index + 2]
        for sequence in cjk_sequences
        for index in range(max(0, len(sequence) - 1))
    }
    return latin | cjk


def _jaccard(left: set[str], right: set[str]) -> float:
    return _safe_ratio(len(left & right), len(left | right))


def _weighted_jaccard(left: Counter, right: Counter) -> float:
    keys = set(left) | set(right)
    if not keys:
        return 0.0
    intersection = sum(min(left[key], right[key]) for key in keys)
    union = sum(max(left[key], right[key]) for key in keys)
    return _safe_ratio(intersection, union)


def _primary_affiliation(scholar: dict) -> dict | None:
    affiliations = scholar.get("affiliations") or []
    return affiliations[0] if affiliations else None


def _contribution_score(authorship: dict | None) -> float:
    if not authorship:
        return 0.0
    author_count = int(authorship.get("author_count") or 0)
    if author_count <= 1:
        return 1.0
    if authorship.get("is_corresponding"):
        return 1.0
    position = (authorship.get("author_position") or "").casefold()
    if position == "first":
        return 0.95
    if position == "last":
        return 0.9
    position_index = authorship.get("position_index")
    if position_index == 0:
        return 0.95
    if isinstance(position_index, int) and position_index == author_count - 1:
        return 0.9
    return 0.45


def _h_index(citations: list[int]) -> int:
    result = 0
    for index, value in enumerate(sorted(citations, reverse=True), start=1):
        if value < index:
            break
        result = index
    return result


def _build_context(dataset: dict) -> dict:
    works = dataset["works"]
    as_of_year = dataset.get("as_of_year")
    raw_impact = {}
    topic_pools: dict[str, list[float]] = defaultdict(list)
    all_impacts = []
    for work_id, work in works.items():
        year = work.get("year")
        age = max(1, (as_of_year - year + 1)) if as_of_year and year else 3
        impact = log1p(max(0, int(work.get("citations") or 0))) / sqrt(age)
        raw_impact[work_id] = impact
        all_impacts.append(impact)
        for name in _topic_names(work):
            topic_pools[_normalized_topic(name)].append(impact)

    impact_percentile = {}
    for work_id, work in works.items():
        pools = [
            topic_pools[_normalized_topic(name)]
            for name in _topic_names(work)
            if len(topic_pools[_normalized_topic(name)]) >= 3
        ]
        if not pools:
            pools = [all_impacts]
        impact_percentile[work_id] = (
            sum(_percentile(raw_impact[work_id], pool) for pool in pools)
            / max(1, len(pools))
        )

    incoming = Counter()
    for edge in dataset.get("citations") or []:
        incoming[edge["cited_work_id"]] += 1

    topic_profiles = {}
    recent_topic_profiles = {}
    method_tokens = {}
    problem_tokens = {}
    category_profiles = {}
    for author_id, scholar in dataset["scholars"].items():
        topics = Counter()
        recent_topics = Counter()
        categories = Counter()
        methods: set[str] = set()
        problems: set[str] = set()
        recent_start = (as_of_year - 3) if as_of_year else None
        for work_id in scholar["work_ids"]:
            work = works.get(work_id)
            if not work:
                continue
            for name in _topic_names(work):
                topics[_normalized_topic(name)] += 1
                if recent_start is None or (work.get("year") or 0) >= recent_start:
                    recent_topics[_normalized_topic(name)] += 1
            text = " ".join(filter(None, [
                work.get("title"),
                (work.get("insight") or {}).get("problem"),
                (work.get("insight") or {}).get("core_method"),
                work.get("work_type"),
            ])).casefold()
            if recent_start is None or (work.get("year") or 0) >= recent_start:
                methods |= _tokens((work.get("insight") or {}).get("core_method"))
                problems |= _tokens((work.get("insight") or {}).get("problem"))
            for category, keywords in METHOD_KEYWORDS.items():
                if any(keyword in text for keyword in keywords):
                    categories[category] += 1
        topic_profiles[author_id] = topics
        recent_topic_profiles[author_id] = recent_topics
        method_tokens[author_id] = methods
        problem_tokens[author_id] = problems
        category_profiles[author_id] = categories
    return {
        "raw_impact": raw_impact,
        "impact_percentile": impact_percentile,
        "incoming": incoming,
        "topic_profiles": topic_profiles,
        "recent_topic_profiles": recent_topic_profiles,
        "method_tokens": method_tokens,
        "problem_tokens": problem_tokens,
        "category_profiles": category_profiles,
    }


def _data_confidence(dataset: dict, scholar: dict) -> dict:
    works = [
        dataset["works"][work_id]
        for work_id in scholar["work_ids"]
        if work_id in dataset["works"]
    ]
    years = sorted({work["year"] for work in works if work.get("year")})
    topic_covered = sum(bool(_topic_names(work)) for work in works)
    abstract_covered = sum(
        bool((work.get("insight") or {}).get("based_on_abstract"))
        for work in works
    )
    work_count = len(works)
    span = (years[-1] - years[0] + 1) if years else 0
    coverage_score = (
        min(1.0, work_count / 12) * 0.35
        + min(1.0, span / 6) * 0.2
        + _safe_ratio(topic_covered, work_count) * 0.25
        + _safe_ratio(abstract_covered, work_count) * 0.15
        + (0.05 if scholar.get("graph_ready") else 0)
    )
    if not scholar.get("graph_ready") or work_count < 3 or topic_covered < 2:
        level = "insufficient"
    elif coverage_score >= 0.8:
        level = "high"
    elif coverage_score >= 0.58:
        level = "medium"
    else:
        level = "low"
    labels = {
        "high": _i18n("高", "High"),
        "medium": _i18n("中等", "Medium"),
        "low": _i18n("低", "Low"),
        "insufficient": _i18n("无法可靠判断", "Insufficient"),
    }
    return {
        "level": level,
        "score": round(coverage_score, 3),
        "label": labels[level],
        "coverage": {
            "works": work_count,
            "year_span": span,
            "topic_coverage": round(_safe_ratio(topic_covered, work_count), 3),
            "abstract_coverage": round(_safe_ratio(abstract_covered, work_count), 3),
            "graph_ready": bool(scholar.get("graph_ready")),
        },
    }


def _evidence(
    code: str,
    zh: str,
    en: str,
    value: Any,
    *,
    paper_ids: list[str] | None = None,
) -> dict:
    return {
        "code": code,
        "label": _i18n(zh, en),
        "value": value,
        "paper_ids": list(paper_ids or []),
    }


def _insufficient_dimension(key: str, confidence: dict, limitations: list[dict]) -> dict:
    return {
        "key": key,
        "status": "insufficient",
        "index": None,
        "confidence": confidence,
        "conclusion": _i18n(INSUFFICIENT_ZH, INSUFFICIENT_EN),
        "evidence": [],
        "limitations": limitations,
    }


def _topic_statistics(dataset: dict, scholar: dict) -> tuple[Counter, dict[str, set[int]]]:
    counts = Counter()
    years: dict[str, set[int]] = defaultdict(set)
    for work_id in scholar["work_ids"]:
        work = dataset["works"].get(work_id)
        if not work:
            continue
        for name in _topic_names(work):
            key = _normalized_topic(name)
            counts[key] += 1
            if work.get("year"):
                years[key].add(work["year"])
    return counts, years


def _representative_works(
    dataset: dict,
    context: dict,
    scholar: dict,
    field_topics: set[str],
    *,
    limit: int = 5,
) -> list[dict]:
    rows = []
    own_work_ids = set(scholar["work_ids"])
    later_same_topic = Counter()
    ordered = sorted(
        (
            dataset["works"][work_id]
            for work_id in scholar["work_ids"]
            if work_id in dataset["works"]
        ),
        key=lambda work: (work.get("year") or 0, work["id"]),
    )
    for index, work in enumerate(ordered):
        topics = {_normalized_topic(name) for name in _topic_names(work)}
        later_same_topic[work["id"]] = sum(
            bool(topics & {
                _normalized_topic(name)
                for name in _topic_names(later)
            })
            for later in ordered[index + 1:]
        )
    for work_id in own_work_ids:
        work = dataset["works"].get(work_id)
        if not work:
            continue
        topics = {_normalized_topic(name) for name in _topic_names(work)}
        relevance = _safe_ratio(len(topics & field_topics), len(topics | field_topics))
        impact = context["impact_percentile"].get(work_id, 0)
        contribution = _contribution_score(scholar["authorships"].get(work_id))
        downstream = min(1.0, context["incoming"].get(work_id, 0) / 3)
        continuation = min(1.0, later_same_topic[work_id] / 3)
        work_confidence_score = (
            (0.3 if topics else 0)
            + (0.25 if (work.get("insight") or {}).get("based_on_abstract") else 0)
            + (0.25 if scholar["authorships"].get(work_id) else 0)
            + (0.1 if work.get("year") else 0)
            + (0.1 if work.get("source_id") else 0)
        )
        work_confidence_level = (
            "high" if work_confidence_score >= 0.85
            else "medium" if work_confidence_score >= 0.65
            else "low"
        )
        score = (
            relevance * 0.28
            + impact * 0.30
            + contribution * 0.18
            + downstream * 0.14
            + continuation * 0.10
        )
        rows.append({
            "id": work["id"],
            "source_id": work["source_id"],
            "title": work["title"],
            "year": work.get("year"),
            "citations": work.get("citations", 0),
            "venue": work.get("venue"),
            "topics": _topic_names(work),
            "index": _round(score * 100),
            "confidence": {
                "level": work_confidence_level,
                "score": round(work_confidence_score, 3),
                "label": {
                    "high": _i18n("高", "High"),
                    "medium": _i18n("中等", "Medium"),
                    "low": _i18n("低", "Low"),
                }[work_confidence_level],
            },
            "components": {
                "field_relevance": round(relevance, 3),
                "field_time_normalized_impact": round(impact, 3),
                "contribution_role": round(contribution, 3),
                "internal_follow_on": round(downstream, 3),
                "topic_continuation": round(continuation, 3),
            },
            "evidence": [
                _evidence(
                    "citations",
                    "OpenAlex 当前引用数（不单独代表质量）",
                    "Current OpenAlex citations (not a standalone quality measure)",
                    int(work.get("citations") or 0),
                ),
                _evidence(
                    "internal_follow_on",
                    "本地图谱内后续论文引用",
                    "Later citations inside the local graph",
                    int(context["incoming"].get(work_id, 0)),
                ),
                _evidence(
                    "contribution_role",
                    "署名贡献角色系数",
                    "Authorship contribution-role factor",
                    round(contribution, 2),
                ),
            ],
        })
    return sorted(
        rows,
        key=lambda row: (
            -row["index"],
            -(row.get("year") or 0),
            row["source_id"],
        ),
    )[:limit]


def _style_dimension(
    dataset: dict,
    context: dict,
    scholar: dict,
    confidence: dict,
    continuity_index: float,
    representative_ids: list[str],
) -> dict:
    works = [
        dataset["works"][work_id]
        for work_id in scholar["work_ids"]
        if work_id in dataset["works"]
    ]
    evidence_works = [
        work for work in works
        if (work.get("insight") or {}).get("based_on_abstract")
        or work.get("title")
    ]
    if confidence["level"] == "insufficient" or len(evidence_works) < 3:
        return _insufficient_dimension(
            "topic_style",
            confidence,
            [_i18n(
                "至少需要 3 篇带标题或摘要证据的图谱论文。",
                "At least three graph papers with title or abstract evidence are required.",
            )],
        )
    categories: Counter = context["category_profiles"][scholar["author_id"]]
    method_side = categories["method"] + categories["data"]
    applied_side = categories["system"] + categories["application"]
    if applied_side >= method_side * 1.35 and applied_side >= 2:
        orientation = _i18n("偏应用、系统或数据落地", "Application, systems, or deployment leaning")
    elif method_side >= applied_side * 1.35 and method_side >= 2:
        orientation = _i18n("偏方法、模型或基础问题", "Methods, models, or foundational-problem leaning")
    else:
        orientation = _i18n("基础方法与应用问题并行", "Mixed foundational-method and application agenda")

    counts, topic_years = _topic_statistics(dataset, scholar)
    sustained_topics = sum(
        counts[topic] >= 3 and len(years) >= 3
        for topic, years in topic_years.items()
    )
    if continuity_index >= 68 and sustained_topics:
        pacing = _i18n("以长期连续方向为主", "Primarily sustained, long-running directions")
    elif continuity_index < 45:
        pacing = _i18n("近期方向组合变化较明显", "Recent topic mix shows material change")
    else:
        pacing = _i18n("延续方向与新方向并存", "Sustained and newer directions coexist")

    dominant = categories.most_common(1)
    category_labels = {
        "method": _i18n("方法/模型", "Methods/models"),
        "system": _i18n("系统/平台", "Systems/platforms"),
        "data": _i18n("数据/基准", "Data/benchmarks"),
        "application": _i18n("应用问题", "Applied problems"),
    }
    focus = (
        category_labels[dominant[0][0]]
        if dominant and dominant[0][1] >= 2
        else _i18n("证据未形成单一主导类型", "No single dominant type in the evidence")
    )
    author_counts = [int(work.get("author_count") or 0) for work in works]
    repeated = sum(
        relation.get("works_count", 0) >= 2
        for relation in scholar.get("collaborations", {}).values()
    )
    typical_team = median(author_counts) if author_counts else 0
    if repeated >= 3:
        collaboration = _i18n("存在多组重复合作关系", "Several repeated collaboration relationships")
    elif repeated >= 1:
        collaboration = _i18n("存在稳定合作核心，同时保留开放合作", "A stable collaboration core with additional open collaboration")
    else:
        collaboration = _i18n("当前图谱未显示足够重复合作", "The current graph shows limited repeated collaboration")
    recent_evidence_ids = [
        work["id"]
        for work in sorted(
            evidence_works,
            key=lambda item: (
                -(item.get("year") or 0),
                -int(item.get("citations") or 0),
                item["id"],
            ),
        )[:5]
    ]
    evidence_work_ids = {work["id"] for work in evidence_works}
    paper_ids = [
        work_id
        for work_id in representative_ids
        if work_id in evidence_work_ids
    ] or recent_evidence_ids
    return {
        "key": "topic_style",
        "status": "available",
        "index": None,
        "confidence": confidence,
        "conclusion": _i18n(
            f"选题证据显示：{orientation['zh']}；{pacing['zh']}。",
            f"Topic evidence suggests: {orientation['en']}; {pacing['en'].lower()}.",
        ),
        "axes": [
            {"key": "orientation", "label": _i18n("问题取向", "Problem orientation"), "value": orientation},
            {"key": "pacing", "label": _i18n("方向节奏", "Direction cadence"), "value": pacing},
            {"key": "work_type", "label": _i18n("成果侧重", "Work emphasis"), "value": focus},
            {"key": "collaboration", "label": _i18n("合作模式", "Collaboration pattern"), "value": collaboration},
        ],
        "evidence": [
            _evidence(
                "classified_works",
                "参与类型判断的论文",
                "Papers used for type classification",
                len(evidence_works),
                paper_ids=paper_ids,
            ),
            _evidence(
                "category_counts",
                "方法/系统/数据/应用命中数",
                "Method/system/data/application signal counts",
                dict(categories),
                paper_ids=paper_ids,
            ),
            _evidence(
                "typical_team_size",
                "典型论文作者数（中位数）",
                "Typical authors per paper (median)",
                round(float(typical_team), 1),
            ),
            _evidence(
                "repeated_collaborators",
                "至少共同发表 2 篇的合作者",
                "Collaborators with at least two shared papers",
                repeated,
            ),
        ],
        "limitations": [_i18n(
            "类型判断来自标题、摘要抽取字段与论文类型关键词，不是人格评价。",
            "Type labels use titles, extracted abstract fields, and work-type keywords; they are not personality assessments.",
        )],
    }


def _scholar_analysis(
    dataset: dict,
    context: dict,
    author_id: str,
    field_topics: set[str],
) -> dict:
    scholar = dataset["scholars"][author_id]
    confidence = _data_confidence(dataset, scholar)
    global_limitations = [
        _i18n(
            "分析仅覆盖当前动态研究图谱已收录的论文与关系。",
            "The analysis covers only papers and relations currently present in the dynamic research graph.",
        ),
        _i18n(
            "引用数已按时间和本地同领域样本归一化，但仍受学科与数据库覆盖影响。",
            "Citations are time- and local-field-normalized, but discipline and database coverage still matter.",
        ),
    ]
    if confidence["level"] == "insufficient":
        dimensions = {
            key: _insufficient_dimension(key, confidence, global_limitations)
            for key in ("academic_quality", "continuity", "impact")
        }
        dimensions["topic_style"] = _insufficient_dimension(
            "topic_style", confidence, global_limitations
        )
        return {
            "subject": _public_scholar(scholar),
            "confidence": confidence,
            "dimensions": dimensions,
            "representative_works": [],
            "limitations": global_limitations,
        }

    works = [
        dataset["works"][work_id]
        for work_id in scholar["work_ids"]
        if work_id in dataset["works"]
    ]
    counts, topic_years = _topic_statistics(dataset, scholar)
    years = sorted({work["year"] for work in works if work.get("year")})
    sustained = {
        topic for topic, topic_count in counts.items()
        if topic_count >= 3 and len(topic_years[topic]) >= 3
    }
    sustained_work_ids = {
        work["id"]
        for work in works
        if {_normalized_topic(name) for name in _topic_names(work)} & sustained
    }
    longest_span = max(
        (
            max(topic_years[topic]) - min(topic_years[topic]) + 1
            for topic in sustained
        ),
        default=0,
    )
    topic_repeat = _safe_ratio(
        sum(count for topic, count in counts.items() if count >= 2),
        sum(counts.values()),
    )
    sustained_share = _safe_ratio(len(sustained_work_ids), len(works))
    recent_start = (dataset["as_of_year"] - 3) if dataset.get("as_of_year") else 0
    earlier_topics = Counter()
    recent_topics = Counter()
    for work in works:
        target = recent_topics if (work.get("year") or 0) >= recent_start else earlier_topics
        for name in _topic_names(work):
            target[_normalized_topic(name)] += 1
    direction_stability = _weighted_jaccard(earlier_topics, recent_topics)
    continuity_index = _round(100 * (
        sustained_share * 0.45
        + min(1.0, longest_span / 8) * 0.25
        + topic_repeat * 0.20
        + direction_stability * 0.10
    ))

    impact_values = [context["impact_percentile"].get(work["id"], 0) for work in works]
    citations = [int(work.get("citations") or 0) for work in works]
    cited_share = _safe_ratio(sum(value > 0 for value in citations), len(citations))
    internally_followed = sum(context["incoming"].get(work["id"], 0) > 0 for work in works)
    internal_spread = _safe_ratio(internally_followed, len(works))
    upper_impact = (
        sum(sorted(impact_values, reverse=True)[:max(1, min(5, len(impact_values)))])
        / max(1, min(5, len(impact_values)))
    )
    impact_index = _round(100 * (
        upper_impact * 0.5
        + internal_spread * 0.3
        + cited_share * 0.2
    ))

    role_scores = [
        _contribution_score(scholar["authorships"].get(work["id"]))
        for work in works
    ]
    strong_role_share = _safe_ratio(sum(score >= 0.9 for score in role_scores), len(role_scores))
    representatives = _representative_works(
        dataset, context, scholar, field_topics, limit=5
    )
    representative_signal = _safe_ratio(
        sum(item["index"] for item in representatives[:3]),
        max(1, min(3, len(representatives))) * 100,
    )
    quality_index = _round(100 * (
        representative_signal * 0.4
        + strong_role_share * 0.25
        + upper_impact * 0.2
        + internal_spread * 0.15
    ))

    def band(index: float, strong: str, moderate: str, limited: str) -> str:
        return strong if index >= 70 else moderate if index >= 48 else limited

    quality_zh = band(
        quality_index,
        "当前本地同领域证据显示较强的代表作、贡献角色与后续扩散组合信号",
        "当前本地同领域证据显示中等的代表作、贡献角色与后续扩散组合信号",
        "当前图谱中的质量相关证据较有限，不能由高引用或论文数量替代",
    )
    quality_en = band(
        quality_index,
        "The local field evidence shows a relatively strong combination of representative-work, contribution-role, and follow-on diffusion signals",
        "The local field evidence shows a moderate combination of representative-work, contribution-role, and follow-on diffusion signals",
        "Quality-related evidence in the current graph is limited and cannot be replaced by citation or paper counts",
    )
    continuity_zh = band(
        continuity_index,
        "多年份主题形成连续工作主线",
        "部分方向具有跨年份延续，同时存在方向调整",
        "现有主题尚未形成充分的跨年份连续证据",
    )
    continuity_en = band(
        continuity_index,
        "Multi-year topics form sustained lines of work",
        "Some directions persist across years while the topic mix also changes",
        "Current topics do not yet provide sufficient evidence of sustained multi-year lines",
    )
    concentration = max(citations, default=0) / max(1, sum(citations))
    if impact_index >= 70 and concentration < 0.65:
        impact_zh = "影响信号分布在多篇成果，并有本地图谱内后续扩散"
        impact_en = "Impact signals are distributed across multiple works with follow-on diffusion inside the local graph"
    elif concentration >= 0.65:
        impact_zh = "当前影响信号集中于少数论文，不能据此推断整体影响力"
        impact_en = "Current impact signals are concentrated in a few papers and do not establish broad influence"
    else:
        impact_zh = "当前影响信号一般，需结合领域覆盖与后续扩散继续观察"
        impact_en = "Current impact signals are moderate and should be read with field coverage and later diffusion"

    representative_ids = [item["id"] for item in representatives[:3]]
    dimensions = {
        "academic_quality": {
            "key": "academic_quality",
            "status": "available",
            "index": quality_index,
            "confidence": confidence,
            "conclusion": _i18n(quality_zh, quality_en),
            "evidence": [
                _evidence(
                    "representative_signal",
                    "代表作综合信号",
                    "Representative-work composite signal",
                    round(representative_signal, 3),
                    paper_ids=representative_ids,
                ),
                _evidence(
                    "strong_contribution_share",
                    "第一/末位/通讯等强贡献角色占比",
                    "Share of first/last/corresponding contribution roles",
                    round(strong_role_share, 3),
                    paper_ids=representative_ids,
                ),
                _evidence(
                    "field_normalized_impact",
                    "同主题与时间归一化影响分位",
                    "Topic- and time-normalized impact percentile",
                    round(upper_impact, 3),
                    paper_ids=representative_ids,
                ),
                _evidence(
                    "internal_diffusion",
                    "有本地图谱后续引用的成果占比",
                    "Share of works with follow-on citations in the local graph",
                    round(internal_spread, 3),
                ),
            ],
            "limitations": global_limitations,
        },
        "continuity": {
            "key": "continuity",
            "status": "available",
            "index": continuity_index,
            "confidence": confidence,
            "conclusion": _i18n(continuity_zh, continuity_en),
            "evidence": [
                _evidence(
                    "sustained_topics",
                    "至少跨 3 年且关联至少 3 篇论文的方向",
                    "Directions spanning at least three years and three papers",
                    len(sustained),
                ),
                _evidence(
                    "longest_span",
                    "最长连续方向覆盖年数",
                    "Longest sustained-direction year span",
                    longest_span,
                ),
                _evidence(
                    "sustained_share",
                    "纳入连续方向的论文占比",
                    "Share of papers in sustained directions",
                    round(sustained_share, 3),
                ),
                _evidence(
                    "recent_stability",
                    "早期与近期主题组合重合度",
                    "Overlap between earlier and recent topic mixes",
                    round(direction_stability, 3),
                ),
            ],
            "limitations": [_i18n(
                "单篇或单年份方向不计入长期连续方向。",
                "One-off or single-year topics are not counted as sustained directions.",
            )],
        },
        "impact": {
            "key": "impact",
            "status": "available",
            "index": impact_index,
            "confidence": confidence,
            "conclusion": _i18n(impact_zh, impact_en),
            "evidence": [
                _evidence(
                    "field_normalized_impact",
                    "代表成果的同主题时间归一化影响分位",
                    "Field- and time-normalized impact percentile of leading works",
                    round(upper_impact, 3),
                    paper_ids=representative_ids,
                ),
                _evidence(
                    "cited_work_share",
                    "至少有一次引用的论文占比",
                    "Share of works with at least one citation",
                    round(cited_share, 3),
                ),
                _evidence(
                    "internal_diffusion",
                    "本地图谱后续扩散覆盖",
                    "Follow-on diffusion coverage inside the local graph",
                    round(internal_spread, 3),
                ),
                _evidence(
                    "local_h_index",
                    "当前图谱论文集 h-index（仅辅助）",
                    "h-index over current graph papers (supporting only)",
                    _h_index(citations),
                ),
            ],
            "limitations": [_i18n(
                "论文数量未进入影响力指数；引用只作为归一化后的多个证据之一。",
                "Paper count is excluded from the impact index; citations are only one normalized evidence source.",
            )],
        },
    }
    dimensions["topic_style"] = _style_dimension(
        dataset,
        context,
        scholar,
        confidence,
        continuity_index,
        [item["id"] for item in representatives],
    )
    return {
        "subject": _public_scholar(scholar),
        "confidence": confidence,
        "dimensions": dimensions,
        "representative_works": representatives,
        "limitations": global_limitations,
    }


def _public_scholar(scholar: dict) -> dict:
    affiliation = _primary_affiliation(scholar)
    return {
        "author_id": scholar["author_id"],
        "scholar_id": scholar["id"],
        "name": scholar["name"],
        "orcid": scholar.get("orcid"),
        "institution": affiliation.get("name") if affiliation else None,
        "graph_ready": bool(scholar.get("graph_ready")),
        "graph_version": int(scholar.get("graph_version") or 0),
    }


def _field_topics(dataset: dict, context: dict, focus_author_id: str) -> list[dict]:
    profile: Counter = context["topic_profiles"].get(focus_author_id, Counter())
    scholar = dataset["scholars"].get(focus_author_id) or {}
    _, years = _topic_statistics(dataset, scholar)
    display = {}
    for work_id in scholar.get("work_ids") or []:
        for name in _topic_names(dataset["works"].get(work_id) or {}):
            display.setdefault(_normalized_topic(name), name)
    rows = []
    for topic, count in profile.items():
        rows.append({
            "name": display.get(topic, topic),
            "normalized_name": topic,
            "works_count": count,
            "active_years": len(years.get(topic, set())),
        })
    ranked = sorted(
        rows,
        key=lambda row: (
            -int(row["active_years"] >= 2),
            -row["works_count"],
            row["normalized_name"],
        ),
    )
    sustained = [
        row
        for row in ranked
        if row["works_count"] >= 2 or row["active_years"] >= 2
    ]
    return (sustained or ranked)[:8]


def _temporal_overlap(dataset: dict, left: dict, right: dict) -> float:
    left_years = {
        dataset["works"][work_id]["year"]
        for work_id in left["work_ids"]
        if work_id in dataset["works"] and dataset["works"][work_id].get("year")
    }
    right_years = {
        dataset["works"][work_id]["year"]
        for work_id in right["work_ids"]
        if work_id in dataset["works"] and dataset["works"][work_id].get("year")
    }
    return _jaccard({str(year) for year in left_years}, {str(year) for year in right_years})


def _recommendation(
    category: str,
    scholar: dict,
    score: float,
    confidence: dict,
    explanation: dict,
    evidence: list[dict],
    limitations: list[dict],
) -> dict:
    return {
        "category": category,
        **_public_scholar(scholar),
        "index": _round(score * 100),
        "confidence": confidence,
        "explanation": explanation,
        "evidence": evidence,
        "limitations": limitations,
    }


def _recommendation_topic_text(row: dict, lang: str) -> str:
    topics = row.get("shared_topics") or []
    if not topics:
        return "相近研究方向" if lang == "zh" else "related research topics"
    if lang == "zh":
        return "、".join(topics)
    if len(topics) == 1:
        return topics[0]
    return " and ".join(topics)


def _recommendation_identity(row: dict, lang: str) -> str:
    name = row["scholar"].get("name") or row["author_id"]
    institution = (_primary_affiliation(row["scholar"]) or {}).get("name")
    if not institution:
        return name
    return (
        f"{name}（{institution}）"
        if lang == "zh"
        else f"{name} at {institution}"
    )


def _recommendation_focus_name(row: dict, lang: str) -> str:
    return (
        row.get("focus_name")
        or ("当前学者" if lang == "zh" else "the current scholar")
    )


def _recommendation_representative(row: dict, lang: str) -> str:
    representatives = (row.get("analysis") or {}).get("representative_works") or []
    if not representatives:
        return ""
    work = representatives[0]
    title = re.sub(r"\s+", " ", str(work.get("title") or "")).strip()
    if not title:
        return ""
    if len(title) > 88:
        title = f"{title[:85].rstrip()}…"
    year = work.get("year")
    if lang == "zh":
        year_text = f"（{year}）" if year else ""
        return f"当前图谱选出的代表成果之一是《{title}》{year_text}"
    year_text = f" ({year})" if year else ""
    return f'One representative result in the current graph is “{title}”{year_text}'


def _recommendation_dimension_evidence(
    row: dict,
    dimension: str,
    code: str,
) -> Any:
    evidence = (
        ((row.get("analysis") or {}).get("dimensions") or {})
        .get(dimension, {})
        .get("evidence", [])
    )
    return next(
        (item.get("value") for item in evidence if item.get("code") == code),
        None,
    )


def _reference_explanation(
    row: dict,
    continuity: float | None,
    impact: float | None,
    downstream: float,
    recent_works: int,
) -> dict:
    identity_zh = _recommendation_identity(row, "zh")
    identity_en = _recommendation_identity(row, "en")
    focus_zh = _recommendation_focus_name(row, "zh")
    focus_en = _recommendation_focus_name(row, "en")
    topics_zh = _recommendation_topic_text(row, "zh")
    topics_en = _recommendation_topic_text(row, "en")
    representative_zh = _recommendation_representative(row, "zh")
    representative_en = _recommendation_representative(row, "en")
    signals = {
        "continuity": (continuity or 0) / 100,
        "impact": (impact or 0) / 100,
        "downstream": downstream,
        "topic_overlap": row["topic_overlap"],
        "recent_overlap": row["recent_overlap"],
    }
    dominant = row.get("reference_angle") or max(
        signals,
        key=lambda key: (signals[key], key),
    )
    if dominant == "continuity" and continuity is not None:
        sustained_topics = _recommendation_dimension_evidence(
            row, "continuity", "sustained_topics"
        )
        longest_span = _recommendation_dimension_evidence(
            row, "continuity", "longest_span"
        )
        if sustained_topics is not None and longest_span is not None:
            detail_zh = (
                f"现有成果形成 {sustained_topics} 个跨年份方向，最长覆盖 {longest_span} 年，"
                "更适合观察其如何沿着这些方向形成连续工作"
            )
            detail_en = (
                f"the covered work forms {sustained_topics} multi-year direction"
                f"{'s' if sustained_topics != 1 else ''}, with the longest spanning {longest_span} years, "
                "making it most useful for seeing how sustained work develops along these topics"
            )
        else:
            detail_zh = "跨年份研究延续更突出，适合观察这些方向如何形成连续工作"
            detail_en = (
                "multi-year continuity is the clearest signal, making it useful for seeing "
                "how sustained work develops along these topics"
            )
    elif dominant == "impact" and impact is not None:
        if downstream > 0:
            detail_zh = (
                f"代表成果的同主题、时间归一化影响信号更突出；当前约 "
                f"{round(downstream * 100)}% 的图谱成果出现后续扩散，适合从代表成果入手查看传播路径"
            )
            detail_en = (
                "the representative work has a stronger topic- and time-normalized impact signal, while "
                f"about {round(downstream * 100)}% of covered results show follow-on diffusion, making "
                "representative results the clearest starting point for reviewing later diffusion"
            )
        else:
            detail_zh = (
                "代表成果的同主题、时间归一化影响信号更突出，但本地图谱尚未观察到后续扩散；"
                "适合先核对代表成果，不外推其整体影响力"
            )
            detail_en = (
                "the representative work has a stronger topic- and time-normalized impact signal, "
                "but no follow-on diffusion is visible in the local graph; review the representative "
                "result without extrapolating broad influence"
            )
    elif dominant == "downstream":
        detail_zh = (
            f"当前图谱中约 {round(downstream * 100)}% 的成果出现后续扩散，"
            "更适合追踪哪些工作正在带动后续研究"
        )
        detail_en = (
            f"about {round(downstream * 100)}% of its covered results show follow-on diffusion, "
            "making it useful for tracing which work is shaping later research"
        )
    elif dominant == "topic_overlap":
        detail_zh = (
            f"双方方向重合约 {round(row['topic_overlap'] * 100)}%，"
            "更适合快速核对最接近的研究路径"
        )
        detail_en = (
            f"their topic overlap is about {round(row['topic_overlap'] * 100)}%, "
            "making this scholar useful for checking the closest related research path"
        )
    else:
        detail_zh = (
            f"近四年方向重合约 {round(row['recent_overlap'] * 100)}%，"
            f"同期收录 {recent_works} 篇图谱论文，适合继续查看近期成果变化"
        )
        detail_en = (
            f"their recent-topic overlap is about {round(row['recent_overlap'] * 100)}%, "
            f"with {recent_works} graph works covered in the latest four years, "
            "making recent changes the most useful angle to follow"
        )
    representative_sentence_zh = f"{representative_zh}。" if representative_zh else ""
    representative_sentence_en = f"{representative_en}. " if representative_en else ""
    return _i18n(
        f"{identity_zh} 和 {focus_zh} 的共同方向是 {topics_zh}。"
        f"{representative_sentence_zh}{detail_zh}。",
        f"{identity_en} and {focus_en} both work on {topics_en}. "
        f"{representative_sentence_en}{detail_en.capitalize()}.",
    )


def _peer_explanation(row: dict) -> dict:
    identity_zh = _recommendation_identity(row, "zh")
    identity_en = _recommendation_identity(row, "en")
    focus_zh = _recommendation_focus_name(row, "zh")
    focus_en = _recommendation_focus_name(row, "en")
    topics_zh = _recommendation_topic_text(row, "zh")
    topics_en = _recommendation_topic_text(row, "en")
    representative_zh = _recommendation_representative(row, "zh")
    representative_en = _recommendation_representative(row, "en")
    if row["recent_overlap"] >= row["temporal"]:
        detail_zh = (
            f"近四年方向重合约 {round(row['recent_overlap'] * 100)}%，"
            f"高于活跃年份重合的 {round(row['temporal'] * 100)}%；适合优先跟进近期成果"
        )
        detail_en = (
            f"recent-topic overlap is about {round(row['recent_overlap'] * 100)}%, above the "
            f"{round(row['temporal'] * 100)}% active-year overlap, so recent results are the clearest angle to follow"
        )
    else:
        detail_zh = (
            f"活跃年份重合约 {round(row['temporal'] * 100)}%，"
            f"近四年方向重合约 {round(row['recent_overlap'] * 100)}%；适合观察同期研究如何演进"
        )
        detail_en = (
            f"active-year overlap is about {round(row['temporal'] * 100)}%, with "
            f"{round(row['recent_overlap'] * 100)}% recent-topic overlap, making concurrent research changes useful to follow"
        )
    representative_sentence_zh = (
        f"{representative_zh}，可从这项成果入手；" if representative_zh else ""
    )
    representative_sentence_en = (
        f"{representative_en}; " if representative_en else ""
    )
    return _i18n(
        f"{identity_zh} 与 {focus_zh} 都在研究 {topics_zh}。"
        f"{representative_sentence_zh}{detail_zh}。",
        f"{identity_en} and {focus_en} both study {topics_en}. "
        f"{representative_sentence_en}{detail_en.capitalize()}.",
    )


def _collaborator_explanation(row: dict) -> dict:
    identity_zh = _recommendation_identity(row, "zh")
    identity_en = _recommendation_identity(row, "en")
    focus_zh = _recommendation_focus_name(row, "zh")
    focus_en = _recommendation_focus_name(row, "en")
    topics_zh = _recommendation_topic_text(row, "zh")
    topics_en = _recommendation_topic_text(row, "en")
    representative_zh = _recommendation_representative(row, "zh")
    representative_en = _recommendation_representative(row, "en")
    shared_count = len(row["shared_collaborators"])
    if row["direct_count"] == 0:
        relation_zh = (
            f"目前没有合著论文，但有 {shared_count} 位共同合作者可作为联系路径"
        )
        relation_en = (
            f"there is no coauthored paper yet, but {shared_count} mutual "
            f"collaborator{'s' if shared_count != 1 else ''} provide a concrete connection path"
        )
    else:
        relation_zh = (
            f"目前只有 1 篇合著论文，尚未形成稳定合作；另有 {shared_count} 位共同合作者"
        )
        relation_en = (
            f"there is only one coauthored paper and no established collaboration yet; "
            f"{shared_count} mutual collaborator{'s' if shared_count != 1 else ''} provide additional links"
        )
    representative_sentence_zh = (
        f"{representative_zh}，可先用它核对对方的实际研究侧重。" if representative_zh
        else ""
    )
    representative_sentence_en = (
        f"{representative_en}, which provides a concrete result for checking the scholar's research focus. "
        if representative_en else ""
    )
    return _i18n(
        f"{identity_zh} 与 {focus_zh} 在 {topics_zh} 上有交集，方法、系统或数据侧重存在差异。"
        f"{representative_sentence_zh}{relation_zh}，适合先核对互补点再决定是否联系。",
        f"{identity_en} overlaps with {focus_en} on {topics_en}, while the method, system, or data "
        f"focus differs. {representative_sentence_en}{relation_en.capitalize()}; verify the complementary "
        "strength before deciding whether to make contact.",
    )


def _competitor_explanation(row: dict) -> dict:
    identity_zh = _recommendation_identity(row, "zh")
    identity_en = _recommendation_identity(row, "en")
    focus_zh = _recommendation_focus_name(row, "zh")
    focus_en = _recommendation_focus_name(row, "en")
    topics_zh = _recommendation_topic_text(row, "zh")
    topics_en = _recommendation_topic_text(row, "en")
    representative_zh = _recommendation_representative(row, "zh")
    representative_en = _recommendation_representative(row, "en")
    relation_zh = (
        "尚无直接合作"
        if row["direct_count"] == 0
        else "只有少量直接合作"
    )
    relation_en = (
        "there is no direct collaboration"
        if row["direct_count"] == 0
        else "direct collaboration is limited"
    )
    representative_sentence_zh = (
        f"{representative_zh}，可用来核对具体问题边界。" if representative_zh else ""
    )
    representative_sentence_en = (
        f"{representative_en}, which can be used to check the concrete problem boundary. "
        if representative_en else ""
    )
    return _i18n(
        f"{identity_zh} 与 {focus_zh} 近期都在推进 {topics_zh}。问题表述重合约 "
        f"{round(row['problem_similarity'] * 100)}%，方法路线重合约 "
        f"{round(row['method_similarity'] * 100)}%，且{relation_zh}。"
        f"{representative_sentence_zh}这只是潜在选题重合，不是竞争关系认定。",
        f"{identity_en} and {focus_en} are both working on {topics_en}. Research-question overlap is about "
        f"{round(row['problem_similarity'] * 100)}% and method overlap is about "
        f"{round(row['method_similarity'] * 100)}%, while {relation_en}. "
        f"{representative_sentence_en}This is only potential topic overlap, not a finding of actual competition.",
    )


def _recommendations(
    dataset: dict,
    context: dict,
    focus_author_id: str,
    analyses: dict[str, dict],
    field_topics: set[str],
    *,
    limit: int,
) -> dict:
    focus = dataset["scholars"][focus_author_id]
    focus_topics = context["topic_profiles"][focus_author_id]
    focus_recent = context["recent_topic_profiles"][focus_author_id]
    focus_categories = set(context["category_profiles"][focus_author_id])
    focus_institution = (_primary_affiliation(focus) or {}).get("name")
    field_candidate_ids = set(dataset.get("field_candidate_ids") or [])
    candidates = []
    for author_id, scholar in dataset["scholars"].items():
        if author_id == focus_author_id or not scholar["work_ids"]:
            continue
        if field_candidate_ids and author_id not in field_candidate_ids:
            continue
        candidate_topic_profile = context["topic_profiles"].get(author_id, Counter())
        topic_overlap = _weighted_jaccard(
            focus_topics,
            candidate_topic_profile,
        )
        recent_overlap = _weighted_jaccard(
            focus_recent,
            context["recent_topic_profiles"].get(author_id, Counter()),
        )
        temporal = _temporal_overlap(dataset, focus, scholar)
        direct = focus.get("collaborations", {}).get(author_id, {})
        direct_count = int(direct.get("works_count") or 0)
        shared_collaborators = sorted(
            set(focus.get("collaborations", {}))
            & set(scholar.get("collaborations", {}))
        )
        method_similarity = _jaccard(
            context["method_tokens"].get(focus_author_id, set()),
            context["method_tokens"].get(author_id, set()),
        )
        problem_similarity = _jaccard(
            context["problem_tokens"].get(focus_author_id, set()),
            context["problem_tokens"].get(author_id, set()),
        )
        candidate_categories = set(context["category_profiles"].get(author_id, Counter()))
        category_overlap = _jaccard(focus_categories, candidate_categories)
        complementarity = 1 - category_overlap if focus_categories and candidate_categories else 0
        topic_display = {}
        for work_id in scholar["work_ids"]:
            for topic_name in _topic_names(dataset["works"].get(work_id) or {}):
                topic_display.setdefault(_normalized_topic(topic_name), topic_name)
        shared_topic_keys = sorted(
            set(focus_topics) & set(candidate_topic_profile),
            key=lambda topic: (
                -min(focus_topics[topic], candidate_topic_profile[topic]),
                topic,
            ),
        )[:2]
        candidates.append({
            "author_id": author_id,
            "scholar": scholar,
            "focus_name": focus.get("name"),
            "analysis": analyses[author_id],
            "topic_overlap": topic_overlap,
            "recent_overlap": recent_overlap,
            "temporal": temporal,
            "direct_count": direct_count,
            "direct": direct,
            "shared_collaborators": shared_collaborators,
            "method_similarity": method_similarity,
            "problem_similarity": problem_similarity,
            "complementarity": complementarity,
            "shared_topics": [
                topic_display.get(topic, topic)
                for topic in shared_topic_keys
            ],
            "institution_relationship": (
                "same"
                if focus_institution
                and focus_institution == (_primary_affiliation(scholar) or {}).get("name")
                else "different_or_unknown"
            ),
        })

    reference_rows = []
    reference_feature_order = (
        "topic_overlap",
        "recent_overlap",
        "downstream",
        "continuity",
        "impact",
    )
    for row in candidates:
        dimensions = row["analysis"]["dimensions"]
        quality = dimensions["academic_quality"].get("index")
        if (
            row["topic_overlap"] < 0.15
            or quality is None
            or len(row["scholar"]["work_ids"]) < 4
            or not row["scholar"].get("graph_ready")
        ):
            continue
        recent_works = sum(
            (dataset["works"][work_id].get("year") or 0)
            >= ((dataset.get("as_of_year") or 0) - 3)
            for work_id in row["scholar"]["work_ids"]
            if work_id in dataset["works"]
        )
        downstream = _safe_ratio(
            sum(
                context["incoming"].get(work_id, 0) > 0
                for work_id in row["scholar"]["work_ids"]
            ),
            len(row["scholar"]["work_ids"]),
        )
        row["reference_recent_works"] = recent_works
        row["reference_downstream"] = downstream
        row["reference_features"] = {
            "topic_overlap": row["topic_overlap"],
            "recent_overlap": row["recent_overlap"],
            "downstream": downstream,
            "continuity": (dimensions["continuity"].get("index") or 0) / 100,
            "impact": (dimensions["impact"].get("index") or 0) / 100,
        }
        row["reference_positions"] = {}
        reference_rows.append(row)

    for feature in reference_feature_order:
        values = [row["reference_features"][feature] for row in reference_rows]
        for row in reference_rows:
            value = row["reference_features"][feature]
            if len(values) <= 1:
                position = 0.5
            else:
                lower = sum(candidate < value for candidate in values)
                equal = sum(candidate == value for candidate in values)
                position = (lower + max(0, equal - 1) / 2) / (len(values) - 1)
            row["reference_positions"][feature] = position

    for row in reference_rows:
        row["reference_angle"] = max(
            reference_feature_order,
            key=lambda feature: (
                row["reference_positions"][feature],
                row["reference_features"][feature],
                -reference_feature_order.index(feature),
            ),
        )

    north_stars = []
    peers = []
    collaborators = []
    competitors = []
    collaborator_ids = set()
    for row in candidates:
        analysis = row["analysis"]
        confidence = analysis["confidence"]
        dimensions = analysis["dimensions"]
        quality = dimensions["academic_quality"].get("index")
        continuity = dimensions["continuity"].get("index")
        impact = dimensions["impact"].get("index")
        if (
            row["topic_overlap"] >= 0.15
            and quality is not None
            and len(row["scholar"]["work_ids"]) >= 4
            and row["scholar"].get("graph_ready")
        ):
            recent_works = row["reference_recent_works"]
            recent_activity = min(1.0, recent_works / 4)
            downstream = row["reference_downstream"]
            score = (
                row["topic_overlap"] * 0.30
                + quality / 100 * 0.20
                + (continuity or 0) / 100 * 0.15
                + (impact or 0) / 100 * 0.15
                + recent_activity * 0.10
                + downstream * 0.10
            )
            north_stars.append(_recommendation(
                "north_star",
                row["scholar"],
                score,
                confidence,
                _reference_explanation(
                    row,
                    continuity,
                    impact,
                    downstream,
                    recent_works,
                ),
                [
                    _evidence(
                        "shared_topics",
                        "共同研究方向",
                        "Shared research topics",
                        "、".join(row["shared_topics"]) or _i18n(
                            "方向名称不足",
                            "Topic names unavailable",
                        ),
                    ),
                    _evidence("field_overlap", "领域方向重合度", "Field-topic overlap", round(row["topic_overlap"], 3)),
                    _evidence("continuity", "研究延续性指数", "Continuity index", continuity),
                    _evidence("impact", "归一化影响力指数", "Normalized impact index", impact),
                    _evidence("recent_activity", "近四年图谱论文", "Graph papers in the latest four years", recent_works),
                    _evidence("downstream", "成果后续扩散覆盖", "Follow-on diffusion coverage", round(downstream, 3)),
                ],
                analysis["limitations"],
            ))

        if (
            row["topic_overlap"] >= 0.18
            and row["temporal"] >= 0.15
            and row["scholar"].get("graph_ready")
        ):
            score = (
                row["topic_overlap"] * 0.45
                + row["temporal"] * 0.20
                + row["recent_overlap"] * 0.25
                + (0.1 if _primary_affiliation(row["scholar"]) else 0)
            )
            peers.append(_recommendation(
                "peer",
                row["scholar"],
                score,
                confidence,
                _peer_explanation(row),
                [
                    _evidence(
                        "shared_topics",
                        "共同研究方向",
                        "Shared research topics",
                        "、".join(row["shared_topics"]) or _i18n(
                            "方向名称不足",
                            "Topic names unavailable",
                        ),
                    ),
                    _evidence("topic_overlap", "研究方向重合度", "Research-topic overlap", round(row["topic_overlap"], 3)),
                    _evidence("temporal_overlap", "活跃年份重合度", "Active-year overlap", round(row["temporal"], 3)),
                    _evidence("recent_overlap", "近期论文方向重合度", "Recent-paper topic overlap", round(row["recent_overlap"], 3)),
                    _evidence("institution", "当前论文关联机构", "Current publication-linked institution", (_primary_affiliation(row["scholar"]) or {}).get("name")),
                ],
                analysis["limitations"],
            ))

        collaboration_eligible = (
            row["scholar"].get("graph_ready")
            and row["direct_count"] <= 1
            and len(row["shared_collaborators"]) >= 1
            and row["topic_overlap"] >= 0.15
            and row["complementarity"] >= 0.15
        )
        if collaboration_eligible:
            score = (
                row["topic_overlap"] * 0.25
                + row["complementarity"] * 0.25
                + min(1, len(row["shared_collaborators"]) / 3) * 0.20
                + min(1, row["direct_count"] / 4) * 0.20
                + row["temporal"] * 0.10
            )
            collaborator_ids.add(row["author_id"])
            collaborators.append(_recommendation(
                "potential_collaborator",
                row["scholar"],
                score,
                confidence,
                _collaborator_explanation(row),
                [
                    _evidence(
                        "shared_topics",
                        "共同研究方向",
                        "Shared research topics",
                        "、".join(row["shared_topics"]) or _i18n(
                            "方向名称不足",
                            "Topic names unavailable",
                        ),
                    ),
                    _evidence("topic_overlap", "主题交集", "Topic overlap", round(row["topic_overlap"], 3)),
                    _evidence("capability_complementarity", "方法/系统/数据类型互补度", "Method/system/data type complementarity", round(row["complementarity"], 3)),
                    _evidence("direct_collaboration", "直接合作论文", "Directly coauthored papers", row["direct_count"]),
                    _evidence("shared_collaborators", "共同合作者", "Shared collaborators", len(row["shared_collaborators"])),
                    _evidence("temporal_overlap", "活跃时间重合度", "Active-period overlap", round(row["temporal"], 3)),
                ],
                [_i18n(
                    "稳定合作者属于合作关系页；一次合作若缺少互补性或共同合作者路径，也不作为新的合作线索。",
                    "Established collaborators belong in the collaboration view; one-off collaboration without complementarity or a shared-collaborator path is not treated as a new collaboration lead.",
                )],
            ))

    for row in candidates:
        if (
            row["author_id"] in collaborator_ids
            or row["direct_count"] >= 2
            or not row["scholar"].get("graph_ready")
        ):
            continue
        if (
            row["recent_overlap"] < 0.25
            or row["problem_similarity"] < 0.08
            or row["method_similarity"] < 0.08
            or row["temporal"] < 0.15
        ):
            continue
        score = (
            row["recent_overlap"] * 0.35
            + row["problem_similarity"] * 0.25
            + row["method_similarity"] * 0.20
            + row["temporal"] * 0.15
            + (0.05 if row["direct_count"] == 0 else 0)
        )
        competitors.append(_recommendation(
            "potential_competitor",
            row["scholar"],
            score,
            row["analysis"]["confidence"],
            _competitor_explanation(row),
            [
                _evidence(
                    "shared_topics",
                    "共同研究方向",
                    "Shared research topics",
                    "、".join(row["shared_topics"]) or _i18n(
                        "方向名称不足",
                        "Topic names unavailable",
                    ),
                ),
                _evidence("recent_topic_overlap", "近期研究问题方向重合度", "Recent research-problem topic overlap", round(row["recent_overlap"], 3)),
                _evidence("problem_similarity", "摘要问题表述相似度", "Abstract-problem similarity", round(row["problem_similarity"], 3)),
                _evidence("method_similarity", "摘要方法路线相似度", "Abstract-method similarity", round(row["method_similarity"], 3)),
                _evidence("temporal_overlap", "发表时间重合度", "Publication-time overlap", round(row["temporal"], 3)),
                _evidence(
                    "team_context",
                    "机构/团队关系",
                    "Institution/team context",
                    (
                        _i18n(
                            "当前论文关联机构相同",
                            "Current publication-linked affiliation is the same",
                        )
                        if row["institution_relationship"] == "same"
                        else _i18n(
                            "当前论文关联机构不同或信息不足",
                            "Current publication-linked affiliations differ or are incomplete",
                        )
                    ),
                ),
                _evidence("direct_collaboration", "直接合作论文", "Directly coauthored papers", row["direct_count"]),
            ],
            [_i18n(
                "方向相似本身不足以判断竞争；只有问题、方法、时间与合作关系同时满足门槛才进入此列表。",
                "Topic similarity alone is insufficient; problem, method, time, and collaboration thresholds must all be met.",
            )],
        ))

    def stable(rows: list[dict]) -> list[dict]:
        return sorted(rows, key=lambda item: (-item["index"], item["author_id"]))[:limit]

    return {
        "north_stars": stable(north_stars),
        "peers": stable(peers),
        "potential_collaborators": stable(collaborators),
        "potential_competitors": stable(competitors),
    }


def _team_views(
    dataset: dict,
    context: dict,
    focus_author_id: str,
    field_topics: set[str],
) -> dict:
    groups: dict[str, dict] = {}
    for author_id, scholar in dataset["scholars"].items():
        affiliation = _primary_affiliation(scholar)
        if not affiliation or not affiliation.get("name"):
            continue
        key = affiliation.get("source_id") or affiliation["name"].casefold()
        group = groups.setdefault(key, {
            "institution_id": affiliation.get("source_id") or affiliation.get("id"),
            "name": affiliation["name"],
            "member_ids": set(),
            "work_ids": set(),
        })
        group["member_ids"].add(author_id)
        group["work_ids"].update(scholar["work_ids"])
    rows = []
    for key, group in groups.items():
        topics = Counter()
        topic_display = {}
        years = set()
        for work_id in group["work_ids"]:
            work = dataset["works"].get(work_id)
            if not work:
                continue
            if work.get("year"):
                years.add(work["year"])
            for name in _topic_names(work):
                normalized = _normalized_topic(name)
                topics[normalized] += 1
                topic_display.setdefault(normalized, name)
        overlap = _safe_ratio(
            sum(topics[topic] for topic in field_topics),
            sum(topics.values()),
        )
        ready_members = sum(
            dataset["scholars"][author_id].get("graph_ready", False)
            for author_id in group["member_ids"]
        )
        confidence_score = (
            min(1, len(group["member_ids"]) / 4) * 0.35
            + min(1, len(group["work_ids"]) / 20) * 0.35
            + _safe_ratio(ready_members, len(group["member_ids"])) * 0.3
        )
        level = "high" if confidence_score >= 0.78 else "medium" if confidence_score >= 0.55 else "low"
        top_topics = [
            {"name": topic_display.get(topic, topic), "works_count": count}
            for topic, count in sorted(
                topics.items(),
                key=lambda item: (-item[1], item[0]),
            )[:6]
        ]
        rows.append({
            "institution_id": group["institution_id"],
            "name": group["name"],
            "member_count": len(group["member_ids"]),
            "covered_work_count": len(group["work_ids"]),
            "active_years": len(years),
            "field_overlap": round(overlap, 3),
            "topics": top_topics,
            "confidence": {
                "level": level,
                "score": round(confidence_score, 3),
                "label": {
                    "high": _i18n("高", "High"),
                    "medium": _i18n("中等", "Medium"),
                    "low": _i18n("低", "Low"),
                }[level],
            },
            "representative_members": [
                _public_scholar(dataset["scholars"][author_id])
                for author_id in sorted(group["member_ids"])[:6]
            ],
            "evidence": [
                _evidence("members", "当前图谱覆盖成员", "Members covered by the current graph", len(group["member_ids"])),
                _evidence("works", "去重后的图谱论文", "Distinct graph papers", len(group["work_ids"])),
                _evidence("years", "有论文的年份数", "Years with publications", len(years)),
                _evidence("field_overlap", "目标领域论文—主题占比", "Target-field paper-topic share", round(overlap, 3)),
            ],
        })
    rows.sort(
        key=lambda row: (
            -row["field_overlap"],
            -row["member_count"],
            -row["covered_work_count"],
            row["name"],
        )
    )
    focus_affiliation = _primary_affiliation(dataset["scholars"][focus_author_id])
    focus_key = (
        (focus_affiliation.get("source_id") or focus_affiliation["name"].casefold())
        if focus_affiliation
        else None
    )
    focus_team = next(
        (row for row in rows if (row["institution_id"] or row["name"].casefold()) == focus_key),
        None,
    )
    field_rows = [
        row
        for row in rows
        if row["field_overlap"] > 0 or row is focus_team
    ]
    return {
        "focus_team": focus_team,
        "field_teams": field_rows[:8],
        "limitations": [
            _i18n(
                "团队视角按当前论文关联机构聚合，仅代表本地图谱覆盖成员，不等同于机构完整名册。",
                "Team views aggregate current publication-linked affiliations and represent only locally covered graph members, not complete institutional rosters.",
            ),
            _i18n(
                "共同机构与主题重合不表示组织归属、项目参与或竞争关系。",
                "Shared affiliation and topic overlap do not establish organizational membership, project participation, or competition.",
            ),
        ],
    }


def build_scholar_intelligence(
    repository,
    author_id: str,
    *,
    limit: int = 8,
) -> dict:
    dataset = load_intelligence_dataset(repository, author_id)
    context = _build_context(dataset)
    focus = dataset["scholars"].get(author_id)
    if not focus:
        focus = _empty_scholar(author_id)
        dataset["scholars"][author_id] = focus
    topics = _field_topics(dataset, context, author_id)
    field_topic_names = {row["normalized_name"] for row in topics}
    if not field_topic_names:
        field_topic_names = set(context["topic_profiles"].get(author_id, Counter()))

    analyses = {
        candidate_id: _scholar_analysis(
            dataset,
            context,
            candidate_id,
            field_topic_names or set(context["topic_profiles"].get(candidate_id, Counter())),
        )
        for candidate_id in dataset["scholars"]
        if dataset["scholars"][candidate_id]["work_ids"]
    }
    if author_id not in analyses:
        analyses[author_id] = _scholar_analysis(
            dataset, context, author_id, field_topic_names
        )
    recommendations = _recommendations(
        dataset,
        context,
        author_id,
        analyses,
        field_topic_names,
        limit=limit,
    )
    subject_analysis = analyses[author_id]
    teams = _team_views(dataset, context, author_id, field_topic_names)
    discovery = get_field_discovery_state(repository, author_id)
    institution_topics = (
        discovery.get("selected_topics")
        or [
            {
                "name": row["name"],
                "works_count": row["works_count"],
                "active_years": row["active_years"],
            }
            for row in topics
        ]
    )
    institutions = build_field_institutions(
        repository,
        author_id,
        dataset,
        institution_topics,
    )
    return {
        "analysis_version": ANALYSIS_VERSION,
        "source": "dynamic_research_graph",
        "generated_from_graph_version": int(focus.get("graph_version") or 0),
        "explanation_mode": "deterministic_templates",
        "subject": subject_analysis["subject"],
        "field": {
            "topics": [
                {
                    "name": row["name"],
                    "works_count": row["works_count"],
                    "active_years": row["active_years"],
                }
                for row in topics
            ],
            "as_of_year": dataset.get("as_of_year"),
            "candidate_count": max(0, len(dataset["scholars"]) - 1),
            "scope": _i18n(
                "当前平台动态研究图谱中的相关学者样本",
                "Related scholars in the platform's current dynamic research graph",
            ),
        },
        "methodology": {
            "score_source": _i18n(
                "确定性统计与图谱特征；LLM 未参与评分",
                "Deterministic statistics and graph features; no LLM scoring",
            ),
            "ranking_scope": _i18n(
                "相对参照列表，不生成绝对“最好学者”",
                "A relative reference list, not an absolute best-scholar ranking",
            ),
            "principles": [
                _i18n("引用按时间与本地领域样本归一化，不直接等同质量。", "Citations are time- and local-field-normalized and do not directly equal quality."),
                _i18n("论文数量不进入影响力指数。", "Paper count is excluded from the impact index."),
                _i18n("竞争推荐必须同时满足问题、方法、时间和低合作门槛。", "Competition recommendations require problem, method, time, and low-collaboration thresholds."),
                _i18n("单次合作不作为长期合作者证据。", "A one-off collaboration is not treated as long-term collaboration evidence."),
            ],
        },
        "confidence": subject_analysis["confidence"],
        "dimensions": subject_analysis["dimensions"],
        "representative_works": subject_analysis["representative_works"],
        "recommendations": recommendations,
        "field_reference_list": {
            "label": _i18n(
                "领域北极星参照学者",
                "Field north-star reference scholars",
            ),
            "is_absolute_ranking": False,
            "items": recommendations["north_stars"],
        },
        "teams": teams,
        "discovery": discovery,
        "institutions": institutions,
        "limitations": (
            subject_analysis["limitations"]
            + teams["limitations"]
            + institutions["limitations"]
        ),
    }


def _comparison_dimension(left: dict, right: dict, key: str) -> dict:
    left_dimension = left["dimensions"][key]
    right_dimension = right["dimensions"][key]
    available = (
        left_dimension["status"] == "available"
        and right_dimension["status"] == "available"
    )
    if not available:
        conclusion = _i18n(
            "至少一侧数据不足，无法可靠比较。",
            "At least one side has insufficient data for a reliable comparison.",
        )
    else:
        difference = abs((left_dimension.get("index") or 0) - (right_dimension.get("index") or 0))
        conclusion = _i18n(
            "两侧指数接近，应优先比较证据构成。"
            if difference < 8
            else "两侧在当前图谱相对指数上存在差异；该差异不表示因果或绝对优劣。",
            "The two indices are close; compare the evidence composition first."
            if difference < 8
            else "The local-graph relative indices differ; this does not imply causality or absolute superiority.",
        )
    return {
        "key": key,
        "status": "available" if available else "insufficient",
        "left": {
            "index": left_dimension.get("index"),
            "confidence": left_dimension["confidence"],
            "evidence": left_dimension.get("evidence") or [],
        },
        "right": {
            "index": right_dimension.get("index"),
            "confidence": right_dimension["confidence"],
            "evidence": right_dimension.get("evidence") or [],
        },
        "conclusion": conclusion,
    }


def _team_for_author(team_views: dict, author_id: str) -> dict | None:
    for team in team_views["field_teams"]:
        if any(
            member["author_id"] == author_id
            for member in team["representative_members"]
        ):
            return team
    return None


def compare_scholar_intelligence(
    repository,
    left_author_id: str,
    right_author_id: str,
    *,
    mode: str = "scholar",
) -> dict:
    if mode == "institution":
        return compare_field_institutions(
            repository,
            left_author_id,
            right_author_id,
        )
    dataset = load_intelligence_dataset(
        repository,
        left_author_id,
        extra_author_ids=[right_author_id],
    )
    context = _build_context(dataset)
    missing = [
        author_id
        for author_id in (left_author_id, right_author_id)
        if author_id not in dataset["scholars"]
    ]
    if missing:
        return {
            "analysis_version": ANALYSIS_VERSION,
            "mode": mode,
            "status": "insufficient",
            "conclusion": _i18n(INSUFFICIENT_ZH, INSUFFICIENT_EN),
            "missing_author_ids": missing,
        }
    shared_topics = (
        set(context["topic_profiles"].get(left_author_id, Counter()))
        | set(context["topic_profiles"].get(right_author_id, Counter()))
    )
    left = _scholar_analysis(
        dataset, context, left_author_id, shared_topics
    )
    right = _scholar_analysis(
        dataset, context, right_author_id, shared_topics
    )
    if mode == "team":
        left_views = _team_views(dataset, context, left_author_id, shared_topics)
        right_views = _team_views(dataset, context, right_author_id, shared_topics)
        left_team = _team_for_author(left_views, left_author_id) or left_views["focus_team"]
        right_team = _team_for_author(right_views, right_author_id) or right_views["focus_team"]
        if not left_team or not right_team:
            return {
                "analysis_version": ANALYSIS_VERSION,
                "mode": "team",
                "status": "insufficient",
                "left": left_team,
                "right": right_team,
                "conclusion": _i18n(
                    "至少一侧缺少可核验的当前机构团队数据，无法可靠比较。",
                    "At least one side lacks verifiable current-affiliation team data.",
                ),
                "limitations": left_views["limitations"],
            }
        return {
            "analysis_version": ANALYSIS_VERSION,
            "mode": "team",
            "status": "available",
            "left": left_team,
            "right": right_team,
            "dimensions": [
                {
                    "key": "covered_members",
                    "left": left_team["member_count"],
                    "right": right_team["member_count"],
                    "label": _i18n("本地图谱覆盖成员", "Locally covered members"),
                },
                {
                    "key": "covered_works",
                    "left": left_team["covered_work_count"],
                    "right": right_team["covered_work_count"],
                    "label": _i18n("去重后的图谱论文", "Distinct graph papers"),
                },
                {
                    "key": "active_years",
                    "left": left_team["active_years"],
                    "right": right_team["active_years"],
                    "label": _i18n("有论文的年份数", "Years with publications"),
                },
                {
                    "key": "field_overlap",
                    "left": left_team["field_overlap"],
                    "right": right_team["field_overlap"],
                    "label": _i18n("目标领域覆盖", "Target-field coverage"),
                },
            ],
            "conclusion": _i18n(
                "团队比较仅展示本地图谱覆盖、方向组合与时间跨度，不给出绝对团队优劣。",
                "The team comparison shows local coverage, topic mix, and time span without declaring an absolute better team.",
            ),
            "limitations": left_views["limitations"],
        }
    return {
        "analysis_version": ANALYSIS_VERSION,
        "mode": "scholar",
        "status": "available",
        "left": left["subject"],
        "right": right["subject"],
        "dimensions": [
            _comparison_dimension(left, right, key)
            for key in ("academic_quality", "continuity", "impact")
        ],
        "topic_overlap": round(_weighted_jaccard(
            context["topic_profiles"].get(left_author_id, Counter()),
            context["topic_profiles"].get(right_author_id, Counter()),
        ), 3),
        "representative_works": {
            "left": left["representative_works"],
            "right": right["representative_works"],
        },
        "conclusion": _i18n(
            "比较使用同一动态研究图谱口径与确定性特征；差异用于理解研究轨迹，不表示因果或绝对优劣。",
            "The comparison uses one dynamic-graph scope and deterministic features; differences describe research trajectories, not causality or absolute superiority.",
        ),
        "limitations": list({
            item["zh"]: item
            for item in left["limitations"] + right["limitations"]
        }.values()),
    }
