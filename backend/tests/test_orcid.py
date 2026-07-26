from orcid import normalize_orcid, parse_orcid_works


def test_normalize_orcid_accepts_public_url():
    assert normalize_orcid("https://orcid.org/0000-0001-5947-1374") == "0000-0001-5947-1374"


def test_parse_orcid_works_extracts_doi_title_and_year():
    payload = {
        "group": [{
            "work-summary": [{
                "title": {"title": {"value": "Urban Computing Study"}},
                "publication-date": {"year": {"value": "2024"}},
                "external-ids": {
                    "external-id": [{
                        "external-id-type": "doi",
                        "external-id-value": "10.1000/URBAN",
                    }],
                },
            }],
        }],
    }

    assert parse_orcid_works(payload) == [{
        "doi": "10.1000/urban",
        "title": "Urban Computing Study",
        "year": 2024,
    }]
