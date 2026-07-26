from quality import assess_profile_quality


def _state(*, expected=2, fetched=2, complete=True):
    works = [
        {"id": f"W{i}", "title": f"Paper {i}", "authorships": []}
        for i in range(fetched)
    ]
    return {
        "target_author_profile": {"display_name": "Ada", "works_count": expected},
        "deduped_works": works,
        "works_complete": complete,
        "web_payload": {"name": "Ada", "totalPapers": fetched},
        "warnings": [],
        "errors": [],
    }


def test_complete_profile_is_publishable():
    assessment = assess_profile_quality(_state())

    assert assessment.publishable
    assert assessment.flags == []


def test_failed_evidence_review_blocks_profile_publish():
    state = _state()
    state["evidence_review"] = {"publishable": False}

    assessment = assess_profile_quality(state)

    assert not assessment.publishable
    assert "evidence_review_failed" in assessment.flags


def test_partial_openalex_fetch_never_replaces_latest_profile():
    assessment = assess_profile_quality(_state(expected=20, fetched=8, complete=False))

    assert not assessment.publishable
    assert "partial_works_fetch" in assessment.flags


def test_large_paper_drop_does_not_replace_latest_profile():
    assessment = assess_profile_quality(
        _state(expected=12, fetched=12),
        cached={"payload": {"totalPapers": 30}},
    )

    assert not assessment.publishable
    assert "suspicious_paper_drop" in assessment.flags


def test_documented_identity_exclusions_can_replace_conflated_profile():
    state = _state(expected=30, fetched=12)
    state["identity_audit"] = {
        "collectedWorks": 30,
        "excludedWorks": 18,
        "resolutionMethod": "orcid_anchor",
    }

    assessment = assess_profile_quality(
        state,
        cached={"payload": {"totalPapers": 30}},
    )

    assert assessment.publishable
    assert "identity_conservative_exclusion" in assessment.flags


def test_identity_risk_is_recorded_without_automatic_merge_or_publish_block():
    state = _state()
    state["graph_nodes"] = [
        {"id": "A1", "name": "Hong Gao", "type": "coauthor"},
        {"id": "A2", "name": "Hong Gao", "type": "coauthor"},
    ]

    assessment = assess_profile_quality(state)

    assert assessment.publishable
    assert "coauthor_name_collision" in assessment.flags
