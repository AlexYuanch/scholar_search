import google_scholar


class FakeResponse:
    def raise_for_status(self):
        return None

    def json(self):
        return {
            "organic_results": [
                {
                    "result_id": "abc",
                    "title": "Visual Recognition",
                    "link": "https://example.org/paper",
                    "publication_info": {"summary": "F Li - Vision Journal, 2024"},
                    "inline_links": {"cited_by": {"total": 32}},
                },
                {
                    "result_id": "other",
                    "title": "A Different Person's Paper",
                    "publication_info": {"summary": "A Lee - 2024"},
                },
            ],
        }


def test_google_scholar_skips_cleanly_without_serpapi_key(monkeypatch):
    monkeypatch.delenv("SERPAPI_API_KEY", raising=False)

    records, audit = google_scholar.verify_author_works(
        {"display_name": "Fei-Fei Li"},
        [{"title": "Visual Recognition", "publication_year": 2024}],
    )

    assert records == []
    assert audit["status"] == "disabled"
    assert audit["reason"] == "api_key_not_configured"


def test_google_scholar_only_keeps_existing_title_year_matches(monkeypatch):
    monkeypatch.setenv("SERPAPI_API_KEY", "test-key")
    monkeypatch.setattr(google_scholar._SESSION, "get", lambda *_args, **_kwargs: FakeResponse())

    records, audit = google_scholar.verify_author_works(
        {"display_name": "Fei-Fei Li"},
        [{"title": "Visual Recognition", "publication_year": 2024}],
    )

    assert audit["status"] == "available"
    assert audit["matched"] == 1
    assert records[0]["id"] == "abc"
    assert records[0]["cited_by"] == 32
