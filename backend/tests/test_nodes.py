from nodes import (
    adjudicate_sources,
    analyze_coauthors,
    build_collaboration_graph,
    collect_crossref_records,
    collect_works,
    dedup_authors,
    format_web_payload,
    generate_profile_report,
    review_profile_evidence,
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
    assert result["source_works"]["openalex"] == [{"id": "W1"}]
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
    state["data_audit"] = {"status": "partial", "collectedWorks": 60}
    state["evidence_review"] = {"publishable": True, "summaryConfidence": "medium"}

    result = format_web_payload(state)
    payload = result["web_payload"]

    assert payload["authorId"] == "A0"
    assert payload["profileEvidence"] == state["profile_evidence"]
    assert payload["dataAudit"] == state["data_audit"]
    assert payload["evidenceReview"] == state["evidence_review"]
    assert len(payload["topCitedPapers"]) == 50
    assert payload["topCitedPapers"][0]["title"] == "Paper 59"


def test_workflow_uses_multi_source_adjudication_and_review_nodes():
    node_names = [name for name, _ in NODES]

    assert node_names[0] == "fetch_profile"
    assert "collect_works" in node_names
    assert "collect_crossref" in node_names
    assert "adjudicate_sources" in node_names
    assert "review_evidence" in node_names
    assert node_names.index("adjudicate_sources") < node_names.index("analyze_citations")
    assert node_names.index("review_evidence") < node_names.index("format_payload")


def test_workflow_parallel_analysis_branches_join_before_report(monkeypatch):
    import crossref
    import openalex
    from workflow import graph

    monkeypatch.setattr(openalex, "get_author", lambda _author_id: {
        "id": "A0",
        "display_name": "Empty Scholar",
        "works_count": 0,
        "last_known_institutions": [],
    })
    monkeypatch.setattr(openalex, "get_works", lambda _author_id: ([], []))
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
    assert "deduped_works" in state
    assert state["source_works"] == {}
    assert state["source_audit"] == {}
    assert state["adjudicated_works"] == []
    assert state["data_audit"] == {}
    assert state["evidence_review"] == {}
    assert "query_name" not in state
    assert "optional_institution" not in state
    assert "candidate_authors" not in state
    assert "semantic_works" not in state
