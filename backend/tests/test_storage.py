from storage import ProfileStore
import sqlite3


def test_profile_store_round_trips_scholar_history(tmp_path):
    store = ProfileStore(tmp_path / "history.sqlite3")

    store.save_profile(
        "https://openalex.org/A1",
        "Haofen Wang",
        {"name": "Haofen Wang", "totalPapers": 171},
        warnings=["demo warning"],
        errors=[],
    )

    cached = store.get_profile("https://openalex.org/A1")

    assert cached is not None
    assert cached["author_id"] == "https://openalex.org/A1"
    assert cached["query_name"] == "Haofen Wang"
    assert cached["payload"] == {"name": "Haofen Wang", "totalPapers": 171}
    assert cached["warnings"] == ["demo warning"]
    assert cached["errors"] == []
    assert isinstance(cached["updated_at"], str)


def test_profile_store_lists_recent_queries(tmp_path):
    store = ProfileStore(tmp_path / "history.sqlite3")
    store.save_profile("A1", "First", {"name": "First"}, warnings=[], errors=[])
    store.save_profile("A2", "Second", {"name": "Second"}, warnings=[], errors=[])

    history = store.list_history(limit=10)

    assert [item["author_id"] for item in history] == ["A2", "A1"]
    assert history[0]["name"] == "Second"


def test_profile_store_reports_cache_freshness(tmp_path):
    db_path = tmp_path / "history.sqlite3"
    store = ProfileStore(db_path)
    store.save_profile("A1", "First", {"name": "First"}, warnings=[], errors=[])

    fresh = store.get_profile("A1")
    assert fresh is not None
    assert store.is_fresh(fresh, max_age_days=7)

    with sqlite3.connect(db_path) as conn:
        conn.execute("DROP TRIGGER scholar_profiles_updated_at")
        conn.execute(
            "UPDATE scholar_profiles SET updated_at = datetime('now', '-8 days') WHERE author_id = ?",
            ("A1",),
        )

    stale = store.get_profile("A1")
    assert stale is not None
    assert not store.is_fresh(stale, max_age_days=7)
