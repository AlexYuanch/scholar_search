from affiliation_evidence import build_affiliation_evidence


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
