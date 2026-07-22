from nodes import (
    analyze_coauthors,
    build_collaboration_graph,
    collect_works,
    dedup_authors,
    format_web_payload,
    generate_profile_report,
)
from state import default_state
from workflow import NODES


def test_dedup_authors_keeps_same_name_different_ids_separate():
    candidates = [
        {
            "id": "A1",
            "display_name": "Haofen Wang",
            "works_count": 10,
            "cited_by_count": 100,
            "summary_stats": {"h_index": 5},
            "last_known_institutions": [{"display_name": "Tongji University"}],
        },
        {
            "id": "A2",
            "display_name": "haofen wang",
            "works_count": 7,
            "cited_by_count": 80,
            "summary_stats": {"h_index": 4},
            "last_known_institutions": [{"display_name": "Tongji University"}],
        },
    ]

    merged = dedup_authors(candidates)

    assert len(merged) == 2
    assert [author["id"] for author in merged] == ["A1", "A2"]
    assert all(author["merged_count"] == 1 for author in merged)


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
    monkeypatch.setattr(openalex, "get_works", lambda _author_id: ([{"id": "W1"}], []))

    result = collect_works(state)

    assert result["raw_works"] == [{"id": "W1"}]
    assert result["works_complete"] is True


def test_collect_works_marks_partial_fetch_for_quality_gate(monkeypatch):
    import openalex

    state = default_state()
    state["target_author_id"] = "A0"
    state["target_author_profile"] = {"works_count": 2}
    monkeypatch.setattr(
        openalex,
        "get_works",
        lambda _author_id: ([{"id": "W1"}], ["OpenAlex partial fetch"]),
    )

    result = collect_works(state)

    assert result["works_complete"] is False
    assert "OpenAlex partial fetch" in result["warnings"]


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

    monkeypatch.setattr(llm, "report_llm", lambda _data: "No evidence markers here.")

    result = generate_profile_report(state)

    assert "[1]" in result["profile_summary"]
    assert result["profile_evidence"][0]["type"] == "metric"
    assert any(item["type"] == "paper" for item in result["profile_evidence"])


def test_format_web_payload_includes_author_id_evidence_and_top_50_papers():
    state = default_state()
    state["target_author_id"] = "A0"
    state["target_author_profile"] = {"display_name": "Ada", "last_known_institutions": []}
    state["citation_summary"] = {"total_papers": 60, "total_citations": 100, "h_index": 5}
    state["deduped_works"] = [
        {"id": f"W{i}", "title": f"Paper {i}", "publication_year": 2000 + i, "cited_by_count": i}
        for i in range(60)
    ]
    state["profile_summary"] = "Summary [1]"
    state["profile_evidence"] = [{"id": "1", "type": "metric", "text": "Metric evidence"}]

    result = format_web_payload(state)
    payload = result["web_payload"]

    assert payload["authorId"] == "A0"
    assert payload["profileEvidence"] == state["profile_evidence"]
    assert len(payload["topCitedPapers"]) == 50
    assert payload["topCitedPapers"][0]["title"] == "Paper 59"


def test_workflow_uses_openalex_only_nodes():
    node_names = [name for name, _ in NODES]

    assert node_names[0] == "fetch_profile"
    assert "collect_works" in node_names
    assert "resolve_author" not in node_names
    assert "collect_semantic" not in node_names
    assert "merge_sources" not in node_names


def test_default_state_has_no_semantic_scholar_fields():
    state = default_state()

    assert "raw_works" in state
    assert "deduped_works" in state
    assert "query_name" not in state
    assert "optional_institution" not in state
    assert "candidate_authors" not in state
    assert "semantic_works" not in state
    assert "merged_works" not in state
