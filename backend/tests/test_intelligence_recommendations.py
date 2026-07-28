from intelligence_recommendations import (
    CollaboratorMetrics,
    CompetitorMetrics,
    NarrativeContext,
    PeerMetrics,
    ReferenceMetrics,
    assign_reference_angles,
    collaborator_explanation,
    competitor_explanation,
    peer_explanation,
    reference_explanation,
)


def _context() -> NarrativeContext:
    return NarrativeContext(
        identity_zh="候选学者（示例大学）",
        identity_en="Candidate Scholar at Example University",
        focus_zh="目标学者",
        focus_en="Focus Scholar",
        topics_zh="知识图谱、自然语言处理",
        topics_en="Knowledge Graphs and Natural Language Processing",
        representative_title="A Representative Work",
        representative_year=2024,
    )


def _reference_metrics(**overrides) -> ReferenceMetrics:
    values = {
        "recent_works": 4,
        "downstream": 0.2,
        "continuity": 20.0,
        "impact": 20.0,
        "topic_overlap": 0.2,
        "recent_overlap": 0.2,
        "sustained_topics": 2,
        "longest_span": 5,
    }
    values.update(overrides)
    return ReferenceMetrics(**values)


def test_reference_angles_are_deterministic_and_do_not_mutate_inputs():
    metrics = {
        "topic": _reference_metrics(topic_overlap=0.9),
        "recent": _reference_metrics(recent_overlap=0.8),
        "downstream": _reference_metrics(downstream=0.9),
    }

    first = assign_reference_angles(metrics)
    second = assign_reference_angles(metrics)

    assert {key: value.angle for key, value in first.items()} == {
        "topic": "topic_overlap",
        "recent": "recent_overlap",
        "downstream": "downstream",
    }
    assert first == second
    assert all(value.angle is None for value in metrics.values())


def test_reference_explanation_uses_selected_evidence_and_representative_work():
    explanation = reference_explanation(
        _context(),
        _reference_metrics(topic_overlap=0.47, angle="topic_overlap"),
    )

    assert "候选学者（示例大学）" in explanation["zh"]
    assert "目标学者" in explanation["zh"]
    assert "《A Representative Work》（2024）" in explanation["zh"]
    assert "方向重合约 47%" in explanation["zh"]
    assert "Candidate Scholar at Example University" in explanation["en"]
    assert "topic overlap is about 47%" in explanation["en"]


def test_each_recommendation_type_explains_its_own_decision_evidence():
    context = _context()
    peer = peer_explanation(
        context,
        PeerMetrics(recent_overlap=0.7, temporal_overlap=0.2),
    )
    collaborator = collaborator_explanation(
        context,
        CollaboratorMetrics(direct_count=0, shared_collaborator_count=2),
    )
    competitor = competitor_explanation(
        context,
        CompetitorMetrics(
            direct_count=0,
            problem_similarity=0.31,
            method_similarity=0.24,
        ),
    )

    assert "近期成果" in peer["zh"]
    assert "70%" in peer["zh"]
    assert "没有合著论文" in collaborator["zh"]
    assert "2 位共同合作者" in collaborator["zh"]
    assert "问题表述重合约 31%" in competitor["zh"]
    assert "潜在选题重合，不是竞争关系认定" in competitor["zh"]
    assert len({peer["zh"], collaborator["zh"], competitor["zh"]}) == 3
