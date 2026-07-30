"""LangGraph 工作流的节点函数。

每个节点接收当前 state，返回要更新的字段 dict。
节点按处理阶段分组，与 workflow.py 中的图定义一一对应。
"""
import json
import math
import re
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
from datetime import datetime, timezone
from affiliation_evidence import build_affiliation_evidence, select_primary_affiliation
from state import ScholarProfileState


CROSSREF_VERIFICATION_LIMIT = 200


# ── 工具函数 ─────────────────────────────────────────────────

def _normalized_name_keys(author: dict) -> set[str]:
    values = [author.get("display_name", ""), *(author.get("display_name_alternatives") or [])]
    keys = set()
    for value in values:
        tokens = re.findall(r"[a-z0-9㐀-鿿]+", str(value).casefold())
        if tokens:
            keys.update({" ".join(tokens), " ".join(sorted(tokens)), "".join(tokens)})
    return keys


def _institution_keys(author: dict) -> set[str]:
    keys = set()
    for institution in author.get("last_known_institutions") or []:
        value = institution.get("id") or institution.get("display_name")
        normalized = _normalized_title(value)
        if normalized:
            keys.add(normalized)
    return keys


def _orcid(author: dict) -> str:
    return str(author.get("orcid") or "").rstrip("/").rsplit("/", 1)[-1].casefold()


def _fingerprint_set(author: dict, field: str) -> set[str]:
    return {str(item) for item in (author.get("identity_fingerprint") or {}).get(field, []) if item}


def _containment(left: set[str], right: set[str]) -> tuple[int, float]:
    shared = len(left & right)
    return shared, shared / max(1, min(len(left), len(right)))


def _identity_match(left: dict, right: dict, candidate_ids: set[str]) -> dict:
    if left.get("id") and left.get("id") == right.get("id"):
        return {"merge": True, "confidence": "high", "reason": "same_openalex_id"}
    left_orcid = _orcid(left)
    right_orcid = _orcid(right)
    if left_orcid and left_orcid == right_orcid:
        return {"merge": True, "confidence": "high", "reason": "same_orcid"}
    if not (_normalized_name_keys(left) & _normalized_name_keys(right)):
        return {"merge": False}

    left_institutions = _institution_keys(left)
    right_institutions = _institution_keys(right)
    institutions = left_institutions & right_institutions
    _, institution_containment = _containment(left_institutions, right_institutions)
    compact_institution_history = max(len(left_institutions), len(right_institutions)) <= 12
    left_works = _fingerprint_set(left, "work_ids")
    right_works = _fingerprint_set(right, "work_ids")
    shared_works, work_containment = _containment(left_works, right_works)
    left_coauthors = _fingerprint_set(left, "coauthor_ids") - candidate_ids
    right_coauthors = _fingerprint_set(right, "coauthor_ids") - candidate_ids
    shared_coauthors, coauthor_containment = _containment(left_coauthors, right_coauthors)
    shared_topics, topic_containment = _containment(
        _fingerprint_set(left, "topic_ids"),
        _fingerprint_set(right, "topic_ids"),
    )
    evidence = {
        "sharedInstitutions": len(institutions),
        "institutionContainment": round(institution_containment, 3),
        "compactInstitutionHistory": compact_institution_history,
        "sharedWorks": shared_works,
        "sharedCoauthors": shared_coauthors,
        "coauthorContainment": round(coauthor_containment, 3),
        "sharedTopics": shared_topics,
        "topicContainment": round(topic_containment, 3),
        "orcidConflict": bool(left_orcid and right_orcid and left_orcid != right_orcid),
    }

    if shared_works >= 2 and work_containment >= 0.25 and (institutions or shared_coauthors >= 2):
        return {"merge": True, "confidence": "high", "reason": "shared_works", **evidence}
    if evidence["orcidConflict"]:
        return {
            "merge": False,
            "confidence": "low",
            "reason": "orcid_conflict",
            **evidence,
        }

    strong_context = (
        bool(institutions)
        and compact_institution_history
        and shared_coauthors >= 3
        and shared_topics >= 2
        and (
            (coauthor_containment >= 0.40 and topic_containment >= 0.35)
            or (coauthor_containment >= 0.25 and topic_containment >= 0.45)
        )
    )
    small_split = (
        bool(institutions)
        and compact_institution_history
        and min(int(left.get("works_count") or 0), int(right.get("works_count") or 0)) <= 3
        and shared_coauthors >= 2
        and coauthor_containment >= 0.50
        and shared_topics >= 1
    )
    should_merge = strong_context or small_split
    return {
        "merge": should_merge,
        "confidence": "high" if strong_context else "medium" if small_split else "low",
        "reason": "shared_context" if strong_context else "small_split_profile" if small_split else "insufficient_evidence",
        **evidence,
    }


def _merge_affiliation_records(profiles: list[dict]) -> list[dict]:
    """Merge identical OpenAlex affiliation records without changing identity rules."""
    affiliations_by_key = {}
    for profile in profiles:
        for affiliation in profile.get("affiliations") or []:
            institution = affiliation.get("institution") or {}
            name = str(institution.get("display_name") or "").strip()
            if not name:
                continue
            key = str(institution.get("id") or name).strip().casefold()
            merged = affiliations_by_key.setdefault(
                key,
                {"institution": deepcopy(institution), "years": set()},
            )
            for year in affiliation.get("years") or []:
                try:
                    merged["years"].add(int(year))
                except (TypeError, ValueError):
                    continue
    return [
        {
            "institution": item["institution"],
            "years": sorted(item["years"], reverse=True),
        }
        for item in affiliations_by_key.values()
    ]


def _combine_author_group(group: list[dict], matches: list[dict]) -> dict:
    primary = dict(max(group, key=lambda item: (
        int(item.get("cited_by_count") or 0),
        int(item.get("works_count") or 0),
    )))
    unique_by_id = {}
    for author in group:
        unique_by_id.setdefault(author.get("id") or f"missing-{len(unique_by_id)}", author)
    unique_group = list(unique_by_id.values())
    primary_id = primary.get("id")
    ordered_ids = [primary_id] if primary_id else []
    ordered_ids.extend(
        author.get("id") for author in unique_group
        if author.get("id") and author.get("id") != primary_id
    )
    institutions = []
    for item in unique_group:
        for institution in item.get("last_known_institutions") or []:
            name = str(institution.get("display_name") or "").strip()
            if name and name not in institutions:
                institutions.append(name)
        for affiliation in item.get("affiliations") or []:
            institution = affiliation.get("institution") or {}
            name = str(institution.get("display_name") or "").strip()
            if name and name not in institutions:
                institutions.append(name)
    h_indices = [int((item.get("summary_stats") or {}).get("h_index") or 0) for item in unique_group]
    primary["works_count"] = sum(int(item.get("works_count") or 0) for item in unique_group)
    primary["cited_by_count"] = sum(int(item.get("cited_by_count") or 0) for item in unique_group)
    primary["summary_stats"] = {**(primary.get("summary_stats") or {}), "h_index": max(h_indices, default=0)}
    primary["institutions"] = institutions
    primary["affiliations"] = _merge_affiliation_records(unique_group)
    primary_institution = select_primary_affiliation(primary["affiliations"])
    if not primary_institution:
        primary_institution = institutions[0] if institutions else ""
    primary["primary_institution"] = primary_institution
    primary["other_institutions"] = [
        institution for institution in institutions if institution != primary_institution
    ]
    primary["merged_ids"] = ordered_ids
    primary["merged_count"] = len(ordered_ids)
    primary["identity_confidence"] = (
        "high" if matches and all(match.get("confidence") == "high" for match in matches)
        else "medium" if matches
        else "single"
    )
    primary["identity_signals"] = matches
    primary["disambiguation"] = ""
    return primary


def dedup_authors(candidates):
    """按多信号保守聚类拆分档案；证据不足的同名作者保持分开。"""
    exact_groups = defaultdict(list)
    for index, author in enumerate(candidates):
        exact_groups[author.get("id") or f"__missing_id_{index}"].append(author)
    unique = []
    for exact_group in exact_groups.values():
        unique.append(max(exact_group, key=lambda item: int(item.get("works_count") or 0)))

    candidate_ids = {str(author.get("id")) for author in unique if author.get("id")}
    assigned = set()
    result = []
    for index, primary in enumerate(unique):
        if index in assigned:
            continue
        group = [primary]
        matches = []
        assigned.add(index)
        for candidate_index in range(index + 1, len(unique)):
            if candidate_index in assigned:
                continue
            match = _identity_match(primary, unique[candidate_index], candidate_ids)
            if match.get("merge"):
                group.append(unique[candidate_index])
                matches.append({"authorId": unique[candidate_index].get("id"), **match})
                assigned.add(candidate_index)
        result.append(_combine_author_group(group, matches))
    return result


def fetch_author_profile(state: ScholarProfileState) -> dict:
    """获取并验证候选身份组，合并基础信息但保留主 OpenAlex ID。"""
    from openalex import (
        enrich_authors_for_disambiguation,
        get_author,
        get_provisional_author_bundle,
        is_provisional_author_id,
    )

    primary_id = state["target_author_id"]
    api_key = state["openalex_api_key"]
    budget_provider = state["openalex_budget_provider"]
    if is_provisional_author_id(primary_id):
        profile, provisional_works = get_provisional_author_bundle(
            primary_id,
            api_key=api_key,
            budget_provider=budget_provider,
        )
        profile["merged_author_ids"] = [primary_id]
        return {
            "target_author_ids": [primary_id],
            "target_author_profile": profile,
            "provisional_works": provisional_works,
            "identity_audit": {
                "primaryAuthorId": primary_id,
                "requestedAuthorIds": [primary_id],
                "mergedAuthorIds": [primary_id],
                "rejectedAuthorIds": [],
                "mergedCount": 1,
                "resolutionMethod": "publication_anchor",
                "provisional": True,
                "anchor": profile.get("provisional_anchor") or {},
            },
        }
    requested_ids = list(dict.fromkeys([primary_id, *(state.get("target_author_ids") or [])]))[:8]
    profiles = [
        get_author(
            author_id,
            api_key=api_key,
            budget_provider=budget_provider,
        )
        for author_id in requested_ids
    ]
    valid_ids = [primary_id]
    if len(profiles) > 1:
        groups = dedup_authors(
            enrich_authors_for_disambiguation(
                profiles,
                api_key=api_key,
                budget_provider=budget_provider,
            )
        )
        selected = next(
            (group for group in groups if primary_id in (group.get("merged_ids") or [])),
            None,
        )
        if selected:
            valid_ids = selected.get("merged_ids") or valid_ids
    valid_profiles = [profile for profile in profiles if profile.get("id") in valid_ids]
    primary = deepcopy(next(
        (profile for profile in valid_profiles if profile.get("id") == primary_id),
        valid_profiles[0],
    ))
    institutions = []
    alternatives = []
    for profile in valid_profiles:
        for institution in profile.get("last_known_institutions") or []:
            key = institution.get("id") or _normalized_title(institution.get("display_name"))
            if key and all((item.get("id") or _normalized_title(item.get("display_name"))) != key for item in institutions):
                institutions.append(institution)
        for name in [profile.get("display_name"), *(profile.get("display_name_alternatives") or [])]:
            if name and name not in alternatives:
                alternatives.append(name)
    primary["works_count"] = sum(int(profile.get("works_count") or 0) for profile in valid_profiles)
    primary["last_known_institutions"] = institutions
    primary["affiliations"] = _merge_affiliation_records(valid_profiles)
    primary["display_name_alternatives"] = alternatives
    primary["merged_author_ids"] = valid_ids
    audit = {
        "primaryAuthorId": primary_id,
        "requestedAuthorIds": requested_ids,
        "mergedAuthorIds": valid_ids,
        "rejectedAuthorIds": [author_id for author_id in requested_ids if author_id not in valid_ids],
        "mergedCount": len(valid_ids),
    }
    return {
        "target_author_ids": valid_ids,
        "target_author_profile": primary,
        "identity_audit": audit,
    }


# ── 阶段二: 论文获取与去重 ──────────────────────────────────

def _work_identity_signals(work: dict, primary_author_id: str) -> dict[str, set[str]]:
    institutions = set()
    coauthors = set()
    for authorship in work.get("authorships") or []:
        author_id = str((authorship.get("author") or {}).get("id") or "")
        if author_id == primary_author_id:
            for institution in authorship.get("institutions") or []:
                key = institution.get("id") or _normalized_title(institution.get("display_name"))
                if key:
                    institutions.add(_normalized_title(str(key)))
        elif author_id:
            coauthors.add(author_id)
    topics = set()
    primary_topic = work.get("primary_topic") or {}
    if primary_topic.get("id"):
        topics.add(str(primary_topic["id"]))
    for topic in work.get("topics") or []:
        if topic.get("id"):
            topics.add(str(topic["id"]))
    return {"institutions": institutions, "coauthors": coauthors, "topics": topics}


def _identity_work_key(work: dict) -> tuple[str, str, int | None]:
    from crossref import normalize_doi

    doi = normalize_doi(work.get("doi"))
    title = _normalized_title(work.get("title"))
    try:
        year = int(work.get("publication_year") or work.get("year") or 0) or None
    except (TypeError, ValueError):
        year = None
    return doi, title, year


def _identity_components(
    works: list[dict],
    signals: list[dict[str, set[str]]],
) -> list[set[int]]:
    work_keys = [_identity_work_key(work) for work in works]

    def strongly_linked(left: int, right: int) -> bool:
        left_key = work_keys[left]
        right_key = work_keys[right]
        same_doi = bool(left_key[0] and left_key[0] == right_key[0])
        same_title = bool(
            left_key[1]
            and left_key[1] == right_key[1]
            and (
                left_key[2] is None
                or right_key[2] is None
                or left_key[2] == right_key[2]
            )
        )
        stable_coauthor = bool(
            signals[left]["coauthors"] & signals[right]["coauthors"]
        )
        return same_doi or same_title or stable_coauthor

    remaining = set(range(len(signals)))
    components: list[set[int]] = []
    while remaining:
        component = {remaining.pop()}
        frontier = list(component)
        while frontier:
            current = frontier.pop()
            linked = {
                candidate
                for candidate in remaining
                if strongly_linked(current, candidate)
            }
            if linked:
                component.update(linked)
                remaining.difference_update(linked)
                frontier.extend(linked)
        components.append(component)
    return components


def _cluster_summary(component: set[int], works: list[dict], signals: list[dict]) -> dict:
    years = sorted({
        int(works[index].get("publication_year"))
        for index in component
        if works[index].get("publication_year")
    })
    topic_counts = defaultdict(int)
    for index in component:
        for topic in works[index].get("topics") or []:
            name = str(topic.get("display_name") or "").strip()
            if name:
                topic_counts[name] += 1
    return {
        "workCount": len(component),
        "yearStart": years[0] if years else None,
        "yearEnd": years[-1] if years else None,
        "topTopics": [
            name
            for name, _count in sorted(
                topic_counts.items(),
                key=lambda item: (-item[1], item[0]),
            )[:3]
        ],
    }


def _filter_identity_outlier_works(
    works: list[dict],
    primary_author_id: str,
    *,
    orcid_works: list[dict] | None = None,
    target_institution_ids: set[str] | None = None,
) -> tuple[list[dict], dict]:
    """使用 ORCID、机构和合作者选择主论文簇；主题相似度不作为身份连接。"""
    if not works:
        return [], {
            "resolutionMethod": "insufficient_evidence",
            "collectedWorks": 0,
            "orcidMatchedWorks": 0,
            "excludedWorks": 0,
            "excludedWorkIds": [],
            "excludedClusters": [],
            "largeConflictWorks": 0,
            "possibleConflatedIdentity": False,
        }
    signals = [_work_identity_signals(work, primary_author_id) for work in works]
    components = _identity_components(works, signals)
    component_by_index = {
        index: component
        for component in components
        for index in component
    }
    anchor_keys = {_identity_work_key(work) for work in (orcid_works or [])}
    anchor_indices = {
        index
        for index, work in enumerate(works)
        if (
            _identity_work_key(work) in anchor_keys
            or (
                _identity_work_key(work)[0]
                and any(_identity_work_key(work)[0] == key[0] for key in anchor_keys if key[0])
            )
        )
    }
    if anchor_indices:
        kept_indices = set(anchor_indices)
        for index in anchor_indices:
            kept_indices.update(component_by_index[index])
        resolution_method = "orcid_anchor"
    else:
        target_institutions = {
            _normalized_title(value)
            for value in (target_institution_ids or set())
            if _normalized_title(value)
        }
        latest_year = max(
            (int(work.get("publication_year") or 0) for work in works),
            default=0,
        )

        def component_score(component: set[int]) -> tuple[int, int, int, int]:
            institution_matches = sum(
                bool(signals[index]["institutions"] & target_institutions)
                for index in component
            )
            stable_collaboration = sum(
                len(signals[index]["coauthors"])
                for index in component
            )
            recent = sum(
                int(works[index].get("publication_year") or 0) >= latest_year - 5
                for index in component
            )
            return institution_matches, stable_collaboration, recent, len(component)

        primary_component = max(components, key=component_score)
        has_identity_evidence = bool(
            target_institutions
            or any(len(component) >= 3 for component in components)
        )
        if len(works) < 20 and not has_identity_evidence:
            kept_indices = set(range(len(works)))
            resolution_method = "insufficient_evidence"
        else:
            kept_indices = set(primary_component)
            resolution_method = "institution_collaborator_cluster"

    excluded_indices = set(range(len(works))) - kept_indices
    kept = [work for index, work in enumerate(works) if index not in excluded_indices]
    excluded_ids = [
        str(works[index].get("id") or works[index].get("doi") or f"work-{index}")
        for index in sorted(excluded_indices)
    ]
    excluded_components = [
        component & excluded_indices
        for component in components
        if component & excluded_indices
    ]
    excluded_summaries = sorted(
        (
            _cluster_summary(component, works, signals)
            for component in excluded_components
        ),
        key=lambda item: -item["workCount"],
    )
    return kept, {
        "resolutionMethod": resolution_method,
        "collectedWorks": len(works),
        "orcidMatchedWorks": len(anchor_indices),
        "excludedWorks": len(excluded_indices),
        "excludedWorkIds": excluded_ids[:50],
        "excludedClusters": excluded_summaries[:10],
        "largeConflictWorks": sum(
            item["workCount"]
            for item in excluded_summaries
            if item["workCount"] >= max(5, math.ceil(len(works) * 0.1))
        ),
        "possibleConflatedIdentity": bool(excluded_indices),
    }


def collect_orcid_identity(state: ScholarProfileState) -> dict:
    """读取无需密钥的 ORCID 公共论文记录，失败时正常降级。"""
    from orcid import get_public_works

    profile = state.get("target_author_profile") or {}
    works, audit = get_public_works(profile.get("orcid"))
    warnings = []
    if profile.get("orcid") and audit.get("status") != "available":
        warnings.append("ORCID 公共论文记录暂时不可用，身份核验已降级为机构与合作者证据")
    return {
        "orcid_works": works,
        "orcid_audit": audit,
        "warnings": warnings,
    }

def collect_works(state: ScholarProfileState) -> dict:
    """并发获取同一身份组的全部论文，并把中心作者统一到主 ID。"""
    from openalex import get_works, is_provisional_author_id
    warnings = []
    works_complete = True
    primary_id = state["target_author_id"]
    api_key = state["openalex_api_key"]
    budget_provider = state["openalex_budget_provider"]
    author_ids = state.get("target_author_ids") or [primary_id]
    works = []
    if is_provisional_author_id(primary_id):
        works = deepcopy(state.get("provisional_works") or [])
        return {
            "raw_works": works,
            "source_works": {"openalex": works},
            "works_complete": bool(works),
            "warnings": (
                []
                if works
                else ["论文锚点候选暂未取得可用于画像的论文记录"]
            ),
        }
    with ThreadPoolExecutor(max_workers=min(6, len(author_ids))) as executor:
        futures = {
            executor.submit(
                get_works,
                author_id,
                api_key=api_key,
                budget_provider=budget_provider,
            ): author_id
            for author_id in author_ids
        }
        for future in as_completed(futures):
            author_id = futures[future]
            try:
                author_works, fetch_warnings = future.result()
                warnings.extend(fetch_warnings)
                if fetch_warnings:
                    works_complete = False
                for source_work in author_works:
                    work = deepcopy(source_work)
                    canonical_authorships = []
                    seen_authors = set()
                    for authorship in work.get("authorships") or []:
                        author = dict(authorship.get("author") or {})
                        source_id = author.get("id")
                        if source_id in author_ids:
                            author["source_id"] = source_id
                            author["id"] = primary_id
                            author["display_name"] = (state.get("target_author_profile") or {}).get("display_name", author.get("display_name", ""))
                        if author.get("id") in seen_authors:
                            continue
                        seen_authors.add(author.get("id"))
                        canonical_authorships.append({**authorship, "author": author})
                    work["authorships"] = canonical_authorships
                    work["source_author_id"] = author_id
                    works.append(work)
            except Exception as exc:
                works_complete = False
                warnings.append(f"OpenAlex 作者档案 {author_id} 论文获取失败: {exc}")
    if state["target_author_profile"]:
        expected = state["target_author_profile"].get("works_count", 0)
        if len(works) < expected:
            warnings.append(f"预期 {expected} 篇，实际获取 {len(works)} 篇（OpenAlex 限制）")
    return {
        "raw_works": works,
        "source_works": {"openalex": works},
        "works_complete": works_complete,
        "warnings": warnings,
    }




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


def collect_crossref_records(state: ScholarProfileState) -> dict:
    """按 DOI 核验 Crossref 出版元数据，不按姓名扩张论文列表。"""
    from crossref import normalize_doi, verify_dois

    works = state.get("deduped_works") or state.get("raw_works") or []
    all_dois = list(dict.fromkeys(
        doi for doi in (normalize_doi(work.get("doi")) for work in works) if doi
    ))
    requested_dois = all_dois[:CROSSREF_VERIFICATION_LIMIT]
    records, report = verify_dois(requested_dois)
    source_works = dict(state.get("source_works") or {})
    source_works.setdefault("openalex", state.get("raw_works") or works)
    source_works["crossref"] = list(records.values())
    audit = {
        **report,
        "available_dois": len(all_dois),
        "limited": len(all_dois) > len(requested_dois),
    }
    warnings = []
    if report["failed"]:
        warnings.append(f"Crossref 有 {report['failed']} 个 DOI 暂时无法核验")
    if audit["limited"]:
        warnings.append(
            f"Crossref 本次核验前 {len(requested_dois)} 个 DOI，另有 {len(all_dois) - len(requested_dois)} 个待后续核验"
        )
    return {"source_works": source_works, "source_audit": audit, "warnings": warnings}


def collect_dblp_records(state: ScholarProfileState) -> dict:
    """用 DBLP 核验已有论文，不按姓名扩张论文列表。"""
    from dblp import verify_author_works

    works = state.get("deduped_works") or state.get("raw_works") or []
    records, report = verify_author_works(state.get("target_author_profile") or {}, works)
    source_works = dict(state.get("source_works") or {})
    source_works["dblp"] = records
    source_audit = dict(state.get("source_audit") or {})
    source_audit["dblp"] = report
    warnings = []
    if report.get("status") == "unavailable":
        warnings.append("DBLP 暂时不可用，已继续使用其他来源")
    return {"source_works": source_works, "source_audit": source_audit, "warnings": warnings}


def collect_google_scholar_records(state: ScholarProfileState) -> dict:
    """可选地通过 SerpApi 核验 Google Scholar 记录。"""
    from google_scholar import verify_author_works

    works = state.get("deduped_works") or state.get("raw_works") or []
    records, report = verify_author_works(state.get("target_author_profile") or {}, works)
    source_works = dict(state.get("source_works") or {})
    source_works["google_scholar"] = records
    source_audit = dict(state.get("source_audit") or {})
    source_audit["google_scholar"] = report
    warnings = []
    if report.get("status") == "unavailable":
        warnings.append("Google Scholar 核验暂时不可用，已继续使用其他来源")
    return {"source_works": source_works, "source_audit": source_audit, "warnings": warnings}


def _normalized_title(value: str | None) -> str:
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", " ", str(value or "").casefold()).strip()


def _work_journal(work: dict) -> str:
    return str(
        work.get("adjudicated_journal")
        or ((work.get("primary_location") or {}).get("source") or {}).get("display_name", "")
    )


def _analysis_works(state: ScholarProfileState) -> list[dict]:
    return state.get("adjudicated_works") or state.get("deduped_works") or []


def adjudicate_sources(state: ScholarProfileState) -> dict:
    """以 DOI 为首要标识合并来源，保留字段来源、冲突与核验状态。"""
    from crossref import normalize_doi

    openalex_works = state.get("deduped_works") or []
    crossref_records = {
        normalize_doi(record.get("doi")): record
        for record in (state.get("source_works") or {}).get("crossref", [])
        if normalize_doi(record.get("doi"))
    }
    dblp_records = list((state.get("source_works") or {}).get("dblp", []))
    scholar_records = list((state.get("source_works") or {}).get("google_scholar", []))

    def source_lookup(records: list[dict]) -> tuple[dict[str, dict], dict[tuple[str, int], dict]]:
        by_doi = {
            normalize_doi(record.get("doi")): record
            for record in records
            if normalize_doi(record.get("doi"))
        }
        by_title_year = {
            (_normalized_title(record.get("title")), int(record.get("publication_year") or 0)): record
            for record in records
            if _normalized_title(record.get("title"))
        }
        return by_doi, by_title_year

    dblp_by_doi, dblp_by_title_year = source_lookup(dblp_records)
    scholar_by_doi, scholar_by_title_year = source_lookup(scholar_records)
    adjudicated = []
    conflicts = []
    verified = 0
    multi_source_verified = 0
    works_with_doi = 0

    for source_work in openalex_works:
        work = deepcopy(source_work)
        doi = normalize_doi(work.get("doi"))
        source_records = [{
            "source": "openalex",
            "id": work.get("id", ""),
            "url": work.get("id", ""),
        }]
        field_sources = {
            "title": "openalex",
            "publicationYear": "openalex",
            "citations": "openalex",
            "authorships": "openalex",
            "topics": "openalex",
        }
        work_conflicts = []
        crossref_record = crossref_records.get(doi) if doi else None
        title_year = (
            _normalized_title(work.get("title")),
            int(work.get("publication_year") or 0),
        )
        dblp_record = (dblp_by_doi.get(doi) if doi else None) or dblp_by_title_year.get(title_year)
        scholar_record = (scholar_by_doi.get(doi) if doi else None) or scholar_by_title_year.get(title_year)
        if doi:
            works_with_doi += 1
            work["doi"] = f"https://doi.org/{doi}"
        if crossref_record:
            verified += 1
            source_records.append({
                "source": "crossref",
                "id": doi,
                "url": f"https://doi.org/{doi}",
            })
            crossref_title = str(crossref_record.get("title") or "").strip()
            openalex_title = str(work.get("title") or "").strip()
            if crossref_title:
                if openalex_title and _normalized_title(crossref_title) != _normalized_title(openalex_title):
                    work_conflicts.append({
                        "field": "title",
                        "openalex": openalex_title,
                        "crossref": crossref_title,
                    })
                work["title"] = crossref_title
                field_sources["title"] = "crossref"
            crossref_year = crossref_record.get("publication_year")
            openalex_year = work.get("publication_year")
            if crossref_year:
                if openalex_year and int(crossref_year) != int(openalex_year):
                    work_conflicts.append({
                        "field": "publication_year",
                        "openalex": openalex_year,
                        "crossref": crossref_year,
                    })
                work["publication_year"] = int(crossref_year)
                field_sources["publicationYear"] = "crossref"
            if crossref_record.get("journal"):
                work["adjudicated_journal"] = crossref_record["journal"]
                field_sources["journal"] = "crossref"
            work["crossref"] = crossref_record
        if dblp_record:
            source_records.append({
                "source": "dblp",
                "id": dblp_record.get("id", ""),
                "url": dblp_record.get("url", ""),
            })
            if dblp_record.get("journal") and not _work_journal(work):
                work["adjudicated_journal"] = dblp_record["journal"]
                field_sources["journal"] = "dblp"
            work["dblp"] = dblp_record
        if scholar_record:
            source_records.append({
                "source": "google_scholar",
                "id": scholar_record.get("id", ""),
                "url": scholar_record.get("url", ""),
            })
            work["google_scholar"] = scholar_record

        if crossref_record or dblp_record or scholar_record:
            multi_source_verified += 1
            work["verification_status"] = "verified"
        else:
            work["verification_status"] = "doi_unverified" if doi else "no_doi"

        for conflict in work_conflicts:
            conflicts.append({"workId": work.get("id", ""), "doi": doi, **conflict})
        work["source_records"] = source_records
        work["field_sources"] = field_sources
        work["conflicts"] = work_conflicts
        adjudicated.append(work)

    source_audit = state.get("source_audit") or {}
    dblp_audit = source_audit.get("dblp") or {}
    scholar_audit = source_audit.get("google_scholar") or {}
    total = len(adjudicated)
    verification_ratio = verified / total if total else 0
    multi_source_ratio = multi_source_verified / total if total else 0
    if not state.get("works_complete", False) or source_audit.get("failed"):
        status = "attention"
    elif multi_source_ratio >= 0.7:
        status = "sufficient"
    elif multi_source_verified:
        status = "partial"
    else:
        status = "attention"
    expected = int((state.get("target_author_profile") or {}).get("works_count") or 0)
    sources = ["OpenAlex", "Crossref"]
    if dblp_audit.get("status") == "available":
        sources.append("DBLP")
    if scholar_audit.get("status") == "available":
        sources.append("Google Scholar")
    data_audit = {
        "status": status,
        "sources": sources,
        "openalexExpected": expected,
        "openalexFetched": len(state.get("raw_works") or []),
        "collectedWorks": total,
        "worksWithDoi": works_with_doi,
        "crossrefRequested": int(source_audit.get("requested") or 0),
        "crossrefVerified": verified,
        "crossrefMissing": int(source_audit.get("missing") or 0),
        "crossrefFailed": int(source_audit.get("failed") or 0),
        "crossrefLimited": bool(source_audit.get("limited")),
        "dblpStatus": str(dblp_audit.get("status") or "not_applicable"),
        "dblpMatched": int(dblp_audit.get("matched") or 0),
        "googleScholarStatus": str(scholar_audit.get("status") or "disabled"),
        "googleScholarMatched": int(scholar_audit.get("matched") or 0),
        "multiSourceVerified": multi_source_verified,
        "unverifiedWorks": max(0, total - multi_source_verified),
        "duplicateRecordsMerged": max(0, len(state.get("raw_works") or []) - total),
        "conflictCount": len(conflicts),
        "conflicts": conflicts[:20],
        "worksComplete": bool(state.get("works_complete")),
        "verifiedRatio": round(verification_ratio, 4),
        "multiSourceRatio": round(multi_source_ratio, 4),
        "retrievedAt": datetime.now(timezone.utc).isoformat(),
    }
    return {
        "adjudicated_works": adjudicated,
        "deduped_works": adjudicated,
        "data_audit": data_audit,
    }


def resolve_work_identity(state: ScholarProfileState) -> dict:
    """在来源裁决后执行准确优先的论文归属判断。"""
    from orcid import normalize_orcid

    works = state.get("adjudicated_works") or []
    profile = state.get("target_author_profile") or {}
    target_orcid = normalize_orcid(profile.get("orcid"))
    orcid_works = list(state.get("orcid_works") or [])
    for work in works:
        crossref = work.get("crossref") or {}
        authors = (crossref.get("raw") or {}).get("author") or []
        if target_orcid and any(
            normalize_orcid(author.get("ORCID")) == target_orcid
            for author in authors
        ):
            orcid_works.append({
                "doi": work.get("doi"),
                "title": work.get("title"),
                "year": work.get("publication_year"),
            })
    target_institution_ids = {
        str(institution.get("id") or institution.get("display_name") or "")
        for institution in profile.get("last_known_institutions") or []
        if institution.get("id") or institution.get("display_name")
    }
    kept, audit = _filter_identity_outlier_works(
        works,
        str(state.get("target_author_id") or ""),
        orcid_works=orcid_works,
        target_institution_ids=target_institution_ids,
    )
    identity_audit = {
        **(state.get("identity_audit") or {}),
        **audit,
        "orcidStatus": (state.get("orcid_audit") or {}).get("status", "unavailable"),
    }
    kept_with_doi = sum(bool(work.get("doi")) for work in kept)
    kept_verified = sum(bool(work.get("crossref")) for work in kept)
    kept_multi_source_verified = sum(work.get("verification_status") == "verified" for work in kept)
    audit_sources = list((state.get("data_audit") or {}).get("sources") or [])
    if (state.get("orcid_audit") or {}).get("status") == "available" and "ORCID" not in audit_sources:
        audit_sources.append("ORCID")
    data_audit = {
        **(state.get("data_audit") or {}),
        "status": (
            "attention"
            if audit["excludedWorks"]
            else (state.get("data_audit") or {}).get("status", "attention")
        ),
        "sources": audit_sources,
        "collectedWorks": len(kept),
        "worksWithDoi": kept_with_doi,
        "crossrefVerified": kept_verified,
        "multiSourceVerified": kept_multi_source_verified,
        "unverifiedWorks": max(0, len(kept) - kept_multi_source_verified),
        "verifiedRatio": round(kept_verified / len(kept), 4) if kept else 0,
        "multiSourceRatio": (
            round(kept_multi_source_verified / len(kept), 4)
            if kept else 0
        ),
        "identityExcludedWorks": audit["excludedWorks"],
    }
    warnings = []
    if audit["excludedWorks"]:
        warnings.append(
            f"身份核验保守排除 {audit['excludedWorks']} 篇与主身份缺少 ORCID、机构或合作者连接的论文；画像可能不完整"
        )
    return {
        "deduped_works": kept,
        "adjudicated_works": kept,
        "identity_audit": identity_audit,
        "data_audit": data_audit,
        "warnings": warnings,
    }


# ── 阶段三: 并行分析 ────────────────────────────────────────

def analyze_citations(state: ScholarProfileState) -> dict:
    """统计总论文数、总引用数、h-index、年度趋势。"""
    works = _analysis_works(state)
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

def plan_agent_analysis(state: ScholarProfileState) -> dict:
    """由路由 Agent 根据本次数据复杂度规划下游模型。"""
    from llm import plan_agents

    works = _analysis_works(state)
    years = {int(work.get("publication_year") or 0) for work in works if work.get("publication_year")}
    candidate_topics = {
        _topic_key(topic.get("display_name", ""))
        for work in works
        for topic in (work.get("topics") or [])
        if topic.get("display_name")
    }
    audit = state.get("data_audit") or {}
    identity = state.get("identity_audit") or {}
    context = {
        "paper_count": len(works),
        "active_years": len(years),
        "source_conflicts": int(audit.get("conflictCount") or 0),
        "crossref_verified": int(audit.get("crossrefVerified") or 0),
        "works_complete": bool(state.get("works_complete")),
        "identity_risk": bool(
            identity.get("possibleConflatedIdentity")
            or identity.get("largeConflictWorks")
            or identity.get("rejectedAuthorIds")
        ),
        "broad_topic_span": len(candidate_topics) >= 18,
    }
    plan, trace = plan_agents(context)
    return {
        "agent_plan": plan.model_dump(),
        "agent_runs": [trace],
    }

_BROAD_TOPIC_LABELS = {
    "agricultural and biological sciences", "agriculture", "artificial intelligence",
    "arts and humanities", "biochemistry", "biology", "business", "chemistry",
    "computer science", "data science", "earth and planetary sciences", "economics",
    "engineering", "environmental science", "health sciences", "humanities",
    "information technology", "life sciences", "materials science", "mathematics",
    "medicine", "multidisciplinary", "neuroscience", "nursing", "pharmacology",
    "physics", "psychology", "social science", "social sciences",
}
_MID_LEVEL_TOPIC_LABELS = {
    "data mining", "information retrieval", "machine learning", "natural language processing",
    "world wide web", "database", "deep learning", "information system",
}
_TITLE_STOPWORDS = {
    "a", "an", "and", "as", "at", "by", "for", "from", "in", "into", "of", "on",
    "or", "over", "the", "through", "to", "toward", "towards", "using", "via", "with",
}
_TITLE_EDGE_WORDS = {
    "analysis", "approach", "based", "case", "challenges", "comparison", "enhanced",
    "evaluation", "framework", "method", "methods", "modeling", "new", "perspective",
    "review", "study", "survey", "system", "systems", "technique", "techniques",
}


def _topic_key(value: str) -> str:
    tokens = re.findall(r"[a-z0-9]+", str(value or "").casefold())
    normalized = []
    for token in tokens:
        if len(token) > 4 and token.endswith("ies"):
            token = token[:-3] + "y"
        elif len(token) > 4 and token.endswith("s") and not token.endswith("ss"):
            token = token[:-1]
        normalized.append(token)
    return " ".join(normalized)


def _topic_is_specific(value: str) -> bool:
    key = _topic_key(value)
    return bool(key and key not in _BROAD_TOPIC_LABELS and len(key) >= 3)


def _title_phrases(title: str) -> set[str]:
    tokens = re.findall(r"[a-z0-9]+", str(title or "").casefold())
    phrases = set()
    for size in range(2, 5):
        for start in range(0, len(tokens) - size + 1):
            phrase_tokens = tokens[start:start + size]
            if any(token in _TITLE_STOPWORDS for token in phrase_tokens):
                continue
            if phrase_tokens[0] in _TITLE_EDGE_WORDS or phrase_tokens[-1] in _TITLE_EDGE_WORDS:
                continue
            key = _topic_key(" ".join(phrase_tokens))
            if _topic_is_specific(key):
                phrases.add(key)
    return phrases


def _topic_display_name(key: str, preferred: str = "") -> str:
    if preferred and _topic_key(preferred) == key:
        return preferred.strip()
    acronyms = {"ai", "dna", "gnn", "llm", "nlp", "rdf", "rna", "sparql"}
    return " ".join(token.upper() if token in acronyms else token.capitalize() for token in key.split())


def _representative_papers(works: list, clusters: list[dict]) -> dict:
    representative = {}
    for cluster in clusters:
        indices = cluster["paper_indices"]
        sorted_indices = sorted(indices, key=lambda index: -(works[index].get("cited_by_count") or 0))
        items = []
        for index in sorted_indices[:3]:
            work = works[index]
            items.append({
                "title": work.get("title", ""),
                "year": work.get("publication_year"),
                "citations": work.get("cited_by_count", 0),
                "journal": _work_journal(work),
                "doi": work.get("doi", ""),
                "id": work.get("id", ""),
                "sources": [
                    record.get("source")
                    for record in work.get("source_records") or []
                    if record.get("source")
                ],
            })
        representative[cluster["topic"]] = items
    return representative

def _fallback_topic_analysis(works: list) -> dict:
    """融合 OpenAlex topics/keywords 与标题短语，优先输出细粒度方向。"""
    if not works:
        return {"topic_clusters": [], "representative_papers": {}}
    candidates = defaultdict(lambda: {
        "score": 0.0,
        "paper_indices": set(),
        "preferred": "",
        "sources": set(),
    })
    max_year = max((int(work.get("publication_year") or 0) for work in works), default=0)
    title_phrase_indices = defaultdict(set)
    normalized_titles = []
    for index, work in enumerate(works):
        normalized_title = _topic_key(work.get("title", ""))
        normalized_titles.append(normalized_title)
        for phrase in _title_phrases(work.get("title", "")):
            title_phrase_indices[phrase].add(index)

    def add_candidate(name: str, index: int, score: float, source: str) -> None:
        if not _topic_is_specific(name):
            return
        key = _topic_key(name)
        if key in _MID_LEVEL_TOPIC_LABELS:
            score *= 0.28
        elif any(key.startswith(f"{label} ") for label in _MID_LEVEL_TOPIC_LABELS):
            score *= 0.55
        item = candidates[key]
        item["score"] += score
        item["paper_indices"].add(index)
        item["sources"].add(source)
        if source in {"keyword", "openalex_topic"} or (source == "concept" and not item["preferred"]):
            item["preferred"] = str(name).strip()

    keyword_occurrences = defaultdict(set)
    for index, work in enumerate(works):
        for keyword in work.get("keywords") or []:
            name = keyword.get("display_name", "")
            if _topic_is_specific(name):
                keyword_occurrences[_topic_key(name)].add(index)

    for index, work in enumerate(works):
        year = int(work.get("publication_year") or 0)
        recency = 1.0 + (0.35 * max(0, year - (max_year - 5)) / 5 if max_year and year else 0)
        citation = 1.0 + min(math.log1p(int(work.get("cited_by_count") or 0)) / 12, 0.45)
        primary = work.get("primary_topic") or {}
        if primary.get("display_name"):
            add_candidate(
                primary["display_name"], index,
                2.2 * float(primary.get("score") or 1) * recency * citation,
                "openalex_topic",
            )
        for topic in work.get("topics") or []:
            if topic.get("display_name"):
                add_candidate(
                    topic["display_name"], index,
                    1.2 * float(topic.get("score") or 1) * recency * citation,
                    "openalex_topic",
                )
        for keyword in work.get("keywords") or []:
            name = keyword.get("display_name", "")
            key = _topic_key(name)
            appears_in_title = bool(key and key in normalized_titles[index])
            if appears_in_title or len(keyword_occurrences[key]) >= 2:
                add_candidate(
                    name, index,
                    2.4 * float(keyword.get("score") or 0.7) * recency * citation,
                    "keyword",
                )
        for concept in work.get("concepts") or []:
            name = concept.get("display_name", "")
            if int(concept.get("level") or 0) >= 2:
                add_candidate(name, index, 0.45 * float(concept.get("score") or 0.5), "concept")

    minimum_phrase_documents = 3
    for phrase, indices in title_phrase_indices.items():
        if len(indices) < minimum_phrase_documents:
            continue
        phrase_score = (2.4 + 0.50 * min(len(phrase.split()), 4)) * len(indices)
        for index in indices:
            add_candidate(phrase, index, phrase_score / len(indices), "title_phrase")

    ranked = sorted(
        candidates.items(),
        key=lambda item: (
            -item[1]["score"],
            -len(item[1]["paper_indices"]),
            -len(item[0].split()),
        ),
    )
    selected = []
    for key, item in ranked:
        indices = set(item["paper_indices"])
        if not indices:
            continue
        key_tokens = set(key.split())
        redundant = False
        for existing in selected:
            existing_tokens = set(existing["key"].split())
            overlap = len(indices & existing["indices"]) / max(1, min(len(indices), len(existing["indices"])))
            if overlap >= 0.70 and (key_tokens <= existing_tokens or existing_tokens <= key_tokens):
                redundant = True
                break
        if redundant:
            continue
        selected.append({"key": key, "indices": indices, **item})
        if len(selected) >= 10:
            break

    total_score = sum(float(item["score"]) for item in selected) or 1.0
    clusters = [{
        "topic": _topic_display_name(item["key"], item["preferred"]),
        "description": "由 OpenAlex 主题、关键词与论文标题共同支持。",
        "weight": round(float(item["score"]) / total_score, 3),
        "score": round(float(item["score"]), 2),
        "paper_indices": sorted(item["indices"]),
        "sources": sorted(item["sources"]),
    } for item in selected]
    return {
        "topic_clusters": clusters,
        "representative_papers": _representative_papers(works, clusters),
    }


def _topic_title_similarity(topic: str, title: str) -> float:
    topic_tokens = set(_topic_key(topic).split())
    title_tokens = set(_topic_key(title).split())
    if not topic_tokens or not title_tokens:
        return 0.0
    return len(topic_tokens & title_tokens) / max(1, min(len(topic_tokens), len(title_tokens)))


def _validate_topic_agent_output(
    output,
    *,
    candidate_names: set[str],
    representative_titles: list[str],
    minimum_directions: int,
) -> list[str]:
    issues = []
    if not minimum_directions <= len(output.directions) <= 10:
        issues.append("topic_count_out_of_range")
    seen_names = set()
    for direction in output.directions:
        key = _topic_key(direction.name)
        word_count = len(key.split())
        if word_count < 2 or word_count > 8:
            issues.append("topic_name_word_count")
        if not _topic_is_specific(direction.name) or key in _MID_LEVEL_TOPIC_LABELS:
            issues.append("broad_topic_label")
        if any(_topic_title_similarity(direction.name, title) >= 0.75 for title in representative_titles):
            issues.append("paper_title_as_topic")
        if key in seen_names:
            issues.append("duplicate_topic_label")
        seen_names.add(key)
        if not direction.source_topics or any(
            source not in candidate_names
            for source in direction.source_topics
        ):
            issues.append("untraceable_source_topic")
        if len(direction.description_zh.strip()) < 8 or len(direction.description_en.strip()) < 12:
            issues.append("topic_description_too_short")
    return list(dict.fromkeys(issues))


def agent_analyze_topics(state: ScholarProfileState) -> dict:
    """使用方向 Agent 重组可追溯候选主题，失败时保留确定性结果。"""
    from llm import TopicAgentOutput, run_structured_agent
    from prompts import AGENT_ANALYZE_TOPICS

    works = _analysis_works(state)
    if not works:
        return {"topic_clusters": [], "representative_papers": {}}
    baseline = _fallback_topic_analysis(works)
    candidates = baseline["topic_clusters"][:12]
    candidate_names = {item["topic"] for item in candidates}
    payload_candidates = []
    for item in candidates:
        ranked_indices = sorted(
            item.get("paper_indices") or [],
            key=lambda index: -(works[index].get("cited_by_count") or 0),
        )
        payload_candidates.append({
            "name": item["topic"],
            "paper_count": len(item.get("paper_indices") or []),
            "sources": item.get("sources") or [],
            "representative_titles": [
                works[index].get("title", "")
                for index in ranked_indices[:3]
                if works[index].get("title")
            ],
        })

    representative_titles = [
        title
        for candidate in payload_candidates
        for title in candidate["representative_titles"]
    ]
    minimum_directions = 1 if len(candidates) <= 2 else 2

    def validate(output: TopicAgentOutput) -> list[str]:
        return _validate_topic_agent_output(
            output,
            candidate_names=candidate_names,
            representative_titles=representative_titles,
            minimum_directions=minimum_directions,
        )

    planned_tier = (state.get("agent_plan") or {}).get("topic_tier", "fast")
    output, trace = run_structured_agent(
        "topic_agent",
        planned_tier=planned_tier,
        system_prompt=AGENT_ANALYZE_TOPICS,
        payload={"candidates": payload_candidates},
        schema=TopicAgentOutput,
        validate=validate,
        temperature=0.2,
        max_tokens=1600,
    )
    if not output:
        return {
            **baseline,
            "agent_runs": [trace],
            "warnings": ["研究方向 Agent 不可用，已使用可追溯规则结果"],
        }

    baseline_by_name = {item["topic"]: item for item in candidates}
    merged = []
    for direction in output.directions:
        source_items = [baseline_by_name[name] for name in direction.source_topics]
        indices = sorted({
            index
            for item in source_items
            for index in (item.get("paper_indices") or [])
        })
        merged.append({
            "topic": direction.name.strip(),
            "description": direction.description_zh.strip(),
            "description_en": direction.description_en.strip(),
            "confidence": direction.confidence,
            "score": round(sum(float(item.get("score") or 0) for item in source_items), 2),
            "paper_indices": indices,
            "sources": sorted({
                source
                for item in source_items
                for source in (item.get("sources") or [])
            }),
            "source_topics": direction.source_topics,
            "agent_generated": True,
        })
    total_score = sum(float(item["score"]) for item in merged) or 1.0
    for item in merged:
        item["weight"] = round(float(item["score"]) / total_score, 3)
    merged.sort(key=lambda item: (-item["weight"], -len(item["paper_indices"])))
    return {
        "topic_clusters": merged,
        "representative_papers": _representative_papers(works, merged),
        "agent_runs": [trace],
    }


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
            for i, w in enumerate(_analysis_works(state)):
                for c in w.get("concepts") or []:
                    if c["display_name"] == name:
                        paper_to_topics[i].append(name)
                        break

    # 按年份统计 topic 出现频次
    yearly = defaultdict(lambda: defaultdict(int))
    for i, w in enumerate(_analysis_works(state)):
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


def _count_only_trajectory_text(value: str) -> bool:
    text = str(value or "").casefold()
    if not re.search(r"\d", text):
        return False
    content_markers = (
        "研究问题", "方法", "应用", "场景", "技术路线", "关注",
        "research problem", "method", "application", "context", "focus", "approach",
    )
    if any(marker in text for marker in content_markers):
        return False
    return bool(
        re.search(r"从\s*\d+\s*篇.*(?:到|至|增加|下降)", text)
        or re.search(
            r"(?:论文|文章)?(?:数|数量|占比|份额)?(?:由|从)\s*"
            r"\d+(?:\.\d+)?\s*(?:篇|%)?.{0,12}"
            r"(?:到|至|增(?:长|加)?至|升至|降至|下降至)\s*"
            r"\d+(?:\.\d+)?\s*(?:篇|%)?",
            text,
        )
        or re.search(r"from\s+\d+\s+(?:papers?|works?).*to\s+\d+", text)
        or re.search(
            r"(?:papers?|works?).{0,20}(?:increased|grew|rose|declined|fell)"
            r"\s+from\s+\d+(?:\.\d+)?(?:%)?\s+to\s+\d+(?:\.\d+)?(?:%)?",
            text,
        )
        or re.search(r"\d+\s*(?:→|->)\s*\d+", text)
    )


def _validate_trajectory_agent_output(
    output,
    *,
    valid_topics: set[str],
    valid_evidence_ids: set[str],
    evidence_by_topic: dict[str, set[str]] | None = None,
) -> list[str]:
    listed = output.emerging + output.rising + output.steady + output.falling
    issues = []
    if any(topic not in valid_topics for topic in listed):
        issues.append("unknown_trajectory_topic")
    if len(listed) != len(set(listed)):
        issues.append("duplicate_trajectory_classification")
    if len(output.summary_zh.strip()) < 20 or len(output.summary_en.strip()) < 30:
        issues.append("trajectory_summary_too_short")
    if _count_only_trajectory_text(output.summary_zh) or _count_only_trajectory_text(output.summary_en):
        issues.append("count_only_trajectory")
    if len(output.insights) > 4:
        issues.append("too_many_trajectory_insights")
    for insight in output.insights:
        if insight.direction not in valid_topics:
            issues.append("unknown_trajectory_topic")
        evidence_ids = set(insight.evidence_work_ids)
        if not evidence_ids or not evidence_ids <= valid_evidence_ids:
            issues.append("unknown_trajectory_evidence")
        if evidence_by_topic is not None and not evidence_ids <= evidence_by_topic.get(insight.direction, set()):
            issues.append("unrelated_trajectory_evidence")
        if (
            len(insight.interpretation_zh.strip()) < 12
            or len(insight.interpretation_en.strip()) < 20
        ):
            issues.append("trajectory_insight_too_short")
        if (
            _count_only_trajectory_text(insight.interpretation_zh)
            or _count_only_trajectory_text(insight.interpretation_en)
        ):
            issues.append("count_only_trajectory")
    return list(dict.fromkeys(issues))


def agent_analyze_trajectory(state: ScholarProfileState) -> dict:
    """使用趋势 Agent 解读相邻三年窗口，并要求真实论文证据。"""
    from llm import TrajectoryAgentOutput, run_structured_agent
    from prompts import AGENT_ANALYZE_TRAJECTORY

    timeline = state.get("interest_timeline") or []
    years = [int(item.get("year") or 0) for item in timeline if item.get("year")]
    if not years:
        return {
            "trajectory_analysis": {},
            "agent_runs": [{
                "agent": "trajectory_agent",
                "status": "skipped",
                "model": "",
                "tier": "",
                "plannedTier": (state.get("agent_plan") or {}).get("trajectory_tier", "fast"),
                "attemptedModels": [],
                "escalated": False,
                "reasons": ["insufficient_timeline"],
            }],
        }

    latest = max(years)
    current_start = latest - 2
    previous_start = latest - 5
    previous_end = current_start - 1
    previous = defaultdict(int)
    current = defaultdict(int)
    for item in timeline:
        year = int(item.get("year") or 0)
        target = current if current_start <= year <= latest else previous if previous_start <= year <= previous_end else None
        if target is None:
            continue
        for topic in item.get("topics") or []:
            target[str(topic.get("topic") or "")] += int(topic.get("count") or 0)
    valid_topics = set(previous) | set(current)
    if not previous or not current:
        return {
            "trajectory_analysis": {},
            "agent_runs": [{
                "agent": "trajectory_agent",
                "status": "skipped",
                "model": "",
                "tier": "",
                "plannedTier": (state.get("agent_plan") or {}).get("trajectory_tier", "fast"),
                "attemptedModels": [],
                "escalated": False,
                "reasons": ["insufficient_comparable_windows"],
            }],
        }

    works = _analysis_works(state)
    clusters_by_topic = {
        str(cluster.get("topic") or ""): cluster
        for cluster in state.get("topic_clusters") or []
    }
    evidence_by_topic: dict[str, set[str]] = {}
    direction_payload = []
    previous_total = sum(previous.values()) or 1
    current_total = sum(current.values()) or 1
    for topic in sorted(valid_topics):
        cluster = clusters_by_topic.get(topic) or {}
        representative = []
        evidence_ids = set()
        for index in cluster.get("paper_indices") or []:
            if not isinstance(index, int) or not 0 <= index < len(works):
                continue
            work = works[index]
            year = int(work.get("publication_year") or 0)
            if not previous_start <= year <= latest:
                continue
            work_id = str(work.get("id") or work.get("doi") or "")
            if not work_id:
                continue
            evidence_ids.add(work_id)
            representative.append({
                "id": work_id,
                "title": work.get("title") or "",
                "year": year,
                "window": "current" if current_start <= year <= latest else "previous",
            })
        representative.sort(key=lambda item: (-item["year"], item["title"]))
        evidence_by_topic[topic] = evidence_ids
        direction_payload.append({
            "direction": topic,
            "description_zh": cluster.get("description") or "",
            "description_en": cluster.get("description_en") or "",
            "previous": {
                "count": previous.get(topic, 0),
                "share": round(previous.get(topic, 0) / previous_total, 4),
            },
            "current": {
                "count": current.get(topic, 0),
                "share": round(current.get(topic, 0) / current_total, 4),
            },
            "representative_papers": representative[:6],
        })
    valid_evidence_ids = {
        work_id
        for work_ids in evidence_by_topic.values()
        for work_id in work_ids
    }

    def validate(output: TrajectoryAgentOutput) -> list[str]:
        return _validate_trajectory_agent_output(
            output,
            valid_topics=valid_topics,
            valid_evidence_ids=valid_evidence_ids,
            evidence_by_topic=evidence_by_topic,
        )

    payload = {
        "previous_window": {
            "start": previous_start,
            "end": previous_end,
            "paper_count": sum(previous.values()),
        },
        "current_window": {
            "start": current_start,
            "end": latest,
            "paper_count": sum(current.values()),
        },
        "directions": direction_payload,
    }
    planned_tier = (state.get("agent_plan") or {}).get("trajectory_tier", "fast")
    output, trace = run_structured_agent(
        "trajectory_agent",
        planned_tier=planned_tier,
        system_prompt=AGENT_ANALYZE_TRAJECTORY,
        payload=payload,
        schema=TrajectoryAgentOutput,
        validate=validate,
        temperature=0.2,
        max_tokens=1800,
    )
    if not output:
        return {"trajectory_analysis": {}, "agent_runs": [trace]}
    works_by_id = {
        str(work.get("id") or work.get("doi") or ""): work
        for work in works
    }
    return {
        "trajectory_analysis": {
            "summaryZh": output.summary_zh.strip(),
            "summaryEn": output.summary_en.strip(),
            "emerging": output.emerging,
            "rising": output.rising,
            "steady": output.steady,
            "falling": output.falling,
            "insights": [{
                "direction": insight.direction,
                "changeKind": insight.change_kind,
                "interpretationZh": insight.interpretation_zh.strip(),
                "interpretationEn": insight.interpretation_en.strip(),
                "confidence": insight.confidence,
                "evidencePapers": [{
                    "id": work_id,
                    "title": works_by_id[work_id].get("title") or "",
                    "year": works_by_id[work_id].get("publication_year"),
                    "url": works_by_id[work_id].get("id") or works_by_id[work_id].get("doi") or "",
                } for work_id in insight.evidence_work_ids],
            } for insight in output.insights],
            "confidence": output.confidence,
            "previousWindow": {"start": previous_start, "end": previous_end},
            "currentWindow": {"start": current_start, "end": latest},
        },
        "agent_runs": [trace],
    }


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

    for i, w in enumerate(_analysis_works(state)):
        agent_topics = paper_agent_topics.get(
            i,
            [c["display_name"] for c in (w.get("concepts") or [])[:3]],
        )
        paper_id = w.get("id", "")

        for au in w.get("authorships") or []:
            aid = (au.get("author") or {}).get("id")
            if aid and aid not in set(state.get("target_author_ids") or [state["target_author_id"]]):
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


def orchestrate_analysis_workers(state: ScholarProfileState) -> dict:
    """Let an orchestrator choose specialist analyses supported by current evidence."""
    from llm import orchestrate_workers

    profile = state.get("target_author_profile") or {}
    institutions = [
        str(item.get("display_name") or "").strip()
        for item in profile.get("last_known_institutions") or []
        if item.get("display_name")
    ]
    institution_name = institutions[0] if institutions else "未知机构"
    evidence = _build_profile_evidence(state, institution_name)
    years = {
        int(work.get("publication_year") or 0)
        for work in _analysis_works(state)
        if work.get("publication_year")
    }
    context = {
        "paper_count": len(_analysis_works(state)),
        "representative_paper_count": len(
            _flatten_representative_papers(state.get("representative_papers") or {})
        ),
        "coauthor_count": len(state.get("coauthors") or []),
        "institution_count": len(set(institutions)),
        "active_years": len(years),
        "source_conflicts": int((state.get("data_audit") or {}).get("conflictCount") or 0),
        "identity_risk": bool(
            (state.get("identity_audit") or {}).get("possibleConflatedIdentity")
            or (state.get("identity_audit") or {}).get("provisional")
        ),
        "evidence_types": sorted({str(item.get("type")) for item in evidence}),
    }
    plan, trace = orchestrate_workers(context)
    worker_context = {
        "scholar": {
            "name": profile.get("display_name", ""),
            "publication_affiliations": institutions,
        },
        "metrics": state.get("citation_summary") or {},
        "topics": [
            {
                "name": topic.get("topic", ""),
                "weight": topic.get("weight", 0),
            }
            for topic in (state.get("topic_clusters") or [])[:8]
        ],
        "representative_papers": _flatten_representative_papers(
            state.get("representative_papers") or {}
        )[:8],
        "coauthors": [
            {
                "name": coauthor.get("name", ""),
                "institution": coauthor.get("institution", ""),
                "papers": coauthor.get("papers", 0),
            }
            for coauthor in (state.get("coauthors") or [])[:10]
        ],
        "trajectory": state.get("trajectory_analysis") or {},
        "evidence": evidence,
    }
    return {
        "orchestrator_tasks": [task.model_dump() for task in plan.tasks],
        "worker_context": worker_context,
        "profile_evidence": evidence,
        "orchestrator_analysis": {
            "rationale": plan.rationale,
            "taskCount": len(plan.tasks),
            "tasks": [task.model_dump() for task in plan.tasks],
            "findings": [],
        },
        "agent_runs": [trace],
    }


def dispatch_analysis_workers(state: ScholarProfileState):
    """Fan out dynamically selected tasks as LangGraph Send messages."""
    from langgraph.types import Send

    tasks = state.get("orchestrator_tasks") or []
    if not tasks:
        return "aggregate_workers"
    return [
        Send("analysis_worker", {
            "worker_task": task,
            "worker_context": state.get("worker_context") or {},
        })
        for task in tasks
    ]


def run_analysis_worker(state: ScholarProfileState) -> dict:
    """Run one specialist worker and retain only evidence-traceable findings."""
    from llm import OrchestratorTask, run_academic_worker

    task = OrchestratorTask.model_validate(state.get("worker_task") or {})
    output, trace = run_academic_worker(task, state.get("worker_context") or {})
    if not output:
        return {"worker_outputs": [], "agent_runs": [trace]}
    return {
        "worker_outputs": [{
            "taskId": output.task_id,
            "kind": output.kind,
            "findingZh": output.finding_zh.strip(),
            "findingEn": output.finding_en.strip(),
            "evidenceIds": output.evidence_ids,
            "confidence": output.confidence,
            "limitationsZh": output.limitations_zh.strip(),
            "limitationsEn": output.limitations_en.strip(),
        }],
        "agent_runs": [trace],
    }


def aggregate_analysis_workers(state: ScholarProfileState) -> dict:
    """Join specialist findings in the order selected by the orchestrator."""
    tasks = state.get("orchestrator_tasks") or []
    order = {
        str(task.get("id") or ""): index
        for index, task in enumerate(tasks)
    }
    findings = sorted(
        state.get("worker_outputs") or [],
        key=lambda item: (
            order.get(str(item.get("taskId") or ""), len(order)),
            str(item.get("taskId") or ""),
        ),
    )
    analysis = dict(state.get("orchestrator_analysis") or {})
    analysis["findings"] = findings
    analysis["completedTaskCount"] = len(findings)
    return {"orchestrator_analysis": analysis}


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
    audit = state.get("data_audit") or {}
    verified = int(audit.get("multiSourceVerified") or audit.get("crossrefVerified") or 0)
    sources = list(audit.get("sources") or ["OpenAlex"])
    evidence = [{
        "id": "1",
        "type": "metric",
        "text": (
            f"本次统一论文集在 {inst_name} 关联档案下收录 "
            f"{cs.get('total_papers', 0)} 篇论文、{cs.get('total_citations', 0)} 次引用，"
            f"h-index 为 {cs.get('h_index', 0)}；其中 {verified} 篇得到其他公开来源交叉核对，"
            "引用数采用 OpenAlex 口径。"
        ),
        "sources": sources,
    }]
    next_id = 2
    topics = [t["topic"] for t in state["topic_clusters"][:5]]
    if topics:
        evidence.append({
            "id": str(next_id),
            "type": "topic",
            "text": "核心研究方向来自裁决后论文标题与 OpenAlex topics、keywords 交叉聚合: " + "、".join(topics) + "。",
            "sources": sources,
        })
        next_id += 1
    profile = state.get("target_author_profile") or {}
    publication_affiliations = list(dict.fromkeys(
        str(item.get("display_name") or "").strip()
        for item in profile.get("last_known_institutions") or []
        if item.get("display_name")
    ))
    if publication_affiliations:
        evidence.append({
            "id": str(next_id),
            "type": "institution",
            "text": (
                "论文署名与 OpenAlex 作者记录关联的机构包括 "
                + "、".join(publication_affiliations[:6])
                + "；该信息仅用于研究网络与机构主题交集分析。"
            ),
            "sources": ["OpenAlex"],
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
            "sources": paper.get("sources") or ["OpenAlex"],
        })
        next_id += 1
    if state["coauthors"]:
        names = [f"{c['name']}({c['papers']} 篇)" for c in state["coauthors"][:3]]
        evidence.append({
            "id": str(next_id),
            "type": "coauthor",
            "text": "高频合作者包括 " + "、".join(names) + "。",
            "sources": ["OpenAlex"],
        })
    return evidence


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
        f"本次核验后的论文集收录 {cs.get('total_papers', 0)} 篇论文、"
        f"累计引用 {cs.get('total_citations', 0):,} 次，h-index 为 {cs.get('h_index', 0)}{metric_ref}。"
        f"其研究方向主要集中在 {topic_text}{topic_ref}{paper_text}。"
        f"{coauthor_text}"
    )


def generate_profile_report(state: ScholarProfileState) -> dict:
    """使用总结 Agent 生成双语学者分析，失败时回退到证据模板。"""
    from llm import ProfileReportOutput, run_structured_agent
    from prompts import AGENT_PROFILE_REPORT

    profile = state["target_author_profile"] or {}
    insts = [i.get("display_name", "") for i in (profile.get("last_known_institutions") or [])]
    inst_name = insts[0] if insts else "未知机构"
    cs = state["citation_summary"]
    topic_names = [t["topic"] for t in state["topic_clusters"][:5]]
    top_coauthors = [{"name": c["name"], "papers": c["papers"]} for c in state["coauthors"][:5]]
    evidence = state.get("profile_evidence") or _build_profile_evidence(state, inst_name)
    representative = _flatten_representative_papers(state["representative_papers"])[:5]
    valid_ids = {item["id"] for item in evidence}
    report_input = {
        "name": profile.get("display_name", ""),
        "publication_affiliation": inst_name,
        "metrics": {
            "total_papers": cs.get("total_papers", 0),
            "total_citations": cs.get("total_citations", 0),
            "h_index": cs.get("h_index", 0),
        },
        "topics": topic_names,
        "top_coauthors": top_coauthors,
        "representative_papers": [p.get("title", "") for p in representative],
        "trajectory": state.get("trajectory_analysis") or {},
        "specialist_findings": (
            state.get("orchestrator_analysis") or {}
        ).get("findings") or [],
        "evidence": evidence,
    }

    def validate(output: ProfileReportOutput) -> list[str]:
        issues = []
        cited = set(re.findall(r"\[(\d+)\]", output.summary_zh + " " + output.summary_en))
        declared = set(output.evidence_ids)
        if not cited or not cited <= valid_ids or not declared <= valid_ids or not cited <= declared:
            issues.append("invalid_report_citations")
        if len(output.summary_zh.strip()) < 60 or len(output.summary_en.split()) < 45:
            issues.append("report_too_short")
        return issues

    planned_tier = (state.get("agent_plan") or {}).get("report_tier", "fast")
    output, trace = run_structured_agent(
        "report_agent",
        planned_tier=planned_tier,
        system_prompt=AGENT_PROFILE_REPORT,
        payload=report_input,
        schema=ProfileReportOutput,
        validate=validate,
        temperature=0.3,
        max_tokens=1800,
    )
    if output:
        return {
            "profile_summary": output.summary_zh.strip(),
            "profile_summary_i18n": {
                "zh": output.summary_zh.strip(),
                "en": output.summary_en.strip(),
            },
            "profile_evidence": evidence,
            "agent_runs": [trace],
        }

    summary = _fallback_summary(profile, inst_name, state, evidence)
    return {
        "profile_summary": summary,
        "profile_summary_i18n": {},
        "profile_evidence": evidence,
        "agent_runs": [trace],
    }


def agent_review_profile(state: ScholarProfileState) -> dict:
    """由证据批判 Agent 审核总结，确定性审查仍保留最终否决权。"""
    from llm import EvidenceReviewOutput, run_structured_agent
    from prompts import AGENT_REVIEW_EVIDENCE

    valid_ids = {str(item.get("id")) for item in state.get("profile_evidence") or []}
    summaries = state.get("profile_summary_i18n") or {"zh": state.get("profile_summary") or ""}

    def validate(output: EvidenceReviewOutput) -> list[str]:
        issues = []
        approved = set(output.approved_evidence_ids)
        if not approved <= valid_ids:
            issues.append("review_unknown_evidence_id")
        cited = set(re.findall(r"\[(\d+)\]", " ".join(summaries.values())))
        if output.summary_supported and not cited <= approved:
            issues.append("review_missing_cited_evidence")
        return issues

    planned_tier = (state.get("agent_plan") or {}).get("review_tier", "fast")
    output, trace = run_structured_agent(
        "evidence_agent",
        planned_tier=planned_tier,
        system_prompt=AGENT_REVIEW_EVIDENCE,
        payload={
            "summaries": summaries,
            "evidence": state.get("profile_evidence") or [],
            "trajectory": state.get("trajectory_analysis") or {},
            "specialist_findings": (
                state.get("orchestrator_analysis") or {}
            ).get("findings") or [],
            "review_iteration": int(state.get("review_iteration") or 0),
        },
        schema=EvidenceReviewOutput,
        validate=validate,
        temperature=0,
        max_tokens=900,
    )
    if not output:
        return {"agent_review": {}, "agent_runs": [trace]}
    review = {
        "summarySupported": output.summary_supported,
        "approvedEvidenceIds": output.approved_evidence_ids,
        "flags": output.flags,
        "confidence": output.confidence,
        "noteZh": output.note_zh.strip(),
        "noteEn": output.note_en.strip(),
        "iteration": int(state.get("review_iteration") or 0),
    }
    return {
        "agent_review": review,
        "review_history": [review],
        "agent_runs": [trace],
    }


MAX_REVIEW_REVISIONS = 2


def route_after_agent_review(state: ScholarProfileState) -> str:
    """Send rejected reports back for revision, bounded by a deterministic limit."""
    review = state.get("agent_review") or {}
    if not review:
        return "review_evidence"
    summaries = state.get("profile_summary_i18n") or {
        "zh": state.get("profile_summary") or "",
    }
    cited = set(re.findall(r"\[(\d+)\]", " ".join(summaries.values())))
    approved = set(review.get("approvedEvidenceIds") or [])
    supported = bool(review.get("summarySupported")) and cited <= approved
    if supported or int(state.get("review_iteration") or 0) >= MAX_REVIEW_REVISIONS:
        return "review_evidence"
    return "optimize_report"


def optimize_profile_report(state: ScholarProfileState) -> dict:
    """Revise a rejected report using explicit reviewer feedback, then re-review it."""
    from llm import ProfileReportOutput, run_structured_agent
    from prompts import AGENT_OPTIMIZE_REPORT

    evidence = state.get("profile_evidence") or []
    valid_ids = {str(item.get("id")) for item in evidence}
    current_summaries = state.get("profile_summary_i18n") or {
        "zh": state.get("profile_summary") or "",
    }
    review = state.get("agent_review") or {}

    def validate(output: ProfileReportOutput) -> list[str]:
        issues = []
        cited = set(re.findall(r"\[(\d+)\]", output.summary_zh + " " + output.summary_en))
        declared = set(output.evidence_ids)
        if not cited or not cited <= valid_ids or not declared <= valid_ids or not cited <= declared:
            issues.append("invalid_optimizer_citations")
        if len(output.summary_zh.strip()) < 60 or len(output.summary_en.split()) < 35:
            issues.append("optimized_report_too_short")
        return issues

    planned_tier = (state.get("agent_plan") or {}).get("report_tier", "fast")
    output, trace = run_structured_agent(
        "optimizer_agent",
        planned_tier=planned_tier,
        system_prompt=AGENT_OPTIMIZE_REPORT,
        payload={
            "current_summaries": current_summaries,
            "review": review,
            "evidence": evidence,
            "specialist_findings": (
                state.get("orchestrator_analysis") or {}
            ).get("findings") or [],
        },
        schema=ProfileReportOutput,
        validate=validate,
        temperature=0.15,
        max_tokens=1800,
    )
    next_iteration = int(state.get("review_iteration") or 0) + 1
    if not output:
        return {
            "review_iteration": MAX_REVIEW_REVISIONS,
            "agent_runs": [trace],
        }
    return {
        "profile_summary": output.summary_zh.strip(),
        "profile_summary_i18n": {
            "zh": output.summary_zh.strip(),
            "en": output.summary_en.strip(),
        },
        "review_iteration": next_iteration,
        "agent_runs": [trace],
    }


def review_profile_evidence(state: ScholarProfileState) -> dict:
    """审查总结证据是否能回溯到裁决后的论文和确定性统计。"""
    from crossref import normalize_doi

    works = _analysis_works(state)
    traceable_keys = set()
    sources_by_key: dict[str, list[str]] = {}
    for work in works:
        keys = {str(work.get("id") or "")}
        doi = normalize_doi(work.get("doi"))
        if doi:
            keys.update({doi, f"https://doi.org/{doi}"})
        sources = [record.get("source", "") for record in work.get("source_records") or [] if record.get("source")]
        for key in filter(None, keys):
            traceable_keys.add(key)
            sources_by_key[key] = sources or ["openalex"]

    approved = []
    rejected = []
    flags = []
    audit = state.get("data_audit") or {}
    for evidence in state.get("profile_evidence") or []:
        item = deepcopy(evidence)
        evidence_type = item.get("type")
        valid = True
        if evidence_type == "paper":
            url = str(item.get("url") or "")
            normalized_url_doi = normalize_doi(url)
            valid = url in traceable_keys or normalized_url_doi in traceable_keys
            if valid:
                item["sources"] = sources_by_key.get(url) or sources_by_key.get(normalized_url_doi) or item.get("sources") or []
            else:
                flags.append("untraceable_paper_evidence")
        elif evidence_type == "topic":
            valid = bool(state.get("topic_clusters"))
        elif evidence_type == "coauthor":
            valid = bool(state.get("coauthors"))
        elif evidence_type == "institution":
            valid = bool(
                (state.get("target_author_profile") or {}).get(
                    "last_known_institutions"
                )
            )
        elif evidence_type == "metric":
            valid = int((state.get("citation_summary") or {}).get("total_papers") or 0) == len(works)
            if not valid:
                flags.append("metric_recalculation_mismatch")
        else:
            valid = False
            flags.append("unsupported_evidence_type")

        if valid:
            item["confidence"] = "high" if evidence_type == "metric" and audit.get("status") == "sufficient" else "medium"
            approved.append(item)
        else:
            rejected.append(item)

    approved_ids = [str(item.get("id")) for item in approved]
    rejected_ids = [str(item.get("id")) for item in rejected]
    metric_approved = any(item.get("type") == "metric" for item in approved)
    summary = state.get("profile_summary") or ""
    summary_i18n = dict(state.get("profile_summary_i18n") or {})
    agent_review = state.get("agent_review") or {}
    agent_approved = set(agent_review.get("approvedEvidenceIds") or [])
    cited_ids = set(re.findall(r"\[(\d+)\]", summary + " " + " ".join(summary_i18n.values())))
    agent_rejected_summary = bool(
        agent_review
        and (
            not agent_review.get("summarySupported", False)
            or not cited_ids <= agent_approved
        )
    )
    if any(f"[{evidence_id}]" in summary for evidence_id in rejected_ids) or agent_rejected_summary:
        profile = state.get("target_author_profile") or {}
        institutions = [
            item.get("display_name", "")
            for item in (profile.get("last_known_institutions") or [])
        ]
        summary = _fallback_summary(profile, institutions[0] if institutions else "未知机构", state, approved)
        summary_i18n = {}
        flags.append(
            "summary_rebuilt_after_agent_review"
            if agent_rejected_summary
            else "summary_rebuilt_after_evidence_review"
        )

    unique_flags = list(dict.fromkeys(flags))
    review = {
        "approvedEvidenceIds": approved_ids,
        "rejectedEvidenceIds": rejected_ids,
        "flags": unique_flags,
        "publishable": metric_approved,
        "summaryConfidence": (
            "high" if metric_approved and not unique_flags and audit.get("status") == "sufficient"
            and (not agent_review or agent_review.get("confidence") == "high")
            else "medium" if metric_approved
            else "low"
        ),
        "agentReviewed": bool(agent_review),
        "agentConfidence": agent_review.get("confidence", ""),
        "agentFlags": agent_review.get("flags") or [],
    }
    claims = [{
        "claimId": f"evidence-{item.get('id')}",
        "type": item.get("type"),
        "text": item.get("text", ""),
        "evidenceIds": [str(item.get("id"))],
        "confidence": item.get("confidence", "medium"),
    } for item in approved]
    return {
        "profile_summary": summary,
        "profile_summary_i18n": summary_i18n,
        "profile_evidence": approved,
        "analysis_claims": claims,
        "evidence_review": review,
    }


def format_web_payload(state: ScholarProfileState) -> dict:
    """组装前端渲染所需的 JSON 数据。"""
    profile = state["target_author_profile"] or {}
    insts = [i.get("display_name", "") for i in (profile.get("last_known_institutions") or [])]
    cs = state["citation_summary"]
    ws = _analysis_works(state)
    affiliation_evidence = build_affiliation_evidence(
        profile,
        ws,
        state.get("target_author_ids") or [state["target_author_id"]],
    )
    institution_history = affiliation_evidence.get("openAlexAffiliationHistory") or []
    institution_names = [
        row.get("name", "")
        for row in institution_history
        if row.get("name")
    ]

    # top 50 高被引论文，避免大作者 payload 过大
    top_cited = sorted(ws, key=lambda w: -(w.get("cited_by_count") or 0))
    top_cited_list = [{
        "id": w.get("id", ""),
        "title": w.get("title", ""),
        "year": w.get("publication_year"),
        "citations": w.get("cited_by_count", 0),
        "journal": _work_journal(w),
        "doi": w.get("doi", ""),
        "sources": [record.get("source") for record in w.get("source_records") or [] if record.get("source")],
        "verificationStatus": w.get("verification_status", ""),
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

    agent_runs = state.get("agent_runs") or []
    successful_agents = [run for run in agent_runs if run.get("status") == "success"]
    attempted_agents = [
        run for run in agent_runs
        if run.get("agent") != "router_agent" and run.get("status") != "skipped"
    ]
    if successful_agents and all(run.get("status") == "success" for run in attempted_agents):
        agent_status = "completed"
    elif successful_agents:
        agent_status = "partial"
    elif any(run.get("status") == "disabled" for run in agent_runs):
        agent_status = "disabled"
    else:
        agent_status = "fallback"

    payload = {
        "name": profile.get("display_name", ""),
        "authorId": state["target_author_id"],
        "institution": affiliation_evidence.get("primaryAffiliation") or "",
        "institutions": list(dict.fromkeys(filter(None, institution_names or insts))),
        "orcid": profile.get("orcid"),
        "department": "",
        "affiliationEvidence": affiliation_evidence,
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
        "coauthors": [{"id": c["id"], "name": c["name"], "institution": c.get("institution", ""), "papers": c["papers"]}
                      for c in state["coauthors"][:15]],
        "graphNodes": state["graph_nodes"],
        "graphEdges": state["graph_edges"],
        "profileSummary": state["profile_summary"],
        "profileSummaryI18n": state.get("profile_summary_i18n") or {},
        "profileEvidence": state["profile_evidence"],
        "identityAudit": state.get("identity_audit") or {},
        "dataAudit": state.get("data_audit") or {},
        "evidenceReview": state.get("evidence_review") or {},
        "agentAnalysis": {
            "status": agent_status,
            "plan": state.get("agent_plan") or {},
            "runs": agent_runs,
            "orchestrator": state.get("orchestrator_analysis") or {},
            "trajectory": state.get("trajectory_analysis") or {},
            "review": state.get("agent_review") or {},
            "reviewHistory": state.get("review_history") or [],
            "reviewIterations": int(state.get("review_iteration") or 0),
        },
    }
    return {"web_payload": payload}
