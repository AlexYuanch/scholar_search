import dblp


class FakeResponse:
    def __init__(self, *, payload=None, content=b""):
        self._payload = payload
        self.content = content

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def test_dblp_matches_exact_author_affiliation_and_existing_papers(monkeypatch):
    search_payload = {
        "result": {
            "hits": {
                "hit": [{
                    "info": {
                        "author": "Li Fei-Fei 0001",
                        "aliases": {"alias": "Fei-Fei Li 0001"},
                        "notes": {"note": {"text": "Stanford University"}},
                        "url": "https://dblp.org/pid/79/2528",
                    },
                }],
            },
        },
    }
    xml = b"""<dblpperson pid="79/2528">
      <r><article key="journals/test/one">
        <author>Fei-Fei Li</author><title>Visual Recognition</title>
        <year>2024</year><journal>Vision Journal</journal>
        <ee>https://doi.org/10.1000/vision</ee>
      </article></r>
      <r><article key="journals/test/two">
        <author>Someone Else</author><title>Unrelated Paper</title><year>2020</year>
      </article></r>
    </dblpperson>"""

    def fake_get(url, **_kwargs):
        if "search/author/api" in url:
            return FakeResponse(payload=search_payload)
        return FakeResponse(content=xml)

    monkeypatch.setattr(dblp._SESSION, "get", fake_get)
    records, audit = dblp.verify_author_works(
        {
            "display_name": "Fei-Fei Li",
            "last_known_institutions": [{"display_name": "Stanford University"}],
        },
        [{
            "title": "Visual Recognition",
            "publication_year": 2024,
            "doi": "https://doi.org/10.1000/vision",
        }],
    )

    assert audit["status"] == "available"
    assert audit["personPid"] == "79/2528"
    assert audit["matchMethod"] == "affiliation"
    assert audit["matched"] == 1
    assert records[0]["doi"] == "10.1000/vision"
    assert records[0]["journal"] == "Vision Journal"


def test_dblp_rejects_ambiguous_exact_names_without_identity_evidence(monkeypatch):
    monkeypatch.setattr(dblp, "_search_candidates", lambda _name: [
        {"pid": "1", "names": ["Alex Lee"], "affiliations": ["University A"], "url": ""},
        {"pid": "2", "names": ["Alex Lee"], "affiliations": ["University B"], "url": ""},
    ])

    records, audit = dblp.verify_author_works(
        {"display_name": "Alex Lee", "last_known_institutions": []},
        [{"title": "A Paper", "publication_year": 2024}],
    )

    assert records == []
    assert audit["status"] == "identity_unresolved"
