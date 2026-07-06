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
        "updated_at": response.json()["updated_at"],
        "warnings": ["cached warning"],
        "errors": [],
        "data": {
            "name": "Ada Lovelace",
            "totalPapers": 1,
            "authorId": "A1",
            "profileEvidence": [],
        },
    }


def test_profile_refresh_bypasses_cached_payload(monkeypatch, tmp_path):
    from storage import ProfileStore
    import main

    store = ProfileStore(tmp_path / "history.sqlite3")
    store.save_profile("A1", "Ada Lovelace", {"name": "Cached"}, warnings=[], errors=[])

    def live_invoke(_state):
        return {"web_payload": {"name": "Live"}, "warnings": [], "errors": []}

    monkeypatch.setattr(main, "profile_store", store)
    monkeypatch.setattr(main.graph, "invoke", live_invoke)

    response = TestClient(app).post("/api/profile", json={"author_id": "A1", "refresh": True})

    assert response.status_code == 200
    assert response.json()["source"] == "live"
    assert response.json()["data"] == {"name": "Live"}


def test_profile_recomputes_stale_cache(monkeypatch, tmp_path):
    from storage import ProfileStore
    import main
    import sqlite3

    db_path = tmp_path / "history.sqlite3"
    store = ProfileStore(db_path)
    store.save_profile("A1", "Ada Lovelace", {"name": "Cached"}, warnings=[], errors=[])
    with sqlite3.connect(db_path) as conn:
        conn.execute("DROP TRIGGER scholar_profiles_updated_at")
        conn.execute(
            "UPDATE scholar_profiles SET updated_at = datetime('now', '-8 days') WHERE author_id = ?",
            ("A1",),
        )

    def live_invoke(_state):
        return {"web_payload": {"name": "Live"}, "warnings": [], "errors": []}

    monkeypatch.setattr(main, "profile_store", store)
    monkeypatch.setattr(main.graph, "invoke", live_invoke)

    response = TestClient(app).post("/api/profile", json={"author_id": "A1"})

    assert response.status_code == 200
    assert response.json()["source"] == "live"
    assert response.json()["data"] == {"name": "Live"}


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


def test_profile_stream_reports_workflow_error(monkeypatch, tmp_path):
    from storage import ProfileStore
    import main

    class BrokenGraph:
        def stream(self, _state, stream_mode="values"):
            raise RuntimeError("workflow exploded")

    monkeypatch.setattr(main, "profile_store", ProfileStore(tmp_path / "history.sqlite3"))
    monkeypatch.setattr(main, "graph", BrokenGraph())

    response = TestClient(app).post("/api/profile/stream", json={"author_id": "A1"})
    body = response.text

    assert response.status_code == 200
    assert '"type": "error"' in body
    assert "workflow exploded" in body
