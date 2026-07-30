from nodes import (
    _fallback_topic_analysis,
    _filter_identity_outlier_works,
    _validate_topic_agent_output,
    _validate_trajectory_agent_output,
    adjudicate_sources,
    agent_analyze_topics,
    agent_analyze_trajectory,
    analyze_coauthors,
    build_collaboration_graph,
    collect_crossref_records,
    collect_dblp_records,
    collect_google_scholar_records,
    collect_works,
    dedup_authors,
    fetch_author_profile,
    format_web_payload,
    generate_profile_report,
    review_profile_evidence,
)
from state import default_state
from workflow import NODES


def _identity_fingerprint(*, coauthors=(), topics=(), works=()):
    return {
        "coauthor_ids": list(coauthors),
        "topic_ids": list(topics),
        "work_ids": list(works),
    }


def test_dedup_authors_merges_split_profiles_with_strong_identity_evidence():
    candidates = [
        {
            "id": "A1",
            "display_name": "Haofen Wang",
            "orcid": "https://orcid.org/0000-0003-3018-3824",
            "works_count": 172,
            "cited_by_count": 2379,
            "summary_stats": {"h_index": 23},
            "last_known_institutions": [{"display_name": "Tongji University"}],
            "identity_fingerprint": _identity_fingerprint(
                coauthors=("C1", "C2", "C3", "C4", "C5", "C6"),
                topics=("T1", "T2", "T3", "T4"),
            ),
        },
        {
            "id": "A2",
            "display_name": "haofen wang",
            "works_count": 32,
            "cited_by_count": 384,
            "summary_stats": {"h_index": 7},
            "last_known_institutions": [{"display_name": "Tongji University"}],
            "identity_fingerprint": _identity_fingerprint(
                coauthors=("C1", "C2", "C3", "C4", "C5", "C7"),
                topics=("T1", "T2", "T3", "T5"),
            ),
        },
    ]

    merged = dedup_authors(candidates)

    assert len(merged) == 1
    assert merged[0]["id"] == "A1"
    assert merged[0]["merged_ids"] == ["A1", "A2"]
    assert merged[0]["merged_count"] == 2
    assert merged[0]["identity_confidence"] == "high"


def test_dedup_authors_keeps_namesakes_separate_when_only_name_and_institution_match():
    candidates = [
        {
            "id": "A1",
            "display_name": "Wei Wang",
            "works_count": 40,
            "cited_by_count": 300,
            "summary_stats": {"h_index": 9},
            "last_known_institutions": [{"display_name": "Example University"}],
            "identity_fingerprint": _identity_fingerprint(coauthors=("C1",), topics=("T1", "T2")),
        },
        {
            "id": "A2",
            "display_name": "Wei Wang",
            "works_count": 35,
            "cited_by_count": 250,
            "summary_stats": {"h_index": 8},
            "last_known_institutions": [{"display_name": "Example University"}],
            "identity_fingerprint": _identity_fingerprint(coauthors=("C2",), topics=("T3", "T4")),
        },
    ]

    merged = dedup_authors(candidates)

    assert len(merged) == 2
    assert [author["id"] for author in merged] == ["A1", "A2"]


def test_dedup_authors_does_not_override_orcid_conflict_with_weak_overlap():
    candidates = [
        {
            "id": "A1",
            "display_name": "Alex Kim",
            "orcid": "https://orcid.org/0000-0000-0000-0001",
            "works_count": 10,
            "last_known_institutions": [{"display_name": "Example University"}],
            "identity_fingerprint": _identity_fingerprint(coauthors=("C1", "C2"), topics=("T1", "T2")),
        },
        {
            "id": "A2",
            "display_name": "Alex Kim",
            "orcid": "https://orcid.org/0000-0000-0000-0002",
            "works_count": 8,
            "last_known_institutions": [{"display_name": "Example University"}],
            "identity_fingerprint": _identity_fingerprint(coauthors=("C1", "C3"), topics=("T1", "T3")),
        },
    ]

    assert len(dedup_authors(candidates)) == 2


def test_dedup_authors_does_not_override_orcid_conflict_with_large_overlap():
    shared_coauthors = tuple(f"C{index}" for index in range(30))
    shared_topics = tuple(f"T{index}" for index in range(20))
    candidates = [
        {
            "id": "A1",
            "display_name": "Wei Wang",
            "orcid": "https://orcid.org/0000-0000-0000-0001",
            "works_count": 900,
            "last_known_institutions": [{"display_name": "Example University"}],
            "identity_fingerprint": _identity_fingerprint(
                coauthors=shared_coauthors,
                topics=shared_topics,
            ),
        },
        {
            "id": "A2",
            "display_name": "Wei Wang",
            "orcid": "https://orcid.org/0000-0000-0000-0002",
            "works_count": 800,
            "last_known_institutions": [{"display_name": "Example University"}],
            "identity_fingerprint": _identity_fingerprint(
                coauthors=shared_coauthors,
                topics=shared_topics,
            ),
        },
    ]

    assert len(dedup_authors(candidates)) == 2


def test_dedup_authors_keeps_diffuse_profiles_separate_despite_context_overlap():
    candidates = [
        {
            "id": "A1",
            "display_name": "Wei Wang",
            "works_count": 600,
            "last_known_institutions": [
                {"display_name": f"Institution {index}"} for index in range(20)
            ],
            "identity_fingerprint": _identity_fingerprint(
                coauthors=("C1", "C2", "C3", "C4"),
                topics=("T1", "T2", "T3", "T4"),
            ),
        },
        {
            "id": "A2",
            "display_name": "Wei Wang",
            "works_count": 30,
            "last_known_institutions": [{"display_name": "Institution 1"}],
            "identity_fingerprint": _identity_fingerprint(
                coauthors=("C1", "C2", "C3", "C4"),
                topics=("T1", "T2", "T3", "T4"),
            ),
        },
    ]

    assert len(dedup_authors(candidates)) == 2


def test_dedup_authors_only_merges_repeated_openalex_id():
    candidates = [
        {
            "id": "A1",
            "display_name": "Lina Chen",
            "works_count": 10,
            "cited_by_count": 100,
            "summary_stats": {"h_index": 5},
            "last_known_institutions": [{"display_name": "Zhejiang Normal University"}],
        },
        {
            "id": "A1",
            "display_name": "Lina Chen",
            "works_count": 10,
            "cited_by_count": 100,
            "summary_stats": {"h_index": 5},
            "last_known_institutions": [{"display_name": "Zhejiang Normal University"}],
        },
    ]

    merged = dedup_authors(candidates)

    assert len(merged) == 1
    assert merged[0]["id"] == "A1"
    assert merged[0]["merged_ids"] == ["A1"]
    assert merged[0]["merged_count"] == 1
    assert merged[0]["institutions"] == ["Zhejiang Normal University"]


def test_analyze_coauthors_keeps_same_name_different_ids_separate():
    state = default_state()
    state["target_author_id"] = "A0"
    state["deduped_works"] = [
        {
            "id": "W1",
            "title": "Paper 1",
            "authorships": [
                {"author": {"id": "A0", "display_name": "Center"}},
                {
                    "author": {"id": "A1", "display_name": "Wei Zhang"},
                    "institutions": [{"display_name": "University One"}],
                },
            ],
        },
        {
            "id": "W2",
            "title": "Paper 2",
            "authorships": [
                {"author": {"id": "A0", "display_name": "Center"}},
                {
                    "author": {"id": "A2", "display_name": "Wei Zhang"},
                    "institutions": [{"display_name": "University Two"}],
                },
            ],
        },
    ]

    result = analyze_coauthors(state)

    assert len(result["coauthors"]) == 2
    assert {item["id"] for item in result["coauthors"]} == {"A1", "A2"}
    assert [item["papers"] for item in result["coauthors"]] == [1, 1]
    assert {item["institution"] for item in result["coauthors"]} == {
        "University One",
        "University Two",
    }

    state["coauthors"] = result["coauthors"]
    state["target_author_profile"] = {"display_name": "Center"}
    graph = build_collaboration_graph(state)
    institutions = {
        item["institution"]
        for item in graph["graph_nodes"]
        if item["type"] == "coauthor"
    }
    assert institutions == {"University One", "University Two"}


def test_collect_works_marks_complete_fetch_for_quality_gate(monkeypatch):
    import openalex

    state = default_state()
    state["target_author_id"] = "A0"
    state["target_author_profile"] = {"works_count": 1}
    monkeypatch.setattr(
        openalex,
        "get_works",
        lambda _author_id, **_kwargs: ([{"id": "W1"}], []),
    )

    result = collect_works(state)

    assert [work["id"] for work in result["raw_works"]] == ["W1"]
    assert result["source_works"]["openalex"] == result["raw_works"]
    assert result["works_complete"] is True


def test_collect_works_marks_partial_fetch_for_quality_gate(monkeypatch):
    import openalex

    state = default_state()
    state["target_author_id"] = "A0"
    state["target_author_profile"] = {"works_count": 2}
    monkeypatch.setattr(
        openalex,
        "get_works",
        lambda _author_id, **_kwargs: ([{"id": "W1"}], ["OpenAlex partial fetch"]),
    )

    result = collect_works(state)

    assert result["works_complete"] is False
    assert "OpenAlex partial fetch" in result["warnings"]


def test_fetch_profile_and_collect_works_join_merged_author_ids(monkeypatch):
    import openalex

    profiles = {
        "A1": {
            "id": "A1",
            "display_name": "Haofen Wang",
            "works_count": 2,
            "last_known_institutions": [{"id": "I1", "display_name": "Tongji University"}],
            "identity_fingerprint": _identity_fingerprint(
                coauthors=("C1", "C2", "C3"), topics=("T1", "T2")
            ),
        },
        "A2": {
            "id": "A2",
            "display_name": "HaoFen Wang",
            "works_count": 1,
            "last_known_institutions": [{"id": "I1", "display_name": "Tongji University"}],
            "identity_fingerprint": _identity_fingerprint(
                coauthors=("C1", "C2", "C3"), topics=("T1", "T2")
            ),
        },
    }
    works = {
        "A1": ([{"id": "W1", "authorships": [{"author": {"id": "A1", "display_name": "Haofen Wang"}}]}], []),
        "A2": ([{"id": "W2", "authorships": [{"author": {"id": "A2", "display_name": "HaoFen Wang"}}]}], []),
    }
    monkeypatch.setattr(openalex, "get_author", lambda author_id, **_kwargs: profiles[author_id])
    monkeypatch.setattr(openalex, "get_works", lambda author_id, **_kwargs: works[author_id])

    state = default_state()
    state["target_author_id"] = "A1"
    state["target_author_ids"] = ["A1", "A2"]
    state.update(fetch_author_profile(state))
    result = collect_works(state)

    assert state["target_author_profile"]["works_count"] == 3
    assert state["target_author_profile"]["merged_author_ids"] == ["A1", "A2"]
    assert {work["id"] for work in result["raw_works"]} == {"W1", "W2"}
    assert {
        authorship["author"]["id"]
        for work in result["raw_works"]
        for authorship in work["authorships"]
    } == {"A1"}
    assert result["works_complete"] is True


def test_fetch_profile_rejects_client_supplied_namesake_without_identity_evidence(monkeypatch):
    import openalex

    profiles = {
        "A1": {
            "id": "A1",
            "display_name": "Wei Wang",
            "works_count": 20,
            "last_known_institutions": [{"id": "I1", "display_name": "Example University"}],
            "identity_fingerprint": _identity_fingerprint(coauthors=("C1",), topics=("T1",)),
        },
        "A2": {
            "id": "A2",
            "display_name": "Wei Wang",
            "works_count": 18,
            "last_known_institutions": [{"id": "I1", "display_name": "Example University"}],
            "identity_fingerprint": _identity_fingerprint(coauthors=("C2",), topics=("T2",)),
        },
    }
    monkeypatch.setattr(openalex, "get_author", lambda author_id, **_kwargs: profiles[author_id])

    state = default_state()
    state["target_author_id"] = "A1"
    state["target_author_ids"] = ["A1", "A2"]
    result = fetch_author_profile(state)

    assert result["target_author_ids"] == ["A1"]
    assert result["identity_audit"]["rejectedAuthorIds"] == ["A2"]
    assert result["target_author_profile"]["works_count"] == 20


def test_specific_topic_analysis_prefers_fine_grained_phrases_over_broad_fields():
    works = [
        {
            "id": "W1",
            "title": "Large Language Model Enhanced Knowledge Representation Learning: A Survey",
            "publication_year": 2025,
            "cited_by_count": 20,
            "primary_topic": {"id": "T1", "display_name": "Topic Modeling", "score": 0.8},
            "topics": [{"id": "T1", "display_name": "Topic Modeling", "score": 0.8}],
            "keywords": [
                {"display_name": "Artificial intelligence", "score": 0.8},
                {"display_name": "Knowledge graph", "score": 0.7},
                {"display_name": "Large language model", "score": 0.9},
            ],
            "concepts": [{"display_name": "Data science", "score": 0.9, "level": 1}],
        },
        {
            "id": "W2",
            "title": "Knowledge Graph Enhanced Large Language Models for Question Answering",
            "publication_year": 2026,
            "cited_by_count": 5,
            "primary_topic": {"id": "T2", "display_name": "Semantic Web and Ontologies", "score": 0.9},
            "topics": [{"id": "T2", "display_name": "Semantic Web and Ontologies", "score": 0.9}],
            "keywords": [
                {"display_name": "Knowledge graph", "score": 0.9},
                {"display_name": "Artificial intelligence", "score": 0.7},
                {"display_name": "Large language model", "score": 0.9},
            ],
            "concepts": [{"display_name": "Artificial intelligence", "score": 0.9, "level": 1}],
        },
        {
            "id": "W3",
            "title": "Retrieval Augmented Generation over Enterprise Knowledge Graphs",
            "publication_year": 2026,
            "cited_by_count": 3,
            "primary_topic": {"id": "T2", "display_name": "Semantic Web and Ontologies", "score": 0.8},
            "topics": [{"id": "T2", "display_name": "Semantic Web and Ontologies", "score": 0.8}],
            "keywords": [
                {"display_name": "Knowledge graph", "score": 0.9},
                {"display_name": "Retrieval augmented generation", "score": 0.9},
            ],
            "concepts": [{"display_name": "Data science", "score": 0.7, "level": 1}],
        },
    ]

    result = _fallback_topic_analysis(works)
    topics = [item["topic"].casefold() for item in result["topic_clusters"]]

    assert "knowledge graph" in topics
    assert "large language model" in topics
    assert "retrieval augmented generation" in topics
    assert "artificial intelligence" not in topics
    assert "data science" not in topics
    assert all(item["paper_indices"] for item in result["topic_clusters"])


def test_identity_outlier_filter_excludes_small_disconnected_work_cluster():
    core_works = [{
        "id": f"W{index}",
        "authorships": [
            {
                "author": {"id": "A1", "display_name": "Wei Wang"},
                "institutions": [{"id": "I1", "display_name": "Example University"}],
            },
            {"author": {"id": "C1", "display_name": "Core Collaborator"}},
        ],
        "primary_topic": {"id": "T1", "display_name": "Knowledge Graph"},
        "topics": [{"id": "T1", "display_name": "Knowledge Graph"}],
    } for index in range(20)]
    outliers = [{
        "id": f"O{index}",
        "authorships": [
            {
                "author": {"id": "A1", "display_name": "Wei Wang"},
                "institutions": [{"id": "I9", "display_name": "Unrelated Hospital"}],
            },
            {"author": {"id": "C9", "display_name": "Other Collaborator"}},
        ],
        "primary_topic": {"id": "T9", "display_name": "Clinical Surgery"},
        "topics": [{"id": "T9", "display_name": "Clinical Surgery"}],
    } for index in range(2)]

    kept, audit = _filter_identity_outlier_works(core_works + outliers, "A1")

    assert len(kept) == 20
    assert audit["excludedWorks"] == 2
    assert audit["possibleConflatedIdentity"] is True
    assert audit["excludedWorkIds"] == ["O0", "O1"]


def test_identity_outlier_filter_keeps_new_topic_with_core_collaborator():
    works = [{
        "id": f"W{index}",
        "authorships": [
            {"author": {"id": "A1"}, "institutions": [{"id": "I1"}]},
            {"author": {"id": "C1"}},
        ],
        "topics": [{"id": "T1"}],
    } for index in range(20)]
    works.append({
        "id": "NEW",
        "authorships": [
            {"author": {"id": "A1"}, "institutions": [{"id": "I2"}]},
            {"author": {"id": "C1"}},
        ],
        "topics": [{"id": "T2"}],
    })

    kept, audit = _filter_identity_outlier_works(works, "A1")

    assert len(kept) == 21
    assert audit["excludedWorks"] == 0


def test_identity_filter_keeps_orcid_anchored_cross_direction_work():
    works = [
        {
            "id": "TRAFFIC",
            "doi": "https://doi.org/10.1000/traffic",
            "title": "Urban Traffic Forecasting",
            "publication_year": 2025,
            "authorships": [
                {"author": {"id": "A1"}, "institutions": [{"id": "I1"}]},
                {"author": {"id": "C1"}},
            ],
            "topics": [{"id": "T-TRAFFIC", "display_name": "Traffic Forecasting"}],
        },
        {
            "id": "ROUGH",
            "doi": "https://doi.org/10.1000/rough",
            "title": "Rough Set Based Feature Selection",
            "publication_year": 2018,
            "authorships": [
                {"author": {"id": "A1"}, "institutions": [{"id": "I2"}]},
                {"author": {"id": "C2"}},
            ],
            "topics": [{"id": "T-ROUGH", "display_name": "Rough Sets"}],
        },
        {
            "id": "SPEECH",
            "doi": "https://doi.org/10.1000/speech",
            "title": "Robust Speech Recognition",
            "publication_year": 2025,
            "authorships": [
                {"author": {"id": "A1"}, "institutions": [{"id": "I9"}]},
                {"author": {"id": "C9"}},
            ],
            "topics": [{"id": "T-SPEECH", "display_name": "Speech Recognition"}],
        },
    ]

    kept, audit = _filter_identity_outlier_works(
        works,
        "A1",
        orcid_works=[
            {"doi": "10.1000/traffic", "title": "Urban Traffic Forecasting", "year": 2025},
            {"doi": "10.1000/rough", "title": "Rough Set Based Feature Selection", "year": 2018},
        ],
    )

    assert {work["id"] for work in kept} == {"TRAFFIC", "ROUGH"}
    assert audit["resolutionMethod"] == "orcid_anchor"
    assert audit["orcidMatchedWorks"] == 2
    assert audit["excludedWorks"] == 1


def test_identity_filter_excludes_large_disconnected_conflict_cluster():
    core = [{
        "id": f"CORE-{index}",
        "publication_year": 2020 + index % 6,
        "authorships": [
            {"author": {"id": "A1"}, "institutions": [{"id": "I1"}]},
            {"author": {"id": "C1"}},
        ],
        "topics": [{"id": "T1", "display_name": "Urban Computing"}],
    } for index in range(12)]
    conflict = [{
        "id": f"CONFLICT-{index}",
        "publication_year": 2020 + index % 6,
        "authorships": [
            {"author": {"id": "A1"}, "institutions": [{"id": "I9"}]},
            {"author": {"id": "C9"}},
        ],
        "topics": [{"id": "T9", "display_name": "Speech Recognition"}],
    } for index in range(10)]

    kept, audit = _filter_identity_outlier_works(
        core + conflict,
        "A1",
        target_institution_ids={"I1"},
    )

    assert {work["id"] for work in kept} == {work["id"] for work in core}
    assert audit["excludedWorks"] == 10
    assert audit["excludedClusters"][0]["workCount"] == 10
    assert audit["possibleConflatedIdentity"] is True


def test_identity_filter_does_not_join_unrelated_clusters_by_institution_only():
    core = [{
        "id": f"CORE-{index}",
        "doi": f"https://doi.org/10.1000/core-{index}",
        "publication_year": 2022 + index,
        "authorships": [
            {"author": {"id": "A1"}, "institutions": [{"id": "I1"}]},
            {"author": {"id": "C1"}},
        ],
        "topics": [{"id": "T1", "display_name": "Indoor Positioning"}],
    } for index in range(2)]
    conflict = [{
        "id": f"CONFLICT-{index}",
        "publication_year": 2022 + index,
        "authorships": [
            {"author": {"id": "A1"}, "institutions": [{"id": "I1"}]},
            {"author": {"id": "C9"}},
        ],
        "topics": [{"id": "T9", "display_name": "Medical Imaging"}],
    } for index in range(4)]

    kept, audit = _filter_identity_outlier_works(
        core + conflict,
        "A1",
        orcid_works=[{
            "doi": "10.1000/core-0",
            "title": "",
            "year": 2022,
        }],
    )

    assert {work["id"] for work in kept} == {"CORE-0", "CORE-1"}
    assert audit["resolutionMethod"] == "orcid_anchor"
    assert audit["excludedWorks"] == 4


def test_identity_filter_keeps_stable_coauthor_across_institutions():
    works = [
        {
            "id": "ANCHOR",
            "doi": "https://doi.org/10.1000/anchor",
            "publication_year": 2022,
            "authorships": [
                {"author": {"id": "A1"}, "institutions": [{"id": "I1"}]},
                {"author": {"id": "C1"}},
            ],
        },
        {
            "id": "FOLLOW-UP",
            "publication_year": 2025,
            "authorships": [
                {"author": {"id": "A1"}, "institutions": [{"id": "I2"}]},
                {"author": {"id": "C1"}},
            ],
        },
    ]

    kept, audit = _filter_identity_outlier_works(
        works,
        "A1",
        orcid_works=[{
            "doi": "10.1000/anchor",
            "title": "",
            "year": 2022,
        }],
    )

    assert {work["id"] for work in kept} == {"ANCHOR", "FOLLOW-UP"}
    assert audit["excludedWorks"] == 0


def test_title_phrases_require_three_repeated_papers():
    works = [{
        "id": f"W{index}",
        "title": (
            "End to End Deep Learning for Robust Speech Recognition"
            if index < 2 else f"Independent Study {index}"
        ),
        "publication_year": 2025,
        "cited_by_count": 1,
        "topics": [],
        "keywords": [],
        "concepts": [],
    } for index in range(5)]

    result = _fallback_topic_analysis(works)

    assert all(
        "speech recognition" not in item["topic"].casefold()
        for item in result["topic_clusters"]
    )


def test_topic_agent_validator_rejects_paper_title_as_direction():
    from llm import TopicAgentOutput, TopicDirection

    output = TopicAgentOutput(directions=[TopicDirection(
        name="End to End Deep Learning for Robust Speech Recognition",
        description_zh="围绕鲁棒语音识别方法开展研究。",
        description_en="Research on robust speech recognition methods.",
        source_topics=["Speech Recognition"],
        confidence="medium",
    )])

    issues = _validate_topic_agent_output(
        output,
        candidate_names={"Speech Recognition"},
        representative_titles=[
            "End-to-End Deep Learning for Robust Speech Recognition",
        ],
        minimum_directions=1,
    )

    assert "topic_name_word_count" in issues or "paper_title_as_topic" in issues


def test_trajectory_validator_requires_real_evidence_and_rejects_count_restatement():
    from llm import TrajectoryAgentOutput, TrajectoryInsight

    output = TrajectoryAgentOutput(
        summary_zh="该方向从3篇变成8篇，数量有所上升。",
        summary_en="The direction increased from 3 papers to 8 papers.",
        emerging=[],
        rising=["Urban Computing"],
        steady=[],
        falling=[],
        insights=[TrajectoryInsight(
            direction="Urban Computing",
            change_kind="rising",
            interpretation_zh="论文从3篇增加到8篇。",
            interpretation_en="The papers increased from 3 to 8.",
            evidence_work_ids=["W404"],
            confidence="medium",
        )],
        confidence="medium",
    )

    issues = _validate_trajectory_agent_output(
        output,
        valid_topics={"Urban Computing"},
        valid_evidence_ids={"W1", "W2"},
    )

    assert "unknown_trajectory_evidence" in issues
    assert "count_only_trajectory" in issues


def test_trajectory_validator_rejects_count_restatement_with_chinese_growth_wording():
    from llm import TrajectoryAgentOutput

    output = TrajectoryAgentOutput(
        summary_zh=(
            "关键词查询翻译与RDF语义搜索论文数由3篇增长至10篇，呈上升趋势；"
            "医学视觉问答方向从6篇降至2篇。"
        ),
        summary_en=(
            "Keyword translation papers increased from 3 to 10, while medical "
            "visual question answering papers declined from 6 to 2."
        ),
        rising=["Semantic Search"],
        falling=["Medical Visual Question Answering"],
        confidence="medium",
    )

    issues = _validate_trajectory_agent_output(
        output,
        valid_topics={"Semantic Search", "Medical Visual Question Answering"},
        valid_evidence_ids=set(),
    )

    assert "count_only_trajectory" in issues


def test_trajectory_agent_publishes_content_insight_with_real_papers(monkeypatch):
    import llm

    works = [
        {
            "id": "W1",
            "title": "Traffic Forecasting with Graph Models",
            "publication_year": 2022,
        },
        {
            "id": "W2",
            "title": "Citywide Mobility Prediction with Foundation Models",
            "publication_year": 2025,
        },
    ]
    state = default_state()
    state["deduped_works"] = works
    state["topic_clusters"] = [{
        "topic": "Spatio Temporal Mobility Prediction",
        "description": "研究城市交通与移动模式预测。",
        "description_en": "Urban traffic and mobility prediction.",
        "paper_indices": [0, 1],
    }]
    state["interest_timeline"] = [
        {"year": 2022, "topics": [{"topic": "Spatio Temporal Mobility Prediction", "count": 1}]},
        {"year": 2025, "topics": [{"topic": "Spatio Temporal Mobility Prediction", "count": 1}]},
    ]
    state["agent_plan"] = {"trajectory_tier": "fast"}
    monkeypatch.setattr(llm, "run_structured_agent", lambda *_args, **_kwargs: (
        llm.TrajectoryAgentOutput(
            summary_zh="研究持续关注城市移动预测，近期方法证据转向面向城市尺度的基础模型。",
            summary_en="The work remains focused on urban mobility prediction while recent evidence shifts toward city-scale foundation models.",
            steady=["Spatio Temporal Mobility Prediction"],
            insights=[llm.TrajectoryInsight(
                direction="Spatio Temporal Mobility Prediction",
                change_kind="steady",
                interpretation_zh="研究问题仍是城市移动预测，近期代表作显示方法从图模型延伸到基础模型。",
                interpretation_en="The research problem remains urban mobility prediction, while recent work extends the method from graph models to foundation models.",
                evidence_work_ids=["W1", "W2"],
                confidence="high",
            )],
            confidence="high",
        ),
        {
            "agent": "trajectory_agent",
            "status": "success",
            "model": "deepseek-v4-flash",
            "tier": "fast",
            "plannedTier": "fast",
            "attemptedModels": ["deepseek-v4-flash"],
            "escalated": False,
            "reasons": [],
        },
    ))

    result = agent_analyze_trajectory(state)

    insight = result["trajectory_analysis"]["insights"][0]
    assert insight["direction"] == "Spatio Temporal Mobility Prediction"
    assert [paper["id"] for paper in insight["evidencePapers"]] == ["W1", "W2"]


def test_crossref_collection_and_adjudication_merge_by_doi(monkeypatch):
    import crossref

    state = default_state()
    state["target_author_id"] = "A0"
    state["target_author_profile"] = {"works_count": 2}
    state["works_complete"] = True
    state["deduped_works"] = [
        {
            "id": "https://openalex.org/W1",
            "doi": "https://doi.org/10.1000/ONE",
            "title": "OpenAlex title",
            "publication_year": 2023,
            "cited_by_count": 8,
            "authorships": [],
            "concepts": [],
            "primary_location": {"source": {"display_name": "OpenAlex Journal"}},
        },
        {
            "id": "https://openalex.org/W2",
            "title": "No DOI paper",
            "publication_year": 2022,
            "cited_by_count": 2,
            "authorships": [],
            "concepts": [],
        },
    ]

    monkeypatch.setattr(crossref, "verify_dois", lambda _dois: ({
        "10.1000/one": {
            "source": "crossref",
            "id": "10.1000/one",
            "doi": "10.1000/one",
            "title": "Publisher title",
            "publication_year": 2024,
            "journal": "Publisher Journal",
            "authors": ["Ada Lovelace"],
            "type": "journal-article",
            "raw": {},
        },
    }, {"requested": 1, "verified": 1, "missing": 0, "failed": 0}))

    collected = collect_crossref_records(state)
    state.update(collected)
    adjudicated = adjudicate_sources(state)

    assert len(adjudicated["adjudicated_works"]) == 2
    verified = adjudicated["adjudicated_works"][0]
    assert verified["title"] == "Publisher title"
    assert verified["publication_year"] == 2024
    assert verified["verification_status"] == "verified"
    assert verified["field_sources"]["title"] == "crossref"
    assert {item["source"] for item in verified["source_records"]} == {"openalex", "crossref"}
    assert adjudicated["data_audit"]["crossrefVerified"] == 1
    assert adjudicated["data_audit"]["unverifiedWorks"] == 1
    assert adjudicated["data_audit"]["conflictCount"] == 2
    assert adjudicated["deduped_works"] == adjudicated["adjudicated_works"]


def test_dblp_and_google_scholar_add_verification_without_expanding_works(monkeypatch):
    import dblp
    import google_scholar

    state = default_state()
    state["target_author_profile"] = {"display_name": "Fei-Fei Li", "works_count": 1}
    state["works_complete"] = True
    state["deduped_works"] = [{
        "id": "https://openalex.org/W1",
        "doi": "https://doi.org/10.1000/vision",
        "title": "Visual Recognition",
        "publication_year": 2024,
        "cited_by_count": 8,
        "authorships": [],
        "concepts": [],
    }]
    state["source_works"] = {"openalex": state["deduped_works"], "crossref": []}
    state["source_audit"] = {"requested": 1, "verified": 0, "missing": 1, "failed": 0}
    monkeypatch.setattr(dblp, "verify_author_works", lambda _profile, _works: ([{
        "source": "dblp",
        "id": "journals/test/one",
        "doi": "10.1000/vision",
        "title": "Visual Recognition",
        "publication_year": 2024,
        "journal": "Vision Journal",
        "url": "https://dblp.org/rec/journals/test/one",
    }], {"status": "available", "requested": 1, "matched": 1}))
    monkeypatch.setattr(google_scholar, "verify_author_works", lambda _profile, _works: ([{
        "source": "google_scholar",
        "id": "scholar-1",
        "title": "Visual Recognition",
        "publication_year": 2024,
        "url": "https://scholar.google.com/example",
    }], {"status": "available", "requested": 1, "matched": 1}))

    state.update(collect_dblp_records(state))
    state.update(collect_google_scholar_records(state))
    result = adjudicate_sources(state)

    assert len(result["adjudicated_works"]) == 1
    work = result["adjudicated_works"][0]
    assert {item["source"] for item in work["source_records"]} == {
        "openalex", "dblp", "google_scholar",
    }
    assert work["adjudicated_journal"] == "Vision Journal"
    assert result["data_audit"]["multiSourceVerified"] == 1
    assert result["data_audit"]["unverifiedWorks"] == 0
    assert result["data_audit"]["sources"] == [
        "OpenAlex", "Crossref", "DBLP", "Google Scholar",
    ]


def test_evidence_review_rejects_untraceable_paper_claim():
    state = default_state()
    state["adjudicated_works"] = [{
        "id": "https://openalex.org/W1",
        "doi": "https://doi.org/10.1000/one",
        "title": "Known paper",
    }]
    state["citation_summary"] = {"total_papers": 1, "total_citations": 3, "h_index": 1}
    state["profile_summary"] = "Summary [1] [2]"
    state["profile_evidence"] = [
        {"id": "1", "type": "metric", "text": "One verified paper."},
        {"id": "2", "type": "paper", "text": "Unknown paper.", "url": "https://openalex.org/W404"},
    ]

    result = review_profile_evidence(state)

    assert [item["id"] for item in result["profile_evidence"]] == ["1"]
    assert result["evidence_review"]["approvedEvidenceIds"] == ["1"]
    assert result["evidence_review"]["rejectedEvidenceIds"] == ["2"]
    assert "untraceable_paper_evidence" in result["evidence_review"]["flags"]
    assert result["evidence_review"]["publishable"] is True


def test_topic_agent_reorganizes_traceable_directions(monkeypatch):
    import llm

    state = default_state()
    state["deduped_works"] = [
        {
            "id": "W1",
            "title": "Knowledge Graph Completion with Language Models",
            "publication_year": 2025,
            "cited_by_count": 10,
            "primary_topic": {"display_name": "Knowledge graph", "score": 0.9},
            "topics": [{"display_name": "Knowledge graph", "score": 0.9}],
            "keywords": [],
            "concepts": [],
        },
        {
            "id": "W2",
            "title": "Question Answering over Knowledge Graphs",
            "publication_year": 2024,
            "cited_by_count": 8,
            "primary_topic": {"display_name": "Question answering", "score": 0.9},
            "topics": [{"display_name": "Question answering", "score": 0.9}],
            "keywords": [],
            "concepts": [],
        },
    ]
    state["agent_plan"] = {"topic_tier": "fast"}
    monkeypatch.setattr(llm, "run_structured_agent", lambda *_args, **_kwargs: (
        llm.TopicAgentOutput(directions=[
            llm.TopicDirection(
                name="Knowledge Graph Question Answering",
                description_zh="围绕知识图谱上的问答与知识补全开展研究。",
                description_en="Research on question answering and completion over knowledge graphs.",
                source_topics=["Knowledge graph", "Question answering"],
                confidence="high",
            ),
        ]),
        {
            "agent": "topic_agent",
            "status": "success",
            "model": "deepseek-v4-flash",
            "tier": "fast",
            "plannedTier": "fast",
            "attemptedModels": ["deepseek-v4-flash"],
            "escalated": False,
            "reasons": [],
        },
    ))

    result = agent_analyze_topics(state)

    assert result["topic_clusters"][0]["topic"] == "Knowledge Graph Question Answering"
    assert result["topic_clusters"][0]["paper_indices"] == [0, 1]
    assert result["topic_clusters"][0]["agent_generated"] is True
    assert result["agent_runs"][0]["status"] == "success"


def test_agent_evidence_rejection_rebuilds_summary():
    state = default_state()
    state["target_author_profile"] = {
        "display_name": "Ada Lovelace",
        "last_known_institutions": [{"display_name": "Analytical Engine Lab"}],
    }
    state["adjudicated_works"] = [{"id": "W1", "title": "Known paper"}]
    state["citation_summary"] = {"total_papers": 1, "total_citations": 3, "h_index": 1}
    state["profile_summary"] = "Unsupported summary [1]"
    state["profile_summary_i18n"] = {"zh": "不受支持的总结 [1]", "en": "Unsupported summary [1]"}
    state["profile_evidence"] = [{"id": "1", "type": "metric", "text": "One paper."}]
    state["agent_review"] = {
        "summarySupported": False,
        "approvedEvidenceIds": ["1"],
        "flags": ["unsupported_claim"],
        "confidence": "low",
    }

    result = review_profile_evidence(state)

    assert result["profile_summary_i18n"] == {}
    assert "summary_rebuilt_after_agent_review" in result["evidence_review"]["flags"]
    assert result["evidence_review"]["agentReviewed"] is True


def test_generate_profile_report_falls_back_to_evidence_when_llm_lacks_citations(monkeypatch):
    import llm

    state = default_state()
    state["target_author_id"] = "A0"
    state["target_author_profile"] = {
        "display_name": "Ada Lovelace",
        "last_known_institutions": [{"display_name": "Analytical Engine Lab"}],
    }
    state["citation_summary"] = {"total_papers": 3, "total_citations": 42, "h_index": 2}
    state["topic_clusters"] = [{"topic": "Computing", "weight": 0.7, "paper_indices": [0]}]
    state["coauthors"] = [{"name": "Charles Babbage", "papers": 2}]
    state["representative_papers"] = {
        "Computing": [{
            "title": "Notes on the Analytical Engine",
            "year": 1843,
            "citations": 42,
            "id": "https://openalex.org/W1",
        }]
    }

    monkeypatch.setattr(llm, "run_structured_agent", lambda *_args, **_kwargs: (
        None,
        {
            "agent": "report_agent",
            "status": "fallback",
            "model": "deepseek-v4-flash",
            "tier": "fast",
            "plannedTier": "fast",
            "attemptedModels": ["deepseek-v4-flash"],
            "escalated": False,
            "reasons": ["invalid_report_citations"],
        },
    ))

    result = generate_profile_report(state)

    assert "[1]" in result["profile_summary"]
    assert result["profile_summary_i18n"] == {}
    assert result["profile_evidence"][0]["type"] == "metric"
    assert any(item["type"] == "paper" for item in result["profile_evidence"])
    assert result["agent_runs"][0]["status"] == "fallback"


def test_generate_profile_report_returns_bilingual_agent_summary(monkeypatch):
    import llm

    state = default_state()
    state["target_author_id"] = "A0"
    state["target_author_profile"] = {
        "display_name": "Ada Lovelace",
        "last_known_institutions": [{"display_name": "Analytical Engine Lab"}],
    }
    state["citation_summary"] = {"total_papers": 3, "total_citations": 42, "h_index": 2}
    state["topic_clusters"] = [{"topic": "Computing", "weight": 0.7, "paper_indices": [0]}]
    state["coauthors"] = [{"name": "Charles Babbage", "papers": 2}]
    state["representative_papers"] = {}
    monkeypatch.setattr(llm, "run_structured_agent", lambda *_args, **_kwargs: (
        llm.ProfileReportOutput(
            summary_zh="该学者围绕可计算方法开展研究，论文与引用指标见依据 [1]。其方向由论文主题支持 [2]，合作网络也有共同署名记录 [3]。",
            summary_en="The scholar works on computational methods, with publication and citation metrics supported by evidence [1]. The research direction is grounded in paper topics [2], while collaboration patterns are supported by coauthorship records [3].",
            evidence_ids=["1", "2", "3"],
            confidence="high",
        ),
        {
            "agent": "report_agent",
            "status": "success",
            "model": "deepseek-v4-flash",
            "tier": "fast",
            "plannedTier": "fast",
            "attemptedModels": ["deepseek-v4-flash"],
            "escalated": False,
            "reasons": [],
        },
    ))

    result = generate_profile_report(state)

    assert result["profile_summary_i18n"]["zh"].startswith("该学者")
    assert result["profile_summary_i18n"]["en"].startswith("The scholar")
    assert result["agent_runs"][0]["model"] == "deepseek-v4-flash"


def test_format_web_payload_includes_author_id_evidence_and_top_50_papers():
    state = default_state()
    state["target_author_id"] = "A0"
    state["target_author_profile"] = {
        "id": "A0",
        "display_name": "Ada",
        "last_known_institutions": [{"id": "I1", "display_name": "Analytical University"}],
        "affiliations": [{
            "institution": {"id": "I1", "display_name": "Analytical University"},
            "years": [2059],
        }],
    }
    state["citation_summary"] = {"total_papers": 60, "total_citations": 100, "h_index": 5}
    state["deduped_works"] = [
        {
            "id": f"W{i}",
            "title": f"Paper {i}",
            "publication_year": 2000 + i,
            "cited_by_count": i,
            "authorships": [{
                "author": {"id": "A0"},
                "raw_affiliation_strings": [
                    "Analytical Engine Research Institute, Analytical University"
                ],
            }],
        }
        for i in range(60)
    ]
    state["coauthors"] = [{
        "id": "A1",
        "name": "Charles Babbage",
        "institution": "Analytical University",
        "papers": 2,
    }]
    state["profile_summary"] = "Summary [1]"
    state["profile_evidence"] = [{"id": "1", "type": "metric", "text": "Metric evidence"}]
    state["data_audit"] = {"status": "partial", "collectedWorks": 60}
    state["evidence_review"] = {"publishable": True, "summaryConfidence": "medium"}
    state["profile_summary_i18n"] = {"zh": "总结 [1]", "en": "Summary [1]"}
    state["agent_plan"] = {"topic_tier": "fast"}
    state["agent_runs"] = [{
        "agent": "topic_agent",
        "status": "success",
        "model": "deepseek-v4-flash",
        "tier": "fast",
        "plannedTier": "fast",
        "attemptedModels": ["deepseek-v4-flash"],
        "escalated": False,
        "reasons": [],
    }]

    result = format_web_payload(state)
    payload = result["web_payload"]

    assert payload["authorId"] == "A0"
    assert payload["profileEvidence"] == state["profile_evidence"]
    assert payload["dataAudit"] == state["data_audit"]
    assert payload["evidenceReview"] == state["evidence_review"]
    assert payload["profileSummaryI18n"] == state["profile_summary_i18n"]
    assert payload["agentAnalysis"]["status"] == "completed"
    assert payload["agentAnalysis"]["runs"][0]["agent"] == "topic_agent"
    assert payload["affiliationEvidence"]["publicationAffiliationStatements"][0] == {
        "text": "Analytical Engine Research Institute, Analytical University",
        "years": list(range(2059, 1999, -1)),
    }
    assert payload["affiliationEvidence"]["verifiedEmployment"] is None
    assert "professionalIdentity" not in payload
    assert payload["department"] == ""
    assert payload["coauthors"][0]["id"] == "A1"
    assert len(payload["topCitedPapers"]) == 50
    assert payload["topCitedPapers"][0]["title"] == "Paper 59"


def test_workflow_uses_multi_source_adjudication_and_review_nodes():
    node_names = [name for name, _ in NODES]

    assert node_names[0] == "fetch_profile"
    assert "collect_works" in node_names
    assert "collect_crossref" in node_names
    assert "collect_dblp" in node_names
    assert "collect_google_scholar" in node_names
    assert "adjudicate_sources" in node_names
    assert "collect_orcid_identity" in node_names
    assert "resolve_work_identity" in node_names
    assert "plan_agents" in node_names
    assert "agent_analyze_trajectory" in node_names
    assert "agent_review_report" in node_names
    assert "review_evidence" in node_names
    assert node_names.index("adjudicate_sources") < node_names.index("plan_agents")
    assert node_names.index("collect_crossref") < node_names.index("collect_dblp")
    assert node_names.index("collect_dblp") < node_names.index("collect_google_scholar")
    assert node_names.index("collect_google_scholar") < node_names.index("adjudicate_sources")
    assert node_names.index("adjudicate_sources") < node_names.index("resolve_work_identity")
    assert node_names.index("resolve_work_identity") < node_names.index("plan_agents")
    assert node_names.index("plan_agents") < node_names.index("analyze_citations")
    assert node_names.index("generate_report") < node_names.index("agent_review_report")
    assert node_names.index("review_evidence") < node_names.index("format_payload")


def test_workflow_parallel_analysis_branches_join_before_report(monkeypatch):
    import crossref
    import openalex
    from workflow import graph

    monkeypatch.setattr(openalex, "get_author", lambda _author_id, **_kwargs: {
        "id": "A0",
        "display_name": "Empty Scholar",
        "works_count": 0,
        "last_known_institutions": [],
    })
    monkeypatch.setattr(openalex, "get_works", lambda _author_id, **_kwargs: ([], []))
    monkeypatch.setattr(crossref, "verify_dois", lambda _dois: ({}, {
        "requested": 0,
        "verified": 0,
        "missing": 0,
        "failed": 0,
    }))
    state = default_state()
    state["target_author_id"] = "A0"

    result = graph.invoke(state)

    assert result["web_payload"]["name"] == "Empty Scholar"
    assert result["evidence_review"]["publishable"] is True
    assert result["profile_evidence"][0]["type"] == "metric"


def test_default_state_has_multi_source_fields_without_semantic_scholar():
    state = default_state()

    assert "raw_works" in state
    assert state["target_author_ids"] == []
    assert state["identity_audit"] == {}
    assert state["orcid_works"] == []
    assert state["orcid_audit"] == {}
    assert "deduped_works" in state
    assert state["source_works"] == {}
    assert state["source_audit"] == {}
    assert state["adjudicated_works"] == []
    assert state["data_audit"] == {}
    assert state["agent_plan"] == {}
    assert state["agent_runs"] == []
    assert state["trajectory_analysis"] == {}
    assert state["profile_summary_i18n"] == {}
    assert state["agent_review"] == {}
    assert state["evidence_review"] == {}
    assert "query_name" not in state
    assert "optional_institution" not in state
    assert "candidate_authors" not in state
    assert "semantic_works" not in state
