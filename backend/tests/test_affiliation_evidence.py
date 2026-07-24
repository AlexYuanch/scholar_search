from affiliation_evidence import build_affiliation_evidence, select_primary_affiliation


AUTHOR_ID = "https://openalex.org/A1"


def _authorship(author_id: str, raw_affiliation: str) -> dict:
    return {
        "author": {"id": author_id, "display_name": "Yunfan Gao"},
        "raw_affiliation_strings": [raw_affiliation],
    }


def test_publication_affiliations_never_become_employment_or_role_claims():
    author = {
        "id": AUTHOR_ID,
        "orcid": "https://orcid.org/0000-0002-7932-2752",
        "last_known_institutions": [
            {"id": "I1", "display_name": "Tongji University"},
        ],
        "affiliations": [
            {
                "institution": {"id": "I1", "display_name": "Tongji University"},
                "years": [2026, 2025, 2024],
            },
            {
                "institution": {"id": "I2", "display_name": "Fudan University"},
                "years": [2023, 2022],
            },
        ],
    }
    works = [{
        "publication_year": 2026,
        "authorships": [
            _authorship(
                AUTHOR_ID,
                "Shanghai Research Institute for Intelligent Autonomous Systems, "
                "Tongji University, Shanghai, China",
            ),
        ],
    }]

    evidence = build_affiliation_evidence(author, works, [AUTHOR_ID])

    assert evidence["openAlexAffiliationHistory"] == [
        {"name": "Tongji University", "years": [2026, 2025, 2024]},
        {"name": "Fudan University", "years": [2023, 2022]},
    ]
    assert evidence["primaryAffiliation"] == "Tongji University"
    assert evidence["publicationAffiliationStatements"] == [{
        "text": (
            "Shanghai Research Institute for Intelligent Autonomous Systems, "
            "Tongji University, Shanghai, China"
        ),
        "years": [2026],
    }]
    assert evidence["verifiedEmployment"] is None
    assert evidence["verifiedEducation"] == []
    assert "currentInstitution" not in evidence
    assert "department" not in evidence
    assert "laboratory" not in evidence
    assert "researchUnit" not in evidence
    assert "academicRole" not in evidence
    assert "degreeStatus" not in evidence
    assert evidence["sourceLinks"] == [
        {"label": "OpenAlex", "url": AUTHOR_ID},
        {"label": "ORCID", "url": "https://orcid.org/0000-0002-7932-2752"},
    ]


def test_one_new_paper_does_not_replace_a_multi_year_primary_affiliation():
    assert select_primary_affiliation([
        {"name": "Long-term University", "years": [2024, 2023, 2022, 2021]},
        {"name": "One-off New Institute", "years": [2026]},
    ]) == "Long-term University"


def test_recent_sustained_affiliation_beats_longer_old_affiliation():
    assert select_primary_affiliation([
        {
            "name": "Tongji University",
            "years": [2026, 2025, 2024, 2023, 2022, 2021, 2020, 2019],
        },
        {
            "name": "Shanghai Jiao Tong University",
            "years": [2018, 2015, 2013, 2012, 2011, 2010, 2009, 2008, 2007],
        },
    ]) == "Tongji University"


def test_publication_affiliations_are_scoped_to_the_target_author():
    works = [{
        "publication_year": 2025,
        "authorships": [
            _authorship(AUTHOR_ID, "School of Computer Science, Tongji University"),
            _authorship(
                "https://openalex.org/A2",
                "Key Laboratory of Data Science, Previous University",
            ),
        ],
    }]

    evidence = build_affiliation_evidence(
        {"id": AUTHOR_ID},
        works,
        [AUTHOR_ID],
    )

    assert evidence["publicationAffiliationStatements"] == [{
        "text": "School of Computer Science, Tongji University",
        "years": [2025],
    }]
    assert evidence["verifiedEmployment"] is None
