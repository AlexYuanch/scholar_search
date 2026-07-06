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
