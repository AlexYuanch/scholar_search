"""SQLite storage for generated scholar profile history."""
import json
import os
import sqlite3
from pathlib import Path
from typing import Any


DEFAULT_DB_PATH = Path(__file__).resolve().parent / "data" / "scholar_history.sqlite3"


class ProfileStore:
    """Small SQLite-backed cache for completed profile payloads."""

    def __init__(self, db_path: str | os.PathLike[str] | None = None):
        self.db_path = Path(db_path or os.getenv("SCHOLAR_PROFILE_DB", DEFAULT_DB_PATH))
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS scholar_profiles (
                    author_id TEXT PRIMARY KEY,
                    query_name TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    warnings_json TEXT NOT NULL,
                    errors_json TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute(
                """
                CREATE TRIGGER IF NOT EXISTS scholar_profiles_updated_at
                AFTER UPDATE ON scholar_profiles
                BEGIN
                    UPDATE scholar_profiles
                    SET updated_at = CURRENT_TIMESTAMP
                    WHERE author_id = NEW.author_id;
                END
                """
            )

    def save_profile(
        self,
        author_id: str,
        query_name: str,
        payload: dict[str, Any],
        warnings: list[str],
        errors: list[str],
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO scholar_profiles (
                    author_id, query_name, payload_json, warnings_json, errors_json
                )
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(author_id) DO UPDATE SET
                    query_name = excluded.query_name,
                    payload_json = excluded.payload_json,
                    warnings_json = excluded.warnings_json,
                    errors_json = excluded.errors_json
                """,
                (
                    author_id,
                    query_name,
                    json.dumps(payload, ensure_ascii=False),
                    json.dumps(warnings, ensure_ascii=False),
                    json.dumps(errors, ensure_ascii=False),
                ),
            )

    def get_profile(self, author_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT author_id, query_name, payload_json, warnings_json,
                       errors_json, created_at, updated_at
                FROM scholar_profiles
                WHERE author_id = ?
                """,
                (author_id,),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_profile(row)

    def list_history(self, limit: int = 20) -> list[dict[str, Any]]:
        safe_limit = max(1, min(limit, 100))
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT author_id, query_name, payload_json, warnings_json,
                       errors_json, created_at, updated_at
                FROM scholar_profiles
                ORDER BY updated_at DESC, rowid DESC
                LIMIT ?
                """,
                (safe_limit,),
            ).fetchall()
        return [self._row_to_profile(row) for row in rows]

    @staticmethod
    def _row_to_profile(row: sqlite3.Row) -> dict[str, Any]:
        payload = json.loads(row["payload_json"])
        return {
            "author_id": row["author_id"],
            "query_name": row["query_name"],
            "name": payload.get("name", row["query_name"]),
            "institution": payload.get("institution", ""),
            "total_papers": payload.get("totalPapers", 0),
            "total_citations": payload.get("totalCitations", 0),
            "h_index": payload.get("hIndex", 0),
            "payload": payload,
            "warnings": json.loads(row["warnings_json"]),
            "errors": json.loads(row["errors_json"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
