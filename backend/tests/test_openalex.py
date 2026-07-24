import pytest
import requests


class FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload
        self.headers = {}
        self.text = str(payload)

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} error", response=self)


class FakeSession:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = 0
        self.requests = []

    def get(self, *args, **kwargs):
        self.calls += 1
        self.requests.append((args, kwargs))
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def test_get_retries_retryable_status(monkeypatch):
    import openalex

    session = FakeSession([
        FakeResponse(429, {"error": "rate limited"}),
        FakeResponse(200, {"results": [{"id": "A1"}]}),
    ])
    monkeypatch.setattr(openalex, "_SESSION", session)
    monkeypatch.setattr(openalex.time, "sleep", lambda _seconds: None)

    data = openalex._get("/authors")

    assert data == {"results": [{"id": "A1"}]}
    assert session.calls == 2


def test_get_preserves_upstream_rate_limit_metadata(monkeypatch):
    import openalex

    responses = [FakeResponse(429, {"error": "rate limited"}) for _ in range(3)]
    for response in responses:
        response.headers["Retry-After"] = "17"
    monkeypatch.setattr(openalex, "_SESSION", FakeSession(responses))
    monkeypatch.setattr(openalex.time, "sleep", lambda _seconds: None)

    with pytest.raises(openalex.OpenAlexError) as captured:
        openalex._get("/authors")

    assert captured.value.status_code == 429
    assert captured.value.retry_after == "17"


def test_get_sends_configured_api_key_without_exposing_it(monkeypatch):
    import openalex

    session = FakeSession([requests.ConnectionError("must-not-leak")])
    monkeypatch.setattr(openalex, "_SESSION", session)
    monkeypatch.setattr(openalex, "MAX_RETRIES", 1)
    monkeypatch.setattr(openalex, "OPENALEX_API_KEY", "test-secret-key")

    with pytest.raises(openalex.OpenAlexError) as captured:
        openalex._get("/authors", per_page=1)

    assert session.requests[0][1]["params"]["api_key"] == "test-secret-key"
    assert "test-secret-key" not in str(captured.value)
    assert "must-not-leak" not in str(captured.value)


def test_get_does_not_reuse_stale_status_after_network_failure(monkeypatch):
    import openalex

    monkeypatch.setattr(openalex, "_SESSION", FakeSession([
        FakeResponse(429, {"error": "rate limited"}),
        requests.Timeout("network timeout"),
        requests.Timeout("network timeout"),
    ]))
    monkeypatch.setattr(openalex.time, "sleep", lambda _seconds: None)

    with pytest.raises(openalex.OpenAlexError) as captured:
        openalex._get("/authors")

    assert captured.value.status_code is None
    assert captured.value.retry_after is None


def test_get_works_returns_partial_results_with_warning(monkeypatch):
    import openalex

    session = FakeSession([
        FakeResponse(200, {
            "results": [{"id": "W1", "title": "First"}],
            "meta": {"next_cursor": "next"},
        }),
        requests.Timeout("slow upstream"),
        requests.Timeout("slow upstream"),
        requests.Timeout("slow upstream"),
    ])
    monkeypatch.setattr(openalex, "_SESSION", session)
    monkeypatch.setattr(openalex.time, "sleep", lambda _seconds: None)

    works, warnings = openalex.get_works("A1")

    assert works == [{"id": "W1", "title": "First"}]
    assert warnings
    assert "部分论文" in warnings[0]


def test_chinese_name_query_adds_both_pinyin_orders():
    import openalex

    variants = openalex._name_query_variants("陈丽娜")

    assert variants[0] == "陈丽娜"
    assert "Chen Lina" in variants
    assert "Lina Chen" in variants


def test_chinese_name_query_falls_back_when_pypinyin_is_unavailable(monkeypatch):
    import openalex

    monkeypatch.setattr(openalex, "lazy_pinyin", None)
    monkeypatch.setattr(openalex, "Style", None)
    monkeypatch.setattr(openalex, "PINYIN_AVAILABLE", False)

    assert openalex._name_query_variants("陈丽娜") == ["陈丽娜"]


def test_search_authors_combines_variants_and_deduplicates_by_id(monkeypatch):
    import openalex

    responses = {
        "陈丽娜": [{"id": "A1", "display_name": "陈丽娜", "last_known_institutions": []}],
        "Chen Lina": [{"id": "A2", "display_name": "Lina Chen", "last_known_institutions": []}],
        "Lina Chen": [
            {"id": "A2", "display_name": "Lina Chen", "last_known_institutions": []},
            {
                "id": "A3",
                "display_name": "Lina Chen",
                "last_known_institutions": [{"display_name": "Zhejiang Normal University"}],
            },
        ],
    }

    def fake_get(_endpoint, **params):
        return {"results": responses[params["filter"].split(":", 1)[1]]}

    monkeypatch.setattr(openalex, "_get", fake_get)

    authors = openalex.search_authors("陈丽娜")

    assert [author["id"] for author in authors] == ["A3", "A1", "A2"]


def test_author_identity_fingerprint_uses_works_coauthors_and_topics(monkeypatch):
    import openalex

    monkeypatch.setattr(openalex, "_get", lambda _endpoint, **_params: {
        "results": [
            {
                "id": "W1",
                "doi": "https://doi.org/10.1000/one",
                "publication_year": 2025,
                "authorships": [
                    {"author": {"id": "A1"}},
                    {"author": {"id": "C1"}},
                ],
                "primary_topic": {"id": "T1"},
                "topics": [{"id": "T1"}, {"id": "T2"}],
            },
            {
                "id": "W2",
                "publication_year": 2026,
                "authorships": [{"author": {"id": "C2"}}],
                "topics": [{"id": "T2"}],
            },
        ]
    })

    fingerprint = openalex.get_author_identity_fingerprint("A1")

    assert fingerprint["work_ids"] == ["W2", "https://doi.org/10.1000/one"]
    assert fingerprint["coauthor_ids"] == ["C1", "C2"]
    assert fingerprint["topic_ids"] == ["T1", "T2"]
    assert fingerprint["publication_years"] == [2025, 2026]
