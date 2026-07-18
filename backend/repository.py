"""Portable PostgreSQL repository and an isolated in-memory test implementation."""
from __future__ import annotations

import json
import os
import threading
import uuid
from hashlib import sha256
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | str | None = None) -> str:
    if isinstance(value, str):
        return value
    return (value or _now()).isoformat()


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _normalize_database_url(database_url: str) -> str:
    if database_url.startswith("postgres://"):
        return database_url.replace("postgres://", "postgresql+psycopg://", 1)
    if database_url.startswith("postgresql://"):
        return database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    return database_url


def _data_fingerprint(author_id: str, works: list[dict]) -> str:
    facts = [
        (work.get("id", ""), work.get("publication_year"), work.get("cited_by_count", 0))
        for work in works
    ]
    encoded = _json({"author_id": author_id, "works": sorted(facts, key=lambda item: str(item[0]))}).encode()
    return sha256(encoded).hexdigest()


def _work_payload(work: dict) -> dict:
    return {
        "id": work.get("id", ""),
        "title": work.get("title", ""),
        "year": work.get("publication_year"),
        "citations": work.get("cited_by_count", 0) or 0,
        "journal": ((work.get("primary_location") or {}).get("source") or {}).get("display_name", ""),
        "doi": work.get("doi", ""),
    }


class RepositoryNotConfigured(RuntimeError):
    pass


class LoginRateLimitExceeded(RuntimeError):
    pass


class InMemoryRepository:
    """Test repository with the same behavioral contract as PostgresRepository."""

    def __init__(self):
        self._lock = threading.RLock()
        self.scholars: dict[str, dict] = {}
        self.profiles: dict[str, dict] = {}
        self.works: dict[str, list[dict]] = {}
        self.history: dict[tuple[str, str], dict] = {}
        self.favorites: dict[tuple[str, str], dict] = {}
        self.jobs: dict[str, dict] = {}
        self.users: dict[str, dict] = {}
        self.login_tokens: dict[str, dict] = {}
        self.sessions: dict[str, dict] = {}

    def _scholar(self, author_id: str, name: str = "") -> dict:
        if author_id not in self.scholars:
            self.scholars[author_id] = {
                "id": str(uuid.uuid4()),
                "author_id": author_id,
                "name": name,
                "last_accessed_at": _iso(),
            }
        elif name:
            self.scholars[author_id]["name"] = name
        return self.scholars[author_id]

    def publish_profile(
        self,
        state: dict,
        query_name: str = "",
        quality_flags: list[str] | None = None,
    ) -> dict:
        with self._lock:
            author_id = state.get("target_author_id") or (state.get("target_author_profile") or {}).get("id")
            if not author_id:
                raise ValueError("target_author_id is required")
            author_profile = state.get("target_author_profile") or {}
            scholar = self._scholar(author_id, author_profile.get("display_name", query_name))
            previous = self.profiles.get(author_id)
            version = int((previous or {}).get("profile_version", 0)) + 1
            payload = deepcopy(state.get("web_payload") or {})
            payload.update({
                "authorId": author_id,
                "scholarId": scholar["id"],
                "profileVersion": version,
                "refreshStatus": "ready",
            })
            saved = {
                "author_id": author_id,
                "scholar_id": scholar["id"],
                "query_name": query_name or payload.get("name", ""),
                "payload": payload,
                "warnings": deepcopy(state.get("warnings") or []),
                "errors": deepcopy(state.get("errors") or []),
                "quality_flags": list(quality_flags or []),
                "updated_at": _iso(),
                "profile_version": version,
                "refresh_status": "ready",
                "data_fingerprint": _data_fingerprint(author_id, state.get("deduped_works") or []),
            }
            self.profiles[author_id] = saved
            works = [_work_payload(work) for work in state.get("deduped_works") or []]
            self.works[author_id] = works
            return deepcopy(saved)

    def get_profile(self, author_id: str) -> dict | None:
        profile = self.profiles.get(author_id)
        return deepcopy(profile) if profile else None

    @staticmethod
    def is_fresh(profile: dict, max_age_days: int = 7) -> bool:
        try:
            updated = datetime.fromisoformat(str(profile["updated_at"]).replace("Z", "+00:00"))
        except (KeyError, ValueError):
            return False
        if updated.tzinfo is None:
            updated = updated.replace(tzinfo=timezone.utc)
        return _now() - updated <= timedelta(days=max_age_days)

    def touch_access(self, author_id: str) -> None:
        with self._lock:
            scholar = self._scholar(author_id)
            scholar["last_accessed_at"] = _iso()

    def list_works(self, author_id: str, limit: int, offset: int, sort: str) -> dict:
        items = list(self.works.get(author_id, []))
        key = "year" if sort == "year" else "citations"
        items.sort(key=lambda item: (item.get(key) or 0, item.get("id", "")), reverse=True)
        return {"items": deepcopy(items[offset:offset + limit]), "total": len(items)}

    def record_history(self, user_id: str, author_id: str, query_name: str = "") -> None:
        with self._lock:
            scholar = self._scholar(author_id, query_name)
            key = (user_id, author_id)
            previous = self.history.get(key, {})
            self.history[key] = {
                "author_id": author_id,
                "scholar_id": scholar["id"],
                "name": scholar.get("name") or query_name,
                "last_viewed_at": _iso(),
                "view_count": int(previous.get("view_count", 0)) + 1,
            }

    def list_history(self, user_id: str, limit: int) -> list[dict]:
        rows = [deepcopy(v) for (uid, _), v in self.history.items() if uid == user_id]
        return sorted(rows, key=lambda row: row["last_viewed_at"], reverse=True)[:limit]

    def add_favorite(self, user_id: str, author_id: str) -> dict:
        with self._lock:
            scholar = self._scholar(author_id)
            row = {
                "author_id": author_id,
                "scholar_id": scholar["id"],
                "name": scholar.get("name", ""),
                "created_at": _iso(),
            }
            self.favorites[(user_id, author_id)] = row
            return deepcopy(row)

    def remove_favorite(self, user_id: str, author_id: str) -> None:
        self.favorites.pop((user_id, author_id), None)

    def list_favorites(self, user_id: str) -> list[dict]:
        rows = [deepcopy(v) for (uid, _), v in self.favorites.items() if uid == user_id]
        return sorted(rows, key=lambda row: row["created_at"], reverse=True)

    def enqueue_refresh(self, author_id: str, reason: str) -> str:
        with self._lock:
            scholar = self._scholar(author_id)
            for job in self.jobs.values():
                if job["author_id"] == author_id and job["status"] in {"pending", "running"}:
                    return job["id"]
            job_id = str(uuid.uuid4())
            self.jobs[job_id] = {
                "id": job_id,
                "scholar_id": scholar["id"],
                "author_id": author_id,
                "reason": reason,
                "status": "pending",
                "attempts": 0,
                "scheduled_at": _iso(),
            }
            return job_id

    def claim_refresh_job(self) -> dict | None:
        with self._lock:
            pending = [job for job in self.jobs.values() if job["status"] == "pending"]
            if not pending:
                return None
            job = sorted(pending, key=lambda row: row["scheduled_at"])[0]
            job["status"] = "running"
            job["attempts"] += 1
            job["started_at"] = _iso()
            return deepcopy(job)

    def complete_refresh_job(self, job_id: str) -> None:
        with self._lock:
            self.jobs[job_id].update(status="succeeded", finished_at=_iso())

    def fail_refresh_job(self, job_id: str, error: str, retry: bool) -> None:
        with self._lock:
            self.jobs[job_id].update(
                status="pending" if retry else "failed",
                last_error=error,
                finished_at=None if retry else _iso(),
                scheduled_at=_iso(_now() + timedelta(minutes=2 ** self.jobs[job_id]["attempts"])),
            )

    def create_login_token(
        self,
        email: str,
        token_hash: str,
        expires_at: datetime,
        request_ip: str | None = None,
    ) -> None:
        normalized_email = email.strip().lower()
        recent = [
            row for row in self.login_tokens.values()
            if row["normalized_email"] == normalized_email
            and _now() - row["created_at"] < timedelta(minutes=15)
        ]
        if len(recent) >= 3:
            raise LoginRateLimitExceeded("Too many login emails requested")
        self.login_tokens[token_hash] = {
            "email": email.strip(),
            "normalized_email": normalized_email,
            "expires_at": expires_at,
            "created_at": _now(),
            "consumed_at": None,
            "request_ip": request_ip,
        }

    def consume_login_token(
        self,
        token_hash: str,
        session_hash: str,
        session_expires_at: datetime,
        user_agent: str = "",
        request_ip: str | None = None,
    ) -> dict | None:
        token = self.login_tokens.get(token_hash)
        if not token or token["consumed_at"] or token["expires_at"] <= _now():
            return None
        token["consumed_at"] = _now()
        normalized_email = token["normalized_email"]
        user = self.users.get(normalized_email)
        if not user:
            user = {
                "id": str(uuid.uuid4()),
                "email": token["email"],
                "normalized_email": normalized_email,
                "is_active": True,
            }
            self.users[normalized_email] = user
        self.sessions[session_hash] = {
            "user_id": user["id"],
            "expires_at": session_expires_at,
            "revoked_at": None,
            "user_agent": user_agent,
            "request_ip": request_ip,
        }
        return deepcopy(user)

    def get_user_by_session(self, session_hash: str) -> dict | None:
        session = self.sessions.get(session_hash)
        if not session or session["revoked_at"] or session["expires_at"] <= _now():
            return None
        return next(
            (deepcopy(user) for user in self.users.values() if user["id"] == session["user_id"]),
            None,
        )

    def revoke_session(self, session_hash: str) -> None:
        session = self.sessions.get(session_hash)
        if session:
            session["revoked_at"] = _now()

    def get_profile_status(self, scholar_id: str) -> dict | None:
        for profile in self.profiles.values():
            if profile["scholar_id"] == scholar_id:
                return {
                    "scholar_id": scholar_id,
                    "version": profile["profile_version"],
                    "status": profile["refresh_status"],
                    "updated_at": profile["updated_at"],
                }
        return None

    def run_maintenance(self) -> dict:
        return {"enqueued": 0, "deleted": 0}

    def healthcheck(self) -> bool:
        return True


class PostgresRepository:
    """PostgreSQL implementation shared by the API and refresh worker."""

    def __init__(self, database_url: str, engine: Engine | None = None):
        self.engine = engine or create_engine(
            _normalize_database_url(database_url),
            pool_pre_ping=True,
            pool_size=int(os.getenv("DATABASE_POOL_SIZE", "5")),
            max_overflow=int(os.getenv("DATABASE_MAX_OVERFLOW", "5")),
            pool_timeout=int(os.getenv("DATABASE_POOL_TIMEOUT", "10")),
            pool_recycle=int(os.getenv("DATABASE_POOL_RECYCLE", "1800")),
            connect_args={"connect_timeout": int(os.getenv("DATABASE_CONNECT_TIMEOUT", "10"))},
        )

    @staticmethod
    def is_fresh(profile: dict, max_age_days: int = 7) -> bool:
        return InMemoryRepository.is_fresh(profile, max_age_days)

    def _upsert_scholar(self, conn, author: dict, fallback_id: str = "") -> str:
        source_id = author.get("id") or fallback_id
        if not source_id:
            raise ValueError("OpenAlex author id is required")
        institutions = author.get("last_known_institutions") or []
        is_detail = any(key in author for key in ("works_count", "cited_by_count", "summary_stats"))
        row = conn.execute(text("""
            insert into public.scholars (
                source, source_author_id, display_name, orcid, works_count,
                cited_by_count, h_index, raw_json, updated_at
            ) values (
                'openalex', :source_id, :display_name, :orcid, :works_count,
                :cited_by_count, :h_index, cast(:raw_json as jsonb), now()
            )
            on conflict (source, source_author_id) do update set
                display_name = excluded.display_name,
                orcid = coalesce(excluded.orcid, scholars.orcid),
                works_count = case when :is_detail then greatest(excluded.works_count, 0) else scholars.works_count end,
                cited_by_count = case when :is_detail then greatest(excluded.cited_by_count, 0) else scholars.cited_by_count end,
                h_index = case when :is_detail then greatest(excluded.h_index, 0) else scholars.h_index end,
                raw_json = case when :is_detail then excluded.raw_json else scholars.raw_json end,
                updated_at = now()
            returning id
        """), {
            "source_id": source_id,
            "display_name": author.get("display_name") or "?",
            "orcid": author.get("orcid"),
            "works_count": author.get("works_count", 0) or 0,
            "cited_by_count": author.get("cited_by_count", 0) or 0,
            "h_index": (author.get("summary_stats") or {}).get("h_index", 0) or 0,
            "raw_json": _json(author),
            "is_detail": is_detail,
        }).scalar_one()

        aliases = {author.get("display_name", "").strip()}
        aliases.update(a.strip() for a in author.get("display_name_alternatives") or [] if a.strip())
        for alias in aliases - {""}:
            conn.execute(text("""
                insert into public.scholar_aliases (scholar_id, alias, normalized_alias)
                values (:scholar_id, :alias, lower(:alias))
                on conflict (scholar_id, normalized_alias) do nothing
            """), {"scholar_id": row, "alias": alias})

        for institution in institutions:
            self._link_institution(conn, row, institution)
        return str(row)

    def _link_institution(self, conn, scholar_id: str, institution: dict) -> None:
        source_id = institution.get("id")
        if not source_id:
            return
        institution_id = conn.execute(text("""
            insert into public.institutions (source, source_institution_id, display_name, country_code, raw_json)
            values ('openalex', :source_id, :display_name, :country_code, cast(:raw_json as jsonb))
            on conflict (source, source_institution_id) do update set
                display_name = excluded.display_name,
                country_code = excluded.country_code,
                raw_json = excluded.raw_json
            returning id
        """), {
            "source_id": source_id,
            "display_name": institution.get("display_name") or "?",
            "country_code": institution.get("country_code"),
            "raw_json": _json(institution),
        }).scalar_one()
        conn.execute(text("""
            insert into public.scholar_institutions (scholar_id, institution_id, is_last_known)
            values (:scholar_id, :institution_id, true)
            on conflict (scholar_id, institution_id) do update set is_last_known = true
        """), {"scholar_id": scholar_id, "institution_id": institution_id})

    def publish_profile(
        self,
        state: dict,
        query_name: str = "",
        quality_flags: list[str] | None = None,
    ) -> dict:
        profile = state.get("target_author_profile") or {}
        author_id = state.get("target_author_id") or profile.get("id")
        if not author_id:
            raise ValueError("target_author_id is required")
        works = state.get("deduped_works") or []

        with self.engine.begin() as conn:
            scholar_id = self._upsert_scholar(conn, profile, author_id)
            work_source_ids: list[str] = []
            for work in works:
                work_source_id = work.get("id")
                if not work_source_id:
                    continue
                work_source_ids.append(work_source_id)
                work_id = conn.execute(text("""
                    insert into public.works (
                        source, source_work_id, doi, title, publication_year,
                        cited_by_count, raw_json, updated_at
                    ) values (
                        'openalex', :source_id, :doi, :title, :year,
                        :citations, cast(:raw_json as jsonb), now()
                    )
                    on conflict (source, source_work_id) do update set
                        doi = excluded.doi,
                        title = excluded.title,
                        publication_year = excluded.publication_year,
                        cited_by_count = excluded.cited_by_count,
                        raw_json = excluded.raw_json,
                        updated_at = now()
                    returning id
                """), {
                    "source_id": work_source_id,
                    "doi": work.get("doi"),
                    "title": work.get("title") or "",
                    "year": work.get("publication_year"),
                    "citations": work.get("cited_by_count", 0) or 0,
                    "raw_json": _json(work),
                }).scalar_one()
                conn.execute(text("delete from public.authorships where work_id = :work_id"), {"work_id": work_id})
                for position, authorship in enumerate(work.get("authorships") or []):
                    raw_author = authorship.get("author") or {}
                    if not raw_author.get("id"):
                        continue
                    coauthor_id = self._upsert_scholar(conn, raw_author)
                    conn.execute(text("""
                        insert into public.authorships (
                            work_id, scholar_id, author_position, position_index,
                            raw_author_name, is_corresponding
                        ) values (
                            :work_id, :scholar_id, :author_position, :position_index,
                            :raw_author_name, :is_corresponding
                        )
                        on conflict (work_id, scholar_id) do update set
                            author_position = excluded.author_position,
                            position_index = excluded.position_index,
                            raw_author_name = excluded.raw_author_name,
                            is_corresponding = excluded.is_corresponding
                    """), {
                        "work_id": work_id,
                        "scholar_id": coauthor_id,
                        "author_position": authorship.get("author_position"),
                        "position_index": position,
                        "raw_author_name": raw_author.get("display_name") or "?",
                        "is_corresponding": bool(authorship.get("is_corresponding")),
                    })
                    for institution in authorship.get("institutions") or []:
                        self._link_institution(conn, coauthor_id, institution)

            if state.get("works_complete"):
                if work_source_ids:
                    conn.execute(text("""
                        delete from public.authorships a
                        where a.scholar_id = :scholar_id
                          and not exists (
                            select 1 from public.works w
                            where w.id = a.work_id
                              and w.source_work_id = any(cast(:work_source_ids as text[]))
                          )
                    """), {"scholar_id": scholar_id, "work_source_ids": work_source_ids})
                else:
                    conn.execute(
                        text("delete from public.authorships where scholar_id = :scholar_id"),
                        {"scholar_id": scholar_id},
                    )

            version = conn.execute(text("""
                insert into public.profile_status (scholar_id, version, status, updated_at)
                values (:scholar_id, 1, 'ready', now())
                on conflict (scholar_id) do update set
                    version = profile_status.version + 1,
                    status = 'ready',
                    updated_at = now()
                returning version
            """), {"scholar_id": scholar_id}).scalar_one()
            payload = deepcopy(state.get("web_payload") or {})
            payload.update({
                "authorId": author_id,
                "scholarId": scholar_id,
                "profileVersion": version,
                "refreshStatus": "ready",
            })
            conn.execute(text("""
                insert into public.scholar_profiles (
                    scholar_id, query_name, payload, warnings, errors,
                    quality_flags, workflow_version, data_fingerprint, generated_at
                ) values (
                    :scholar_id, :query_name, cast(:payload as jsonb), cast(:warnings as jsonb),
                    cast(:errors as jsonb), cast(:quality_flags as jsonb), :workflow_version,
                    :data_fingerprint, now()
                )
                on conflict (scholar_id) do update set
                    query_name = excluded.query_name,
                    payload = excluded.payload,
                    warnings = excluded.warnings,
                    errors = excluded.errors,
                    quality_flags = excluded.quality_flags,
                    workflow_version = excluded.workflow_version,
                    data_fingerprint = excluded.data_fingerprint,
                    generated_at = now()
            """), {
                "scholar_id": scholar_id,
                "query_name": query_name or payload.get("name", ""),
                "payload": _json(payload),
                "warnings": _json(state.get("warnings") or []),
                "errors": _json(state.get("errors") or []),
                "quality_flags": _json(quality_flags or []),
                "workflow_version": os.getenv("WORKFLOW_VERSION", "1"),
                "data_fingerprint": _data_fingerprint(author_id, works),
            })
            conn.execute(text("""
                update public.scholars
                set last_synced_at = now(),
                    quality_flags = cast(:quality_flags as jsonb), updated_at = now()
                where id = :scholar_id
            """), {"scholar_id": scholar_id, "quality_flags": _json(quality_flags or [])})

        return self.get_profile(author_id) or {}

    def get_profile(self, author_id: str) -> dict | None:
        with self.engine.connect() as conn:
            row = conn.execute(text("""
                select s.id as scholar_id, s.source_author_id as author_id,
                       p.query_name, p.payload, p.warnings, p.errors, p.quality_flags,
                       p.data_fingerprint,
                       p.generated_at as updated_at, ps.version as profile_version,
                       ps.status as refresh_status
                from public.scholars s
                join public.scholar_profiles p on p.scholar_id = s.id
                join public.profile_status ps on ps.scholar_id = s.id
                where s.source = 'openalex' and s.source_author_id = :author_id
            """), {"author_id": author_id}).mappings().first()
        if not row:
            return None
        result = dict(row)
        result["scholar_id"] = str(result["scholar_id"])
        result["updated_at"] = _iso(result["updated_at"])
        return result

    def get_profile_status(self, scholar_id: str) -> dict | None:
        with self.engine.connect() as conn:
            row = conn.execute(text("""
                select scholar_id, version, status, updated_at
                from public.profile_status
                where scholar_id = cast(:scholar_id as uuid)
            """), {"scholar_id": scholar_id}).mappings().first()
        if not row:
            return None
        result = dict(row)
        result["scholar_id"] = str(result["scholar_id"])
        result["updated_at"] = _iso(result["updated_at"])
        return result

    def touch_access(self, author_id: str) -> None:
        with self.engine.begin() as conn:
            conn.execute(text("""
                update public.scholars set last_accessed_at = now(), updated_at = now()
                where source = 'openalex' and source_author_id = :author_id
            """), {"author_id": author_id})

    def list_works(self, author_id: str, limit: int, offset: int, sort: str) -> dict:
        order = "w.publication_year desc nulls last, w.id" if sort == "year" else "w.cited_by_count desc, w.id"
        with self.engine.connect() as conn:
            total = conn.execute(text("""
                select count(*) from public.works w
                join public.authorships a on a.work_id = w.id
                join public.scholars s on s.id = a.scholar_id
                where s.source = 'openalex' and s.source_author_id = :author_id
            """), {"author_id": author_id}).scalar_one()
            rows = conn.execute(text(f"""
                select w.source_work_id as id, w.title, w.publication_year as year,
                       w.cited_by_count as citations, w.doi,
                       coalesce(w.raw_json #>> '{{primary_location,source,display_name}}', '') as journal
                from public.works w
                join public.authorships a on a.work_id = w.id
                join public.scholars s on s.id = a.scholar_id
                where s.source = 'openalex' and s.source_author_id = :author_id
                order by {order}
                limit :limit offset :offset
            """), {"author_id": author_id, "limit": limit, "offset": offset}).mappings().all()
        return {"items": [dict(row) for row in rows], "total": total}

    def _scholar_summary(self, row: dict) -> dict:
        payload = row.get("payload") or {}
        return {
            "author_id": row["author_id"],
            "scholar_id": str(row["scholar_id"]),
            "name": payload.get("name") or row.get("display_name") or "",
            "institution": payload.get("institution", ""),
            "total_papers": payload.get("totalPapers", 0),
            "total_citations": payload.get("totalCitations", 0),
            "h_index": payload.get("hIndex", 0),
            "updated_at": _iso(row.get("updated_at")),
        }

    def record_history(self, user_id: str, author_id: str, query_name: str = "") -> None:
        with self.engine.begin() as conn:
            conn.execute(text("""
                insert into public.user_history (user_id, scholar_id, query_name, view_count, last_viewed_at)
                select cast(:user_id as uuid), id, :query_name, 1, now()
                from public.scholars where source = 'openalex' and source_author_id = :author_id
                on conflict (user_id, scholar_id) do update set
                    query_name = excluded.query_name,
                    view_count = user_history.view_count + 1,
                    last_viewed_at = now()
            """), {"user_id": user_id, "author_id": author_id, "query_name": query_name})

    def list_history(self, user_id: str, limit: int) -> list[dict]:
        with self.engine.connect() as conn:
            rows = conn.execute(text("""
                select s.id as scholar_id, s.source_author_id as author_id, s.display_name,
                       p.payload, p.generated_at as updated_at, h.last_viewed_at, h.view_count
                from public.user_history h
                join public.scholars s on s.id = h.scholar_id
                left join public.scholar_profiles p on p.scholar_id = s.id
                where h.user_id = cast(:user_id as uuid)
                order by h.last_viewed_at desc limit :limit
            """), {"user_id": user_id, "limit": limit}).mappings().all()
        return [self._scholar_summary(dict(row)) | {
            "last_viewed_at": _iso(row["last_viewed_at"]),
            "view_count": row["view_count"],
        } for row in rows]

    def add_favorite(self, user_id: str, author_id: str) -> dict:
        with self.engine.begin() as conn:
            row = conn.execute(text("""
                insert into public.favorites (user_id, scholar_id)
                select cast(:user_id as uuid), id from public.scholars
                where source = 'openalex' and source_author_id = :author_id
                on conflict (user_id, scholar_id) do update set user_id = excluded.user_id
                returning scholar_id, created_at
            """), {"user_id": user_id, "author_id": author_id}).mappings().first()
            if not row:
                raise KeyError("scholar not found")
        cached = self.get_profile(author_id)
        if not cached or not self.is_fresh(cached, max_age_days=1):
            self.enqueue_refresh(author_id, "favorite")
        return {"author_id": author_id, "scholar_id": str(row["scholar_id"]), "created_at": _iso(row["created_at"])}

    def remove_favorite(self, user_id: str, author_id: str) -> None:
        with self.engine.begin() as conn:
            conn.execute(text("""
                delete from public.favorites f using public.scholars s
                where f.scholar_id = s.id and f.user_id = cast(:user_id as uuid)
                  and s.source = 'openalex' and s.source_author_id = :author_id
            """), {"user_id": user_id, "author_id": author_id})

    def list_favorites(self, user_id: str) -> list[dict]:
        with self.engine.connect() as conn:
            rows = conn.execute(text("""
                select s.id as scholar_id, s.source_author_id as author_id, s.display_name,
                       p.payload, p.generated_at as updated_at, f.created_at
                from public.favorites f
                join public.scholars s on s.id = f.scholar_id
                left join public.scholar_profiles p on p.scholar_id = s.id
                where f.user_id = cast(:user_id as uuid)
                order by f.created_at desc
            """), {"user_id": user_id}).mappings().all()
        return [self._scholar_summary(dict(row)) | {"created_at": _iso(row["created_at"])} for row in rows]

    def enqueue_refresh(self, author_id: str, reason: str) -> str:
        with self.engine.begin() as conn:
            scholar_id = conn.execute(text("""
                select id from public.scholars where source = 'openalex' and source_author_id = :author_id
            """), {"author_id": author_id}).scalar_one_or_none()
            if not scholar_id:
                raise KeyError("scholar not found")
            job_id = conn.execute(text("""
                insert into public.refresh_jobs (scholar_id, reason, status, scheduled_at)
                values (:scholar_id, :reason, 'pending', now())
                on conflict do nothing
                returning id
            """), {"scholar_id": scholar_id, "reason": reason}).scalar_one_or_none()
            if not job_id:
                job_id = conn.execute(text("""
                    select id from public.refresh_jobs
                    where scholar_id = :scholar_id and status in ('pending', 'running')
                    order by created_at limit 1
                """), {"scholar_id": scholar_id}).scalar_one()
            conn.execute(text("""
                update public.profile_status set status = 'queued', updated_at = now()
                where scholar_id = :scholar_id
            """), {"scholar_id": scholar_id})
            return str(job_id)

    def claim_refresh_job(self) -> dict | None:
        with self.engine.begin() as conn:
            row = conn.execute(text("""
                with candidate as (
                    select j.id from public.refresh_jobs j
                    where j.status = 'pending' and j.scheduled_at <= now()
                    order by j.scheduled_at for update skip locked limit 1
                )
                update public.refresh_jobs j set
                    status = 'running', attempts = attempts + 1,
                    started_at = now(), locked_at = now(), updated_at = now()
                from candidate c, public.scholars s
                where j.id = c.id and s.id = j.scholar_id
                returning j.id, j.scholar_id, s.source_author_id as author_id,
                          j.reason, j.attempts, j.status
            """
            )).mappings().first()
            if row:
                conn.execute(text("""
                    update public.profile_status set status = 'updating', updated_at = now()
                    where scholar_id = :scholar_id
                """), {"scholar_id": row["scholar_id"]})
        return dict(row) if row else None

    def complete_refresh_job(self, job_id: str) -> None:
        with self.engine.begin() as conn:
            conn.execute(text("""
                update public.refresh_jobs set status = 'succeeded', finished_at = now(), updated_at = now()
                where id = cast(:job_id as uuid)
            """), {"job_id": job_id})

    def fail_refresh_job(self, job_id: str, error: str, retry: bool) -> None:
        with self.engine.begin() as conn:
            scholar_id = conn.execute(text("""
                update public.refresh_jobs set
                    status = case when :retry then 'pending' else 'failed' end,
                    last_error = :error,
                    scheduled_at = case when :retry then now() + make_interval(mins => power(2, attempts)::int) else scheduled_at end,
                    finished_at = case when :retry then null else now() end,
                    updated_at = now()
                where id = cast(:job_id as uuid)
                returning scholar_id
            """), {"job_id": job_id, "error": error[:4000], "retry": retry}).scalar_one_or_none()
            if scholar_id:
                conn.execute(text("""
                    update public.profile_status
                    set status = case when :retry then 'queued' else 'failed' end, updated_at = now()
                    where scholar_id = :scholar_id
                """), {"scholar_id": scholar_id, "retry": retry})

    def create_login_token(
        self,
        email: str,
        token_hash: str,
        expires_at: datetime,
        request_ip: str | None = None,
    ) -> None:
        normalized_email = email.strip().lower()
        with self.engine.begin() as conn:
            conn.execute(
                text("select pg_advisory_xact_lock(hashtextextended(:email, 0))"),
                {"email": normalized_email},
            )
            email_count = conn.execute(text("""
                select count(*) from public.auth_login_tokens
                where normalized_email = :email
                  and created_at >= now() - interval '15 minutes'
            """), {"email": normalized_email}).scalar_one()
            ip_count = 0
            if request_ip:
                ip_count = conn.execute(text("""
                    select count(*) from public.auth_login_tokens
                    where request_ip = cast(:request_ip as inet)
                      and created_at >= now() - interval '15 minutes'
                """), {"request_ip": request_ip}).scalar_one()
            if email_count >= 3 or ip_count >= 20:
                raise LoginRateLimitExceeded("Too many login emails requested")
            conn.execute(text("""
                insert into public.auth_login_tokens (
                    email, normalized_email, token_hash, expires_at, request_ip
                ) values (
                    :email, :normalized_email, :token_hash, :expires_at,
                    cast(:request_ip as inet)
                )
            """), {
                "email": email.strip(),
                "normalized_email": normalized_email,
                "token_hash": token_hash,
                "expires_at": expires_at,
                "request_ip": request_ip,
            })

    def consume_login_token(
        self,
        token_hash: str,
        session_hash: str,
        session_expires_at: datetime,
        user_agent: str = "",
        request_ip: str | None = None,
    ) -> dict | None:
        with self.engine.begin() as conn:
            token = conn.execute(text("""
                update public.auth_login_tokens
                set consumed_at = now()
                where token_hash = :token_hash
                  and consumed_at is null
                  and expires_at > now()
                returning email, normalized_email
            """), {"token_hash": token_hash}).mappings().first()
            if not token:
                return None
            user = conn.execute(text("""
                insert into public.app_users (email, normalized_email, last_login_at)
                values (:email, :normalized_email, now())
                on conflict (normalized_email) do update set
                    email = excluded.email,
                    last_login_at = now(),
                    updated_at = now()
                returning id, email, is_active
            """), dict(token)).mappings().one()
            if not user["is_active"]:
                return None
            conn.execute(text("""
                insert into public.user_sessions (
                    user_id, token_hash, expires_at, user_agent, request_ip
                ) values (
                    :user_id, :token_hash, :expires_at, :user_agent,
                    cast(:request_ip as inet)
                )
            """), {
                "user_id": user["id"],
                "token_hash": session_hash,
                "expires_at": session_expires_at,
                "user_agent": user_agent[:1000],
                "request_ip": request_ip,
            })
        return {"id": str(user["id"]), "email": user["email"]}

    def get_user_by_session(self, session_hash: str) -> dict | None:
        with self.engine.begin() as conn:
            row = conn.execute(text("""
                select u.id, u.email
                from public.user_sessions s
                join public.app_users u on u.id = s.user_id
                where s.token_hash = :token_hash
                  and s.revoked_at is null
                  and s.expires_at > now()
                  and u.is_active
            """), {"token_hash": session_hash}).mappings().first()
            if row:
                conn.execute(text("""
                    update public.user_sessions
                    set last_seen_at = now()
                    where token_hash = :token_hash
                      and last_seen_at < now() - interval '5 minutes'
                """), {"token_hash": session_hash})
        return {"id": str(row["id"]), "email": row["email"]} if row else None

    def revoke_session(self, session_hash: str) -> None:
        with self.engine.begin() as conn:
            conn.execute(text("""
                update public.user_sessions set revoked_at = now()
                where token_hash = :token_hash and revoked_at is null
            """), {"token_hash": session_hash})

    def run_maintenance(self) -> dict:
        """Enqueue stale profiles and remove expired operational records."""
        with self.engine.begin() as conn:
            locked = conn.execute(text(
                "select pg_try_advisory_xact_lock(hashtextextended('scholar-maintenance', 0))"
            )).scalar_one()
            if not locked:
                return {"enqueued": 0, "deleted": 0}

            conn.execute(text("""
                update public.refresh_jobs
                set status = case when attempts < 3 then 'pending' else 'failed' end,
                    scheduled_at = case when attempts < 3 then now() else scheduled_at end,
                    finished_at = case when attempts < 3 then null else now() end,
                    last_error = 'worker lease expired',
                    locked_at = null,
                    updated_at = now()
                where status = 'running'
                  and locked_at < now() - interval '30 minutes'
            """))
            conn.execute(text("""
                update public.profile_status ps
                set status = 'failed', updated_at = now()
                where exists (
                    select 1 from public.refresh_jobs j
                    where j.scholar_id = ps.scholar_id
                      and j.status = 'failed'
                      and j.last_error = 'worker lease expired'
                )
            """))

            enqueued = conn.execute(text("""
                insert into public.refresh_jobs (scholar_id, reason, status, scheduled_at)
                select s.id,
                       case when exists (
                           select 1 from public.favorites f where f.scholar_id = s.id
                       ) then 'favorite' else 'recent_access' end,
                       'pending', now()
                from public.scholars s
                where s.last_synced_at is not null
                  and (
                    (exists (select 1 from public.favorites f where f.scholar_id = s.id)
                     and s.last_synced_at <= now() - interval '24 hours')
                    or
                    (s.last_accessed_at >= now() - interval '30 days'
                     and s.last_synced_at <= now() - interval '7 days')
                  )
                on conflict do nothing
            """)).rowcount
            conn.execute(text("""
                update public.profile_status ps
                set status = 'queued', updated_at = now()
                where exists (
                    select 1 from public.refresh_jobs j
                    where j.scholar_id = ps.scholar_id and j.status = 'pending'
                ) and not exists (
                    select 1 from public.refresh_jobs j
                    where j.scholar_id = ps.scholar_id and j.status = 'running'
                )
            """))
            deleted = 0
            for statement in (
                "delete from public.refresh_jobs where status in ('succeeded', 'failed') and updated_at < now() - interval '30 days'",
                "delete from public.auth_login_tokens where expires_at < now() - interval '1 day'",
                "delete from public.user_sessions where expires_at < now() - interval '7 days' or revoked_at < now() - interval '7 days'",
            ):
                deleted += conn.execute(text(statement)).rowcount
        return {"enqueued": enqueued, "deleted": deleted}

    def healthcheck(self) -> bool:
        with self.engine.connect() as conn:
            return conn.execute(text("select 1")).scalar_one() == 1


class UnavailableRepository:
    def __init__(self, message: str):
        self.message = message

    def __getattr__(self, _name):
        raise RepositoryNotConfigured(self.message)

    def healthcheck(self) -> bool:
        return False


def create_repository():
    if os.getenv("REPOSITORY_BACKEND") == "memory":
        return InMemoryRepository()
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        return UnavailableRepository("DATABASE_URL is required for PostgreSQL")
    return PostgresRepository(database_url)
