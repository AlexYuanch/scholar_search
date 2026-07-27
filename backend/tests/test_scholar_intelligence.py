from copy import deepcopy
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from auth import generate_token, hash_password, hash_token
from intelligence_repository import save_intelligence_feedback
from main import app
from repository import InMemoryRepository
from research_graph import build_research_graph_batch
from research_graph_repository import apply_research_graph_batch
from scholar_intelligence import (
    build_scholar_intelligence,
    compare_scholar_intelligence,
)


FOCUS = "https://openalex.org/A-INTEL-FOCUS"
NORTH = "https://openalex.org/A-INTEL-NORTH"
WEAK = "https://openalex.org/A-INTEL-WEAK"
UNRELATED = "https://openalex.org/A-INTEL-UNRELATED"
SHIFT = "https://openalex.org/A-INTEL-SHIFT"
COLLABORATOR = "https://openalex.org/A-INTEL-COLLABORATOR"
ONE_OFF = "https://openalex.org/A-INTEL-ONE-OFF"
COMPETITOR = "https://openalex.org/A-INTEL-COMPETITOR"


def _inverted(text: str) -> dict:
    result = {}
    for index, word in enumerate(text.split()):
        result.setdefault(word, []).append(index)
    return result


def _author(author_id: str, name: str, institution: str) -> dict:
    institution_id = f"https://openalex.org/I-{institution.replace(' ', '-').upper()}"
    return {
        "id": author_id,
        "display_name": name,
        "works_count": 0,
        "cited_by_count": 0,
        "summary_stats": {"h_index": 0},
        "affiliations": [{
            "institution": {
                "id": institution_id,
                "display_name": institution,
                "country_code": "CN",
            },
            "years": list(range(2018, 2027)),
        }],
        "last_known_institutions": [{
            "id": institution_id,
            "display_name": institution,
            "country_code": "CN",
        }],
    }


def _authorships(
    author_id: str,
    name: str,
    *,
    role: str = "first",
    coauthors: list[tuple[str, str]] | None = None,
) -> list[dict]:
    coauthors = coauthors or []
    target = {
        "author_position": role,
        "is_corresponding": role in {"first", "last"},
        "author": {"id": author_id, "display_name": name},
        "institutions": [],
    }
    others = [
        {
            "author_position": "middle",
            "author": {"id": other_id, "display_name": other_name},
            "institutions": [],
        }
        for other_id, other_name in coauthors
    ]
    if role == "middle":
        return [
            {
                "author_position": "first",
                "author": {
                    "id": f"{author_id}-LEAD",
                    "display_name": f"{name} Lead",
                },
                "institutions": [],
            },
            target,
            *others,
        ]
    return [target, *others]


def _work(
    author_id: str,
    name: str,
    index: int,
    *,
    year: int,
    topic: str,
    citations: int,
    role: str = "first",
    coauthors: list[tuple[str, str]] | None = None,
    problem: str = "reliable graph retrieval",
    method: str = "neural graph retrieval framework",
    referenced_works: list[str] | None = None,
) -> dict:
    source_id = f"https://openalex.org/W-{author_id.rsplit('-', 1)[-1]}-{index}"
    abstract = (
        f"We address the problem of {problem}. "
        f"We propose a {method}. "
        "Results show reproducible improvements."
    )
    topic_id = f"https://openalex.org/T-{topic.replace(' ', '-').upper()}"
    return {
        "id": source_id,
        "doi": f"10.5555/{author_id.rsplit('-', 1)[-1].lower()}.{index}",
        "title": f"{topic} study {index}",
        "publication_year": year,
        "publication_date": f"{year}-05-01",
        "updated_date": f"{year}-06-01T00:00:00Z",
        "cited_by_count": citations,
        "abstract_inverted_index": _inverted(abstract),
        "referenced_works": referenced_works or [],
        "authorships": _authorships(
            author_id,
            name,
            role=role,
            coauthors=coauthors,
        ),
        "primary_topic": {
            "id": topic_id,
            "display_name": topic,
            "score": 0.95,
        },
        "topics": [{
            "id": topic_id,
            "display_name": topic,
            "score": 0.95,
        }],
        "primary_location": {"source": {"display_name": "Evidence Journal"}},
        "type": "article",
        "language": "en",
    }


def _apply(
    repository: InMemoryRepository,
    author_id: str,
    name: str,
    institution: str,
    works: list[dict],
) -> None:
    author = _author(author_id, name, institution)
    author["works_count"] = len(works)
    author["cited_by_count"] = sum(work["cited_by_count"] for work in works)
    apply_research_graph_batch(
        repository,
        build_research_graph_batch(author, works),
        force_rebuild=False,
        warnings=[],
    )


def _rich_repository() -> InMemoryRepository:
    repository = InMemoryRepository()
    shared = [(COLLABORATOR, "Alex Kim")]
    focus_works = [
        _work(
            FOCUS,
            "Focus Scholar",
            index,
            year=2019 + index,
            topic="Knowledge Graph Retrieval",
            citations=8 + index * 3,
            coauthors=shared if index in {1, 3} else (
                [(ONE_OFF, "Alex Kim")] if index == 4 else []
            ),
        )
        for index in range(6)
    ]
    focus_works.append(_work(
        FOCUS,
        "Focus Scholar",
        90,
        year=2018,
        topic="Quantum Materials",
        citations=5000,
        role="middle",
        problem="quantum phase transitions",
        method="spectroscopy experiment",
    ))
    _apply(repository, FOCUS, "Focus Scholar", "Graph University", focus_works)

    north_ids = [
        f"https://openalex.org/W-NORTH-{index}"
        for index in range(8)
    ]
    north_works = []
    for index, source_id in enumerate(north_ids):
        work = _work(
            NORTH,
            "Reference Scholar",
            index,
            year=2017 + index,
            topic="Knowledge Graph Retrieval",
            citations=35 + index * 5,
            role="last" if index % 2 else "first",
            referenced_works=[north_ids[index - 1]] if index else [],
        )
        work["id"] = source_id
        work["doi"] = f"10.5555/north.{index}"
        north_works.append(work)
    _apply(repository, NORTH, "Reference Scholar", "Reference Institute", north_works)

    weak_works = [
        _work(
            WEAK,
            "Many Papers Scholar",
            index,
            year=2014 + index,
            topic="Knowledge Graph Retrieval",
            citations=index % 3,
            role="middle",
        )
        for index in range(12)
    ]
    _apply(repository, WEAK, "Many Papers Scholar", "Volume Lab", weak_works)

    unrelated_works = [
        _work(
            UNRELATED,
            "Alex Kim",
            index,
            year=2019 + index,
            topic="Quantum Materials",
            citations=10000 + index,
            problem="quantum phase transitions",
            method="spectroscopy experiment",
        )
        for index in range(6)
    ]
    _apply(repository, UNRELATED, "Alex Kim", "Physics University", unrelated_works)

    shift_works = [
        _work(
            SHIFT,
            "Short Shift Scholar",
            index,
            year=2022 if index < 3 else 2025,
            topic="Computer Vision" if index < 3 else "Knowledge Graph Retrieval",
            citations=4,
        )
        for index in range(6)
    ]
    _apply(repository, SHIFT, "Short Shift Scholar", "Shift Lab", shift_works)

    collaborator_works = [
        deepcopy(focus_works[1]),
        deepcopy(focus_works[3]),
        _work(
            COLLABORATOR,
            "Alex Kim",
            20,
            year=2024,
            topic="Graph Data Systems",
            citations=6,
            problem="reliable graph retrieval",
            method="distributed graph data platform",
        ),
        _work(
            COLLABORATOR,
            "Alex Kim",
            21,
            year=2025,
            topic="Knowledge Graph Retrieval",
            citations=7,
            problem="reliable graph retrieval",
            method="distributed graph data platform",
        ),
    ]
    _apply(
        repository,
        COLLABORATOR,
        "Alex Kim",
        "Graph University",
        collaborator_works,
    )

    one_off_works = [deepcopy(focus_works[4])] + [
        _work(
            ONE_OFF,
            "Alex Kim",
            30 + index,
            year=2023 + index,
            topic="Knowledge Graph Retrieval",
            citations=3,
            problem="independent graph curation",
            method="manual graph audit protocol",
        )
        for index in range(3)
    ]
    _apply(repository, ONE_OFF, "Alex Kim", "One Off Institute", one_off_works)

    competitor_works = [
        _work(
            COMPETITOR,
            "Potential Peer",
            index,
            year=2021 + index,
            topic="Knowledge Graph Retrieval",
            citations=12 + index,
            problem="reliable graph retrieval",
            method="neural graph retrieval framework",
        )
        for index in range(5)
    ]
    _apply(
        repository,
        COMPETITOR,
        "Potential Peer",
        "Competing Institute",
        competitor_works,
    )
    return repository


def _recommendation_ids(result: dict) -> set[str]:
    return {
        item["author_id"]
        for rows in result["recommendations"].values()
        for item in rows
    }


def test_data_insufficient_and_new_scholar_return_explicit_unknown():
    repository = InMemoryRepository()
    result = build_scholar_intelligence(repository, FOCUS)

    assert result["source"] == "dynamic_research_graph"
    assert result["confidence"]["level"] == "insufficient"
    assert result["dimensions"]["academic_quality"]["status"] == "insufficient"
    assert result["dimensions"]["academic_quality"]["conclusion"]["zh"] == "无法可靠判断"
    assert result["recommendations"]["north_stars"] == []


def test_scholar_seen_only_as_graph_neighbor_is_not_treated_as_complete():
    repository = _rich_repository()
    repository._research_graph_store["sync"].pop(FOCUS)

    result = build_scholar_intelligence(repository, FOCUS)

    assert result["confidence"]["level"] == "insufficient"
    assert result["dimensions"]["academic_quality"]["status"] == "insufficient"
    assert result["dimensions"]["continuity"]["conclusion"]["zh"] == "无法可靠判断"


def test_field_references_exclude_highly_cited_cross_field_namesake():
    result = build_scholar_intelligence(_rich_repository(), FOCUS, limit=20)

    assert [topic["name"] for topic in result["field"]["topics"]] == [
        "Knowledge Graph Retrieval"
    ]
    assert NORTH in {
        item["author_id"]
        for item in result["recommendations"]["north_stars"]
    }
    assert UNRELATED not in _recommendation_ids(result)
    same_names = {
        item["author_id"]
        for rows in result["recommendations"].values()
        for item in rows
        if item["name"] == "Alex Kim"
    }
    assert UNRELATED not in same_names
    assert COLLABORATOR in same_names
    assert f"{WEAK}-LEAD" not in _recommendation_ids(result)
    assert all(
        team["name"] != "Physics University"
        for team in result["teams"]["field_teams"]
    )


def test_paper_volume_and_raw_citations_do_not_replace_quality_or_relevance():
    result = build_scholar_intelligence(_rich_repository(), FOCUS, limit=20)
    north = build_scholar_intelligence(_rich_repository(), NORTH)
    weak = build_scholar_intelligence(_rich_repository(), WEAK)

    assert (
        north["dimensions"]["academic_quality"]["index"]
        > weak["dimensions"]["academic_quality"]["index"]
    )
    assert (
        result["representative_works"][0]["source_id"]
        != "https://openalex.org/W-FOCUS-90"
    )
    assert all(
        item["author_id"] != UNRELATED
        for item in result["field_reference_list"]["items"]
    )
    representative_ids = {
        item["id"]
        for item in result["representative_works"]
    }
    style_evidence = next(
        item
        for item in result["dimensions"]["topic_style"]["evidence"]
        if item["code"] == "classified_works"
    )
    assert style_evidence["paper_ids"]
    assert set(style_evidence["paper_ids"]).issubset(representative_ids)


def test_short_term_topic_change_is_not_counted_as_long_term_continuity():
    repository = _rich_repository()
    focus = build_scholar_intelligence(repository, FOCUS)
    shift = build_scholar_intelligence(repository, SHIFT)

    assert (
        focus["dimensions"]["continuity"]["index"]
        > shift["dimensions"]["continuity"]["index"]
    )
    sustained_evidence = next(
        item
        for item in shift["dimensions"]["continuity"]["evidence"]
        if item["code"] == "sustained_topics"
    )
    assert sustained_evidence["value"] == 0


def test_collaborators_and_potential_competitors_are_disjoint_and_one_off_is_rejected():
    result = build_scholar_intelligence(_rich_repository(), FOCUS, limit=20)
    collaborators = {
        item["author_id"]
        for item in result["recommendations"]["potential_collaborators"]
    }
    competitors = {
        item["author_id"]
        for item in result["recommendations"]["potential_competitors"]
    }

    assert COLLABORATOR in collaborators
    assert COMPETITOR in competitors
    assert collaborators.isdisjoint(competitors)
    assert ONE_OFF not in collaborators
    assert f"{WEAK}-LEAD" not in competitors
    competitor = next(
        item
        for item in result["recommendations"]["potential_competitors"]
        if item["author_id"] == COMPETITOR
    )
    assert "潜在" in competitor["explanation"]["zh"]


def test_ranking_is_stable_for_the_same_graph_snapshot():
    repository = _rich_repository()

    first = build_scholar_intelligence(repository, FOCUS, limit=20)
    second = build_scholar_intelligence(repository, FOCUS, limit=20)

    for key in first["recommendations"]:
        assert [
            (item["author_id"], item["index"])
            for item in first["recommendations"][key]
        ] == [
            (item["author_id"], item["index"])
            for item in second["recommendations"][key]
        ]


def test_scholar_and_team_comparisons_use_graph_evidence():
    repository = _rich_repository()

    scholar = compare_scholar_intelligence(
        repository,
        FOCUS,
        NORTH,
        mode="scholar",
    )
    team = compare_scholar_intelligence(
        repository,
        FOCUS,
        NORTH,
        mode="team",
    )

    assert scholar["status"] == "available"
    assert {row["key"] for row in scholar["dimensions"]} == {
        "academic_quality",
        "continuity",
        "impact",
    }
    assert team["status"] == "available"
    assert team["left"]["name"] == "Graph University"
    assert team["right"]["name"] == "Reference Institute"
    assert "绝对团队优劣" in team["conclusion"]["zh"]


def test_feedback_upserts_per_user_without_cross_user_overwrite():
    repository = InMemoryRepository()
    first = save_intelligence_feedback(
        repository,
        user_id="user-a",
        target_author_id=FOCUS,
        candidate_author_id=NORTH,
        analysis_key="north_star",
        verdict="helpful",
        analysis_version="deterministic-graph-v1",
    )
    updated = save_intelligence_feedback(
        repository,
        user_id="user-a",
        target_author_id=FOCUS,
        candidate_author_id=NORTH,
        analysis_key="north_star",
        verdict="inaccurate",
        analysis_version="deterministic-graph-v1",
    )
    other_user = save_intelligence_feedback(
        repository,
        user_id="user-b",
        target_author_id=FOCUS,
        candidate_author_id=NORTH,
        analysis_key="north_star",
        verdict="helpful",
        analysis_version="deterministic-graph-v1",
    )

    assert first["id"] == updated["id"]
    assert updated["verdict"] == "inaccurate"
    assert other_user["id"] != first["id"]


def test_authenticated_intelligence_routes_and_feedback(monkeypatch):
    import main

    repository = _rich_repository()
    user = repository.create_password_user(
        "intelligence-user",
        hash_password("correct horse battery staple"),
    )
    raw_session = generate_token()
    repository.create_user_session(
        user["id"],
        hash_token(raw_session),
        datetime.now(timezone.utc) + timedelta(days=1),
    )
    monkeypatch.setattr(main, "repository", repository)
    monkeypatch.setattr(app.state, "repository", repository)
    client = TestClient(app)
    client.cookies.set("scholar_session", raw_session)

    analysis = client.get(f"/api/authors/{FOCUS}/intelligence")
    field = client.get("/api/intelligence/field", params={"author_id": FOCUS})
    comparison = client.post(
        "/api/intelligence/compare",
        json={"author_ids": [FOCUS, NORTH], "mode": "scholar"},
    )
    feedback = client.post(
        "/api/intelligence/feedback",
        json={
            "target_author_id": FOCUS,
            "candidate_author_id": NORTH,
            "analysis_key": "north_star",
            "verdict": "helpful",
        },
    )

    assert analysis.status_code == 200
    assert analysis.json()["source"] == "dynamic_research_graph"
    assert field.status_code == 200
    assert field.json()["field_reference_list"]["is_absolute_ranking"] is False
    assert comparison.status_code == 200
    assert comparison.json()["status"] == "available"
    assert feedback.status_code == 200
    assert feedback.json()["verdict"] == "helpful"
