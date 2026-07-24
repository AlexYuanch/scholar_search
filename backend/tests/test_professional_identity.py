from professional_identity import build_professional_identity


AUTHOR_ID = "https://openalex.org/A1"


def _authorship(raw_affiliation: str) -> dict:
    return {
        "author": {"id": AUTHOR_ID, "display_name": "Yunfan Gao"},
        "raw_affiliation_strings": [raw_affiliation],
    }


def test_professional_identity_uses_traceable_affiliations_without_inferring_role():
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
    works = [
        {
            "publication_year": 2026,
            "authorships": [
                _authorship(
                    "Shanghai Research Institute for Intelligent Autonomous Systems, "
                    "Tongji University, Shanghai, China"
                ),
            ],
        },
        {
            "publication_year": 2023,
            "authorships": [
                _authorship("School of Computer Science, Fudan University, Shanghai, China"),
            ],
        },
    ]

    identity = build_professional_identity(author, works, [AUTHOR_ID])

    assert identity["currentInstitution"] == "Tongji University"
    assert identity["researchUnit"] == (
        "Shanghai Research Institute for Intelligent Autonomous Systems"
    )
    assert identity["currentAffiliationStatements"] == [{
        "text": (
            "Shanghai Research Institute for Intelligent Autonomous Systems, "
            "Tongji University, Shanghai, China"
        ),
        "years": [2026],
    }]
    assert identity["institutionHistory"] == [
        {"name": "Tongji University", "years": [2026, 2025, 2024]},
        {"name": "Fudan University", "years": [2023, 2022]},
    ]
    assert identity["academicRole"] is None
    assert identity["degreeStatus"] is None
    assert identity["sourceLinks"] == [
        {"label": "OpenAlex", "url": AUTHOR_ID},
        {"label": "ORCID", "url": "https://orcid.org/0000-0002-7932-2752"},
    ]


def test_professional_identity_extracts_department_and_laboratory_from_current_year_only():
    author = {
        "id": AUTHOR_ID,
        "last_known_institutions": [
            {"id": "I1", "display_name": "Tongji University"},
        ],
    }
    works = [
        {
            "publication_year": 2025,
            "authorships": [
                _authorship(
                    "School of Computer Science, Key Laboratory of Data Science, "
                    "Tongji University"
                ),
            ],
        },
        {
            "publication_year": 2024,
            "authorships": [
                _authorship("Department of Computing, Previous University"),
            ],
        },
    ]

    identity = build_professional_identity(author, works, [AUTHOR_ID])

    assert identity["department"] == "School of Computer Science"
    assert identity["laboratory"] == "Key Laboratory of Data Science"
    assert "Previous University" not in identity["currentAffiliationStatements"][0]["text"]
