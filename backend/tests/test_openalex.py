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

    def get(self, *args, **kwargs):
        self.calls += 1
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
