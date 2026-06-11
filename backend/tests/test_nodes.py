from nodes import dedup_authors
from state import default_state
from workflow import NODES


def test_dedup_authors_merges_same_name_and_institution():
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

    assert len(merged) == 1
    assert merged[0]["works_count"] == 10
    assert merged[0]["cited_by_count"] == 100
    assert merged[0]["summary_stats"]["h_index"] == 5


def test_workflow_uses_openalex_only_nodes():
    node_names = [name for name, _ in NODES]

    assert "collect_works" in node_names
    assert "collect_semantic" not in node_names
    assert "merge_sources" not in node_names


def test_default_state_has_no_semantic_scholar_fields():
    state = default_state()

    assert "raw_works" in state
    assert "deduped_works" in state
    assert "semantic_works" not in state
    assert "merged_works" not in state
