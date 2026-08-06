import requests

import google_scholar


class FakeResponse:
    def __init__(self, payload, *, status_code=200):
        self.payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError("request failed")

    def json(self):
        return self.payload


def _work():
    return {
        "title": "ImageNet: A large-scale hierarchical image database",
        "publication_year": 2009,
        "cited_by_count": 100000,
    }


def test_google_scholar_skips_cleanly_without_serpapi_key(monkeypatch):
    monkeypatch.delenv("SERPAPI_API_KEY", raising=False)

    records, audit = google_scholar.verify_author_works(
        {"display_name": "Fei-Fei Li"},
        [_work()],
    )

    assert records == []
    assert audit["status"] == "disabled"
    assert audit["reason"] == "api_key_not_configured"


def test_google_scholar_anchors_author_profile_before_matching_works(monkeypatch):
    monkeypatch.setenv("SERPAPI_API_KEY", "test-key")
    engines = []

    def fake_get(_url, *, params, timeout):
        assert timeout == google_scholar.TIMEOUT
        engines.append(params["engine"])
        assert params["api_key"] == "test-key"
        if params["engine"] == "google_scholar":
            return FakeResponse({
                "organic_results": [{
                    "result_id": "anchor",
                    "title": _work()["title"],
                    "link": "https://example.org/imagenet",
                    "publication_info": {
                        "summary": "J Deng, W Dong, R Socher, LJ Li, K Li, L Fei-Fei - CVPR, 2009",
                        "authors": [
                            {"name": "L Fei-Fei", "author_id": "correct-profile"},
                            {"name": "K Li", "author_id": "wrong-profile"},
                        ],
                    },
                }],
            })
        return FakeResponse({
            "author": {
                "name": "Li Fei-Fei",
                "affiliations": "Professor of Computer Science, Stanford University",
            },
            "articles": [
                {
                    "citation_id": "correct-profile:imagenet",
                    "title": _work()["title"],
                    "year": "2009",
                    "cited_by": {"value": 101379},
                    "link": "https://scholar.google.com/example",
                },
                {
                    "citation_id": "correct-profile:other",
                    "title": "An unrelated article",
                    "year": "2024",
                },
            ],
        })

    monkeypatch.setattr(google_scholar._SESSION, "get", fake_get)

    records, audit = google_scholar.verify_author_works(
        {
            "display_name": "Fei-Fei Li",
            "last_known_institutions": [{"display_name": "Stanford University"}],
        },
        [_work()],
    )

    assert engines == ["google_scholar", "google_scholar_author"]
    assert audit["status"] == "available"
    assert audit["matched"] == 1
    assert audit["profileId"] == "correct-profile"
    assert audit["verificationMethod"] == "paper_anchor_profile"
    assert records[0]["cited_by"] == 101379


def test_google_scholar_does_not_accept_name_only_results(monkeypatch):
    monkeypatch.setenv("SERPAPI_API_KEY", "test-key")
    monkeypatch.setattr(
        google_scholar._SESSION,
        "get",
        lambda *_args, **_kwargs: FakeResponse({
            "organic_results": [{
                "result_id": "namesake",
                "title": "A Different Person's Paper",
                "publication_info": {
                    "summary": "F Li - Vision Journal, 2024",
                    "authors": [{"name": "F Li", "author_id": "namesake-profile"}],
                },
            }],
        }),
    )

    records, audit = google_scholar.verify_author_works(
        {"display_name": "Fei-Fei Li"},
        [_work()],
    )

    assert records == []
    assert audit["status"] == "identity_unresolved"
    assert audit["profilesChecked"] == 0


def test_google_scholar_keeps_exact_paper_author_anchor_without_profile_id(monkeypatch):
    monkeypatch.setenv("SERPAPI_API_KEY", "test-key")
    monkeypatch.setattr(
        google_scholar._SESSION,
        "get",
        lambda *_args, **_kwargs: FakeResponse({
            "organic_results": [{
                "result_id": "anchor-only",
                "title": _work()["title"],
                "publication_info": {
                    "summary": "J Deng, W Dong, R Socher, LJ Li, K Li, L Fei-Fei - CVPR, 2009",
                    "authors": [{"name": "L Fei-Fei"}],
                },
            }],
        }),
    )

    records, audit = google_scholar.verify_author_works(
        {"display_name": "Fei-Fei Li"},
        [_work()],
    )

    assert [record["id"] for record in records] == ["anchor-only"]
    assert audit["status"] == "available"
    assert audit["verificationMethod"] == "paper_title_author_anchor"


def test_google_scholar_reports_unavailable_without_leaking_request_details(monkeypatch):
    monkeypatch.setenv("SERPAPI_API_KEY", "test-key")

    def fail(*_args, **_kwargs):
        raise requests.Timeout("timed out")

    monkeypatch.setattr(google_scholar._SESSION, "get", fail)

    records, audit = google_scholar.verify_author_works(
        {"display_name": "Fei-Fei Li"},
        [_work()],
    )

    assert records == []
    assert audit == {
        "status": "unavailable",
        "requested": 1,
        "matched": 0,
        "anchorQueries": 1,
        "successfulRequests": 0,
    }
