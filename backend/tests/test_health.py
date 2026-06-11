from fastapi.testclient import TestClient

from main import app


def test_health_returns_ok():
    response = TestClient(app).get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_profile_returns_cached_payload_without_running_graph(monkeypatch, tmp_path):
    from storage import ProfileStore
    import main

    store = ProfileStore(tmp_path / "history.sqlite3")
    store.save_profile(
        "A1",
        "Ada Lovelace",
        {"name": "Ada Lovelace", "totalPapers": 1},
        warnings=["cached warning"],
        errors=[],
    )

    def fail_invoke(_state):
        raise AssertionError("graph should not run when cache is warm")

    monkeypatch.setattr(main, "profile_store", store)
    monkeypatch.setattr(main.graph, "invoke", fail_invoke)

    response = TestClient(app).post("/api/profile", json={"author_id": "A1"})

    assert response.status_code == 200
    assert response.json() == {
        "status": "success",
        "source": "cache",
        "warnings": ["cached warning"],
        "errors": [],
        "data": {"name": "Ada Lovelace", "totalPapers": 1},
    }


def test_profile_stream_reports_cache_hit(monkeypatch, tmp_path):
    from storage import ProfileStore
    import main

    store = ProfileStore(tmp_path / "history.sqlite3")
    store.save_profile("A1", "Ada Lovelace", {"name": "Ada Lovelace"}, warnings=[], errors=[])
    monkeypatch.setattr(main, "profile_store", store)

    response = TestClient(app).post("/api/profile/stream", json={"author_id": "A1"})
    body = response.text

    assert response.status_code == 200
    assert '"type": "progress"' in body
    assert '"progress": 100' in body
    assert '"type": "cache_hit"' in body
    assert '"source": "cache"' in body
