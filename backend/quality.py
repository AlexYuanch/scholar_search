"""画像发布前的数据质量检查。"""
from dataclasses import dataclass


@dataclass(frozen=True)
class QualityAssessment:
    publishable: bool
    flags: list[str]


def assess_profile_quality(state: dict, cached: dict | None = None) -> QualityAssessment:
    """判断一次工作流结果是否可以替换当前最新画像。"""
    flags: list[str] = []
    blocking_flags: list[str] = []
    works = state.get("deduped_works") or []
    profile = state.get("target_author_profile") or {}
    expected = int(profile.get("works_count") or 0)
    fetched = len(works)

    if not state.get("works_complete", False):
        blocking_flags.append("partial_works_fetch")
    if state.get("errors"):
        blocking_flags.append("workflow_errors")
    if not state.get("web_payload"):
        blocking_flags.append("missing_payload")
    evidence_review = state.get("evidence_review") or {}
    if evidence_review and not evidence_review.get("publishable", False):
        blocking_flags.append("evidence_review_failed")

    allowed_gap = max(5, int(expected * 0.2))
    if expected and expected - fetched > allowed_gap:
        blocking_flags.append("openalex_count_mismatch")

    previous_count = int(((cached or {}).get("payload") or {}).get("totalPapers") or 0)
    if previous_count >= 10 and fetched < previous_count * 0.8:
        blocking_flags.append("suspicious_paper_drop")

    institutions = profile.get("last_known_institutions") or []
    countries = {item.get("country_code") for item in institutions if item.get("country_code")}
    if len(countries) > 1:
        flags.append("institution_country_conflict")

    topics = state.get("topic_clusters") or []
    if len(topics) >= 8 and max((float(item.get("weight") or 0) for item in topics), default=0) < 0.25:
        flags.append("broad_topic_span")

    names: dict[str, set[str]] = {}
    for node in state.get("graph_nodes") or []:
        if node.get("type") != "coauthor":
            continue
        normalized = " ".join(str(node.get("name") or "").lower().split())
        if normalized:
            names.setdefault(normalized, set()).add(str(node.get("id") or ""))
    if any(len(ids) > 1 for ids in names.values()):
        flags.append("coauthor_name_collision")

    flags = blocking_flags + flags
    return QualityAssessment(publishable=not blocking_flags, flags=flags)
