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
    def __init__(self, responses):
        self.responses = responses

    def get(self, url, **_kwargs):
        doi = url.split("/works/", 1)[1]
        return self.responses[doi]


def test_normalize_doi_accepts_common_forms():
    import crossref

    assert crossref.normalize_doi("https://doi.org/10.1000/ABC") == "10.1000/abc"
    assert crossref.normalize_doi("doi:10.1000/ABC") == "10.1000/abc"
    assert crossref.normalize_doi("") == ""


def test_verify_dois_returns_normalized_records_and_missing_count(monkeypatch):
    import crossref

    session = FakeSession({
        "10.1000%2Fverified": FakeResponse(200, {"message": {
            "DOI": "10.1000/VERIFIED",
            "title": ["Verified title"],
            "container-title": ["Verified Journal"],
            "published": {"date-parts": [[2024, 3, 1]]},
            "author": [{"given": "Ada", "family": "Lovelace"}],
            "type": "journal-article",
        }}),
        "10.1000%2Fmissing": FakeResponse(404, {"status": "resource-not-found"}),
    })
    monkeypatch.setattr(crossref, "_SESSION", session)

    records, report = crossref.verify_dois(
        ["https://doi.org/10.1000/VERIFIED", "10.1000/missing"],
        max_workers=1,
    )

    assert records["10.1000/verified"]["title"] == "Verified title"
    assert records["10.1000/verified"]["publication_year"] == 2024
    assert report == {"requested": 2, "verified": 1, "missing": 1, "failed": 0}

