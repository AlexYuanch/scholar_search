"""Pure, deterministic recommendation narrative helpers.

This module turns already-computed graph evidence into localized explanations.
It does not query repositories, mutate candidate rows, or calculate ranking
scores.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Literal, Mapping


LocalizedText = dict[str, str]
ReferenceAngle = Literal[
    "topic_overlap",
    "recent_overlap",
    "downstream",
    "continuity",
    "impact",
]

REFERENCE_FEATURE_ORDER: tuple[ReferenceAngle, ...] = (
    "topic_overlap",
    "recent_overlap",
    "downstream",
    "continuity",
    "impact",
)
REFERENCE_FEATURE_PRIORITY = {
    feature: -index
    for index, feature in enumerate(REFERENCE_FEATURE_ORDER)
}


@dataclass(frozen=True)
class NarrativeContext:
    identity_zh: str
    identity_en: str
    focus_zh: str
    focus_en: str
    topics_zh: str
    topics_en: str
    representative_title: str | None = None
    representative_year: int | None = None


@dataclass(frozen=True)
class ReferenceMetrics:
    recent_works: int
    downstream: float
    continuity: float | None
    impact: float | None
    topic_overlap: float
    recent_overlap: float
    sustained_topics: int | None
    longest_span: int | None
    angle: ReferenceAngle | None = None

    def features(self) -> dict[ReferenceAngle, float]:
        return {
            "topic_overlap": self.topic_overlap,
            "recent_overlap": self.recent_overlap,
            "downstream": self.downstream,
            "continuity": (self.continuity or 0) / 100,
            "impact": (self.impact or 0) / 100,
        }


@dataclass(frozen=True)
class PeerMetrics:
    recent_overlap: float
    temporal_overlap: float


@dataclass(frozen=True)
class CollaboratorMetrics:
    direct_count: int
    shared_collaborator_count: int


@dataclass(frozen=True)
class CompetitorMetrics:
    direct_count: int
    problem_similarity: float
    method_similarity: float


def assign_reference_angles(
    metrics_by_author: Mapping[str, ReferenceMetrics],
) -> dict[str, ReferenceMetrics]:
    """Choose the most distinguishing evidence angle within this candidate set."""
    if not metrics_by_author:
        return {}
    features_by_author = {
        author_id: metrics.features()
        for author_id, metrics in metrics_by_author.items()
    }
    feature_values = {
        feature: [
            features[feature]
            for features in features_by_author.values()
        ]
        for feature in REFERENCE_FEATURE_ORDER
    }
    result = {}
    for author_id, metrics in metrics_by_author.items():
        features = features_by_author[author_id]
        positions = {
            feature: _relative_position(
                features[feature],
                feature_values[feature],
            )
            for feature in REFERENCE_FEATURE_ORDER
        }
        angle = max(
            REFERENCE_FEATURE_ORDER,
            key=lambda feature: (
                positions[feature],
                features[feature],
                REFERENCE_FEATURE_PRIORITY[feature],
            ),
        )
        result[author_id] = replace(metrics, angle=angle)
    return result


def reference_explanation(
    context: NarrativeContext,
    metrics: ReferenceMetrics,
) -> LocalizedText:
    angle = metrics.angle or max(
        REFERENCE_FEATURE_ORDER,
        key=lambda feature: (
            metrics.features()[feature],
            REFERENCE_FEATURE_PRIORITY[feature],
        ),
    )
    detail_zh, detail_en = _reference_detail(angle, metrics)
    representative_zh = _representative_phrase(context, "zh")
    representative_en = _representative_phrase(context, "en")
    return _localized(
        f"{context.identity_zh} 和 {context.focus_zh} 的共同方向是 {context.topics_zh}。"
        f"{_sentence(representative_zh)}{detail_zh}。",
        f"{context.identity_en} and {context.focus_en} both work on {context.topics_en}. "
        f"{_sentence(representative_en, trailing_space=True)}{detail_en.capitalize()}.",
    )


def peer_explanation(
    context: NarrativeContext,
    metrics: PeerMetrics,
) -> LocalizedText:
    recent = round(metrics.recent_overlap * 100)
    temporal = round(metrics.temporal_overlap * 100)
    if metrics.recent_overlap >= metrics.temporal_overlap:
        detail_zh = (
            f"近四年方向重合约 {recent}%，高于活跃年份重合的 {temporal}%；"
            "适合优先跟进近期成果"
        )
        detail_en = (
            f"recent-topic overlap is about {recent}%, above the {temporal}% "
            "active-year overlap, so recent results are the clearest angle to follow"
        )
    else:
        detail_zh = (
            f"活跃年份重合约 {temporal}%，近四年方向重合约 {recent}%；"
            "适合观察同期研究如何演进"
        )
        detail_en = (
            f"active-year overlap is about {temporal}%, with {recent}% recent-topic "
            "overlap, making concurrent research changes useful to follow"
        )
    representative_zh = _representative_phrase(context, "zh")
    representative_en = _representative_phrase(context, "en")
    lead_zh = f"{representative_zh}，可从这项成果入手；" if representative_zh else ""
    lead_en = f"{representative_en}; " if representative_en else ""
    return _localized(
        f"{context.identity_zh} 与 {context.focus_zh} 都在研究 {context.topics_zh}。"
        f"{lead_zh}{detail_zh}。",
        f"{context.identity_en} and {context.focus_en} both study {context.topics_en}. "
        f"{lead_en}{detail_en.capitalize()}.",
    )


def collaborator_explanation(
    context: NarrativeContext,
    metrics: CollaboratorMetrics,
) -> LocalizedText:
    shared = metrics.shared_collaborator_count
    if metrics.direct_count == 0:
        relation_zh = f"目前没有合著论文，但有 {shared} 位共同合作者可作为联系路径"
        relation_en = (
            f"there is no coauthored paper yet, but {shared} mutual "
            f"collaborator{'s' if shared != 1 else ''} provide a concrete connection path"
        )
    else:
        relation_zh = f"目前只有 1 篇合著论文，尚未形成稳定合作；另有 {shared} 位共同合作者"
        relation_en = (
            "there is only one coauthored paper and no established collaboration yet; "
            f"{shared} mutual collaborator{'s' if shared != 1 else ''} provide additional links"
        )
    representative_zh = _representative_phrase(context, "zh")
    representative_en = _representative_phrase(context, "en")
    lead_zh = (
        f"{representative_zh}，可先用它核对对方的实际研究侧重。"
        if representative_zh else ""
    )
    lead_en = (
        f"{representative_en}, which provides a concrete result for checking the "
        "scholar's research focus. "
        if representative_en else ""
    )
    return _localized(
        f"{context.identity_zh} 与 {context.focus_zh} 在 {context.topics_zh} 上有交集，"
        f"方法、系统或数据侧重存在差异。{lead_zh}{relation_zh}，"
        "适合先核对互补点再决定是否联系。",
        f"{context.identity_en} overlaps with {context.focus_en} on {context.topics_en}, "
        f"while the method, system, or data focus differs. {lead_en}"
        f"{relation_en.capitalize()}; verify the complementary strength before deciding "
        "whether to make contact.",
    )


def competitor_explanation(
    context: NarrativeContext,
    metrics: CompetitorMetrics,
) -> LocalizedText:
    problem = round(metrics.problem_similarity * 100)
    method = round(metrics.method_similarity * 100)
    relation_zh = "尚无直接合作" if metrics.direct_count == 0 else "只有少量直接合作"
    relation_en = (
        "there is no direct collaboration"
        if metrics.direct_count == 0
        else "direct collaboration is limited"
    )
    representative_zh = _representative_phrase(context, "zh")
    representative_en = _representative_phrase(context, "en")
    lead_zh = f"{representative_zh}，可用来核对具体问题边界。" if representative_zh else ""
    lead_en = (
        f"{representative_en}, which can be used to check the concrete problem boundary. "
        if representative_en else ""
    )
    return _localized(
        f"{context.identity_zh} 与 {context.focus_zh} 近期都在推进 {context.topics_zh}。"
        f"问题表述重合约 {problem}%，方法路线重合约 {method}%，且{relation_zh}。"
        f"{lead_zh}这只是潜在选题重合，不是竞争关系认定。",
        f"{context.identity_en} and {context.focus_en} are both working on "
        f"{context.topics_en}. Research-question overlap is about {problem}% and method "
        f"overlap is about {method}%, while {relation_en}. {lead_en}"
        "This is only potential topic overlap, not a finding of actual competition.",
    )


def _reference_detail(
    angle: ReferenceAngle,
    metrics: ReferenceMetrics,
) -> tuple[str, str]:
    if angle == "continuity":
        if metrics.sustained_topics is not None and metrics.longest_span is not None:
            plural = "s" if metrics.sustained_topics != 1 else ""
            return (
                f"现有成果形成 {metrics.sustained_topics} 个跨年份方向，"
                f"最长覆盖 {metrics.longest_span} 年，更适合观察其如何沿着这些方向形成连续工作",
                f"the covered work forms {metrics.sustained_topics} multi-year direction{plural}, "
                f"with the longest spanning {metrics.longest_span} years, making it most useful "
                "for seeing how sustained work develops along these topics",
            )
        return (
            "跨年份研究延续更突出，适合观察这些方向如何形成连续工作",
            "multi-year continuity is the clearest signal, making it useful for seeing "
            "how sustained work develops along these topics",
        )
    if angle == "impact":
        downstream = round(metrics.downstream * 100)
        if metrics.downstream > 0:
            return (
                "代表成果的同主题、时间归一化影响信号更突出；"
                f"当前约 {downstream}% 的图谱成果出现后续扩散，"
                "适合从代表成果入手查看传播路径",
                "the representative work has a stronger topic- and time-normalized impact "
                f"signal, while about {downstream}% of covered results show follow-on "
                "diffusion, making representative results the clearest starting point for "
                "reviewing later diffusion",
            )
        return (
            "代表成果的同主题、时间归一化影响信号更突出，但本地图谱尚未观察到"
            "后续扩散；适合先核对代表成果，不外推其整体影响力",
            "the representative work has a stronger topic- and time-normalized impact signal, "
            "but no follow-on diffusion is visible in the local graph; review the representative "
            "result without extrapolating broad influence",
        )
    if angle == "downstream":
        downstream = round(metrics.downstream * 100)
        return (
            f"当前图谱中约 {downstream}% 的成果出现后续扩散，"
            "更适合追踪哪些工作正在带动后续研究",
            f"about {downstream}% of its covered results show follow-on diffusion, "
            "making it useful for tracing which work is shaping later research",
        )
    if angle == "topic_overlap":
        overlap = round(metrics.topic_overlap * 100)
        return (
            f"双方方向重合约 {overlap}%，更适合快速核对最接近的研究路径",
            f"their topic overlap is about {overlap}%, making this scholar useful for "
            "checking the closest related research path",
        )
    recent = round(metrics.recent_overlap * 100)
    return (
        f"近四年方向重合约 {recent}%，同期收录 {metrics.recent_works} 篇图谱论文，"
        "适合继续查看近期成果变化",
        f"their recent-topic overlap is about {recent}%, with {metrics.recent_works} "
        "graph works covered in the latest four years, making recent changes the most "
        "useful angle to follow",
    )


def _relative_position(value: float, values: list[float]) -> float:
    if len(values) <= 1:
        return 0.5
    lower = sum(candidate < value for candidate in values)
    equal = sum(candidate == value for candidate in values)
    return (lower + max(0, equal - 1) / 2) / (len(values) - 1)


def _representative_phrase(
    context: NarrativeContext,
    lang: Literal["zh", "en"],
) -> str:
    if not context.representative_title:
        return ""
    if lang == "zh":
        year = f"（{context.representative_year}）" if context.representative_year else ""
        return f"当前图谱选出的代表成果之一是《{context.representative_title}》{year}"
    year = f" ({context.representative_year})" if context.representative_year else ""
    return (
        f'One representative result in the current graph is '
        f'“{context.representative_title}”{year}'
    )


def _sentence(value: str, *, trailing_space: bool = False) -> str:
    if not value:
        return ""
    return f"{value}. " if trailing_space else f"{value}。"


def _localized(zh: str, en: str) -> LocalizedText:
    return {"zh": zh, "en": en}
