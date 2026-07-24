"""Portable PostgreSQL repository and an isolated in-memory test implementation."""
from __future__ import annotations

import json
import math
import os
import threading
import uuid
from hashlib import sha256
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError


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


def _analysis_topics_by_index(state: dict) -> dict[int, list[str]]:
    topics_by_index: dict[int, list[str]] = {}
    for cluster in state.get("topic_clusters") or []:
        topic = str(cluster.get("topic") or "").strip()
        if not topic:
            continue
        for raw_index in cluster.get("paper_indices") or []:
            try:
                index = int(raw_index)
            except (TypeError, ValueError):
                continue
            topics = topics_by_index.setdefault(index, [])
            if topic not in topics:
                topics.append(topic)
    return topics_by_index


def _normalize_topic(value: Any) -> str:
    return " ".join(str(value or "").casefold().split())


def _work_matches_topic(work: dict, topic: str) -> bool:
    expected = _normalize_topic(topic)
    if not expected:
        return True
    if expected in _normalize_topic(work.get("title")):
        return True
    for value in work.get("analysis_topics") or work.get("topics") or []:
        label = value if isinstance(value, str) else value.get("display_name")
        if _normalize_topic(label) == expected:
            return True
    primary_topic = work.get("primary_topic") or {}
    if _normalize_topic(primary_topic.get("display_name")) == expected:
        return True
    for field in ("keywords", "concepts"):
        for value in work.get(field) or []:
            if _normalize_topic(value.get("display_name")) == expected:
                return True
    return False


def _work_payload(work: dict, analysis_topics: list[str] | None = None) -> dict:
    return {
        "id": work.get("id", ""),
        "title": work.get("title", ""),
        "year": work.get("publication_year"),
        "citations": work.get("cited_by_count", 0) or 0,
        "journal": work.get("adjudicated_journal") or ((work.get("primary_location") or {}).get("source") or {}).get("display_name", ""),
        "doi": work.get("doi", ""),
        "source_records": deepcopy(work.get("source_records") or []),
        "verification_status": work.get("verification_status", ""),
        "topics": list(analysis_topics or work.get("analysis_topics") or []),
    }


def _research_change_summary(payload: dict) -> list[dict]:
    """Return deterministic recent direction changes from the current profile payload."""
    timeline = payload.get("interestTimeline") or []
    usable_years = [
        int(item.get("year"))
        for item in timeline
        if item.get("year") is not None and item.get("topics")
    ]
    if not usable_years:
        return []
    latest_year = max(usable_years)
    current_start = latest_year - 2
    previous_start = current_start - 3
    previous: dict[str, int] = {}
    current: dict[str, int] = {}
    for item in timeline:
        year = int(item.get("year") or 0)
        target = (
            current if current_start <= year <= latest_year
            else previous if previous_start <= year < current_start
            else None
        )
        if target is None:
            continue
        for topic in item.get("topics") or []:
            name = str(topic.get("topic") or "").strip()
            count = int(topic.get("count") or 0)
            if name and count > 0:
                target[name] = target.get(name, 0) + count

    previous_total = sum(previous.values())
    current_total = sum(current.values())
    if not current_total:
        return []
    changes = []
    for topic in set(previous) | set(current):
        previous_count = previous.get(topic, 0)
        current_count = current.get(topic, 0)
        previous_share = previous_count / previous_total if previous_total else 0
        current_share = current_count / current_total
        delta = current_share - previous_share
        kind = ""
        if current_count > 0 and previous_count == 0:
            kind = "emerging"
        elif delta >= 0.04 or (delta >= 0.02 and current_share >= previous_share * 1.5):
            kind = "rising"
        elif delta <= -0.04 or (delta <= -0.02 and previous_share >= current_share * 1.5):
            kind = "falling"
        if kind:
            changes.append({
                "topic": topic,
                "kind": kind,
                "previous_count": previous_count,
                "current_count": current_count,
            })
    return sorted(
        changes,
        key=lambda item: max(item["previous_count"], item["current_count"]),
        reverse=True,
    )[:5]


class RepositoryNotConfigured(RuntimeError):
    pass


class LoginRateLimitExceeded(RuntimeError):
    pass


class UsernameTaken(RuntimeError):
    pass


class RegistrationRateLimitExceeded(RuntimeError):
    pass


class APIQuotaExceeded(RuntimeError):
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
        self.login_attempts: list[dict] = []
        self.registration_attempts: list[dict] = []
        self.api_rate_limit_events: list[dict] = []
        self.sessions: dict[str, dict] = {}
        self.openalex_search_cache: dict[str, dict] = {}
        self.openalex_identity_cache: dict[str, dict] = {}
        self.openalex_search_jobs: dict[str, dict] = {}
        self.upstream_rate_limits: dict[str, dict] = {}
        self.user_api_credentials: dict[tuple[str, str], dict] = {}

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
            scholar["raw_json"] = deepcopy(author_profile)
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
            analysis_topics = _analysis_topics_by_index(state)
            works = [
                _work_payload(work, analysis_topics.get(index))
                for index, work in enumerate(state.get("deduped_works") or [])
            ]
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

    def list_works(
        self,
        author_id: str,
        limit: int,
        offset: int,
        sort: str,
        year: int | None = None,
        topic: str | None = None,
    ) -> dict:
        items = list(self.works.get(author_id, []))
        if year is not None:
            items = [item for item in items if item.get("year") == year]
        if topic:
            items = [item for item in items if _work_matches_topic(item, topic)]
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
            profile = self.profiles.get(author_id) or {}
            payload = profile.get("payload") or {}
            row = {
                "author_id": author_id,
                "scholar_id": scholar["id"],
                "name": scholar.get("name", ""),
                "created_at": _iso(),
                "last_seen_profile_version": int(profile.get("profile_version", 0)),
                "last_seen_total_papers": int(payload.get("totalPapers", 0)),
                "last_seen_total_citations": int(payload.get("totalCitations", 0)),
                "last_seen_at": _iso(),
            }
            self.favorites[(user_id, author_id)] = row
            return deepcopy(row)

    def is_tracking(self, user_id: str, author_id: str) -> bool:
        return (user_id, author_id) in self.favorites

    def remove_favorite(self, user_id: str, author_id: str) -> None:
        self.favorites.pop((user_id, author_id), None)

    def list_favorites(self, user_id: str) -> list[dict]:
        rows = []
        for (uid, author_id), favorite in self.favorites.items():
            if uid != user_id:
                continue
            row = deepcopy(favorite)
            profile = self.profiles.get(author_id) or {}
            payload = profile.get("payload") or {}
            current_papers = int(payload.get("totalPapers", 0))
            current_citations = int(payload.get("totalCitations", 0))
            new_papers = max(0, current_papers - int(row.get("last_seen_total_papers", 0)))
            new_citations = max(0, current_citations - int(row.get("last_seen_total_citations", 0)))
            current_version = int(profile.get("profile_version", 0))
            unseen_version = current_version > int(row.get("last_seen_profile_version", 0))
            research_changes = _research_change_summary(payload) if unseen_version else []
            latest_job = next(
                (
                    job for job in sorted(
                        self.jobs.values(),
                        key=lambda item: item.get("scheduled_at", ""),
                        reverse=True,
                    )
                    if job["author_id"] == author_id
                    and job.get("requested_by_user_id") == user_id
                ),
                {},
            )
            row.update({
                "institution": payload.get("institution", ""),
                "total_papers": current_papers,
                "total_citations": current_citations,
                "h_index": int(payload.get("hIndex", 0)),
                "updated_at": profile.get("updated_at"),
                "profile_version": current_version,
                "refresh_status": profile.get("refresh_status", "ready"),
                "refresh_error": latest_job.get("last_error"),
                "new_papers": new_papers,
                "new_citations": new_citations,
                "research_changes": research_changes,
                "has_research_changes": bool(research_changes),
                "has_updates": new_papers > 0 or new_citations > 0 or bool(research_changes),
            })
            rows.append(row)
        return sorted(rows, key=lambda row: row["created_at"], reverse=True)

    def mark_favorite_seen(self, user_id: str, author_id: str, profile_version: int) -> None:
        with self._lock:
            row = self.favorites.get((user_id, author_id))
            profile = self.profiles.get(author_id)
            if not row or not profile:
                return
            current_version = int(profile.get("profile_version", 0))
            row["last_seen_profile_version"] = max(
                int(row.get("last_seen_profile_version", 0)),
                min(profile_version, current_version),
            )
            if current_version <= profile_version:
                payload = profile.get("payload") or {}
                row["last_seen_total_papers"] = int(payload.get("totalPapers", 0))
                row["last_seen_total_citations"] = int(payload.get("totalCitations", 0))
            row["last_seen_at"] = _iso()

    def enqueue_refresh(
        self,
        author_id: str,
        reason: str,
        requested_by_user_id: str | None = None,
    ) -> str:
        with self._lock:
            scholar = self._scholar(author_id)
            for job in self.jobs.values():
                if job["author_id"] == author_id and job["status"] in {"pending", "running"}:
                    if author_id in self.profiles:
                        status = (
                            "updating" if job["status"] == "running" else "queued"
                        )
                        self.profiles[author_id]["refresh_status"] = status
                        self.profiles[author_id]["payload"]["refreshStatus"] = status
                    return job["id"]
            job_id = str(uuid.uuid4())
            self.jobs[job_id] = {
                "id": job_id,
                "scholar_id": scholar["id"],
                "author_id": author_id,
                "reason": reason,
                "requested_by_user_id": requested_by_user_id,
                "status": "pending",
                "attempts": 0,
                "scheduled_at": _iso(),
            }
            if author_id in self.profiles:
                self.profiles[author_id]["refresh_status"] = "queued"
                self.profiles[author_id]["payload"]["refreshStatus"] = "queued"
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
            if job["author_id"] in self.profiles:
                self.profiles[job["author_id"]]["refresh_status"] = "updating"
                self.profiles[job["author_id"]]["payload"]["refreshStatus"] = "updating"
            return deepcopy(job)

    def complete_refresh_job(self, job_id: str) -> None:
        with self._lock:
            self.jobs[job_id].update(status="succeeded", finished_at=_iso())

    def fail_refresh_job(self, job_id: str, error: str, retry: bool) -> None:
        with self._lock:
            job = self.jobs[job_id]
            job.update(
                status="pending" if retry else "failed",
                last_error=error,
                finished_at=None if retry else _iso(),
                scheduled_at=_iso(_now() + timedelta(minutes=2 ** job["attempts"])),
            )
            if job["author_id"] in self.profiles:
                status = "queued" if retry else "failed"
                self.profiles[job["author_id"]]["refresh_status"] = status
                self.profiles[job["author_id"]]["payload"]["refreshStatus"] = status

    def get_openalex_search_cache(self, query_key: str) -> dict | None:
        with self._lock:
            row = self.openalex_search_cache.get(query_key)
            if not row:
                return None
            result = deepcopy(row)
            result["fresh"] = row["expires_at"] > _now()
            result["expires_at"] = _iso(row["expires_at"])
            return result

    def search_local_openalex_authors(self, query_text: str, limit: int = 50) -> list[dict]:
        normalized = " ".join(query_text.casefold().split())
        with self._lock:
            matches = []
            for scholar in self.scholars.values():
                names = {
                    str(scholar.get("name") or "").casefold(),
                    *(
                        str(value).casefold()
                        for value in (scholar.get("raw_json") or {}).get(
                            "display_name_alternatives", []
                        )
                    ),
                }
                if normalized not in names:
                    continue
                author = deepcopy(scholar.get("raw_json") or {})
                author.setdefault("id", scholar["author_id"])
                author.setdefault("display_name", scholar.get("name") or query_text)
                matches.append(author)
            return matches[:limit]

    def save_openalex_search_cache(
        self,
        query_key: str,
        query_text: str,
        candidates: list[dict],
        ttl_seconds: int,
    ) -> None:
        with self._lock:
            previous = self.openalex_search_cache.get(query_key) or {}
            self.openalex_search_cache[query_key] = {
                "query_key": query_key,
                "query_text": query_text,
                "candidates": deepcopy(candidates),
                "expires_at": _now() + timedelta(seconds=max(1, ttl_seconds)),
                "created_at": previous.get("created_at") or _iso(),
                "updated_at": _iso(),
            }

    def get_openalex_identity_cache(self, author_id: str) -> dict | None:
        with self._lock:
            row = self.openalex_identity_cache.get(author_id)
            if not row:
                return None
            result = deepcopy(row)
            result["fresh"] = row["expires_at"] > _now()
            result["expires_at"] = _iso(row["expires_at"])
            return result

    def get_openalex_identity_caches(self, author_ids: list[str]) -> dict[str, dict]:
        return {
            author_id: cached
            for author_id in dict.fromkeys(author_ids)
            if (cached := self.get_openalex_identity_cache(author_id)) is not None
        }

    def save_openalex_identity_cache(
        self,
        author_id: str,
        fingerprint: dict,
        ttl_seconds: int,
    ) -> None:
        with self._lock:
            previous = self.openalex_identity_cache.get(author_id) or {}
            self.openalex_identity_cache[author_id] = {
                "author_id": author_id,
                "fingerprint": deepcopy(fingerprint),
                "expires_at": _now() + timedelta(seconds=max(1, ttl_seconds)),
                "created_at": previous.get("created_at") or _iso(),
                "updated_at": _iso(),
            }

    def enqueue_openalex_search(
        self,
        query_key: str,
        query_text: str,
        requested_by_user_id: str | None = None,
    ) -> str:
        with self._lock:
            for job in self.openalex_search_jobs.values():
                if job["query_key"] == query_key and job["status"] in {"pending", "running"}:
                    return job["id"]
            job_id = str(uuid.uuid4())
            self.openalex_search_jobs[job_id] = {
                "id": job_id,
                "query_key": query_key,
                "query_text": query_text,
                "requested_by_user_id": requested_by_user_id,
                "status": "pending",
                "attempts": 0,
                "scheduled_at": _now(),
                "created_at": _iso(),
            }
            return job_id

    def claim_openalex_search_job(self, query_key: str | None = None) -> dict | None:
        with self._lock:
            pending = [
                job for job in self.openalex_search_jobs.values()
                if job["status"] == "pending"
                and job["scheduled_at"] <= _now()
                and (query_key is None or job["query_key"] == query_key)
            ]
            if not pending:
                return None
            job = sorted(pending, key=lambda row: row["scheduled_at"])[0]
            job["status"] = "running"
            job["attempts"] += 1
            job["started_at"] = _iso()
            job["locked_at"] = _iso()
            return deepcopy(job)

    def complete_openalex_search_job(self, job_id: str) -> None:
        with self._lock:
            self.openalex_search_jobs[job_id].update(
                status="succeeded",
                finished_at=_iso(),
                updated_at=_iso(),
            )

    def fail_openalex_search_job(
        self,
        job_id: str,
        error: str,
        retry: bool,
        retry_after_seconds: int | None = None,
    ) -> None:
        with self._lock:
            job = self.openalex_search_jobs[job_id]
            delay = retry_after_seconds or (2 ** max(1, int(job["attempts"])) * 60)
            job.update(
                status="pending" if retry else "failed",
                last_error=error[:4000],
                scheduled_at=_now() + timedelta(seconds=max(1, delay)),
                locked_at=None,
                finished_at=None if retry else _iso(),
                updated_at=_iso(),
            )

    def record_upstream_rate_limit(
        self,
        provider: str,
        limit_credits: int | None,
        remaining_credits: int | None,
        reset_after_seconds: int | None,
    ) -> None:
        with self._lock:
            previous = self.upstream_rate_limits.get(provider) or {}
            self.upstream_rate_limits[provider] = {
                "provider": provider,
                "limit_credits": limit_credits
                if limit_credits is not None else previous.get("limit_credits"),
                "remaining_credits": remaining_credits
                if remaining_credits is not None else previous.get("remaining_credits"),
                "reset_at": (
                    _now() + timedelta(seconds=max(0, reset_after_seconds))
                    if reset_after_seconds is not None
                    else previous.get("reset_at")
                ),
                "updated_at": _iso(),
            }

    def get_upstream_retry_after(self, provider: str, min_remaining_credits: int) -> int | None:
        with self._lock:
            row = self.upstream_rate_limits.get(provider)
            if not row or row.get("remaining_credits") is None:
                return None
            reset_at = row.get("reset_at")
            if (
                int(row["remaining_credits"]) > min_remaining_credits
                or not isinstance(reset_at, datetime)
                or reset_at <= _now()
            ):
                return None
            return max(1, math.ceil((reset_at - _now()).total_seconds()))

    def save_user_api_credential(
        self,
        user_id: str,
        provider: str,
        encrypted_secret: str,
        key_hint: str,
    ) -> dict:
        with self._lock:
            previous = self.user_api_credentials.get((user_id, provider)) or {}
            row = {
                "user_id": user_id,
                "provider": provider,
                "encrypted_secret": encrypted_secret,
                "key_hint": key_hint,
                "validated_at": _iso(),
                "created_at": previous.get("created_at") or _iso(),
                "updated_at": _iso(),
            }
            self.user_api_credentials[(user_id, provider)] = row
            return deepcopy(row)

    def get_user_api_credential(self, user_id: str, provider: str) -> dict | None:
        row = self.user_api_credentials.get((user_id, provider))
        return deepcopy(row) if row else None

    def delete_user_api_credential(self, user_id: str, provider: str) -> bool:
        with self._lock:
            deleted = self.user_api_credentials.pop((user_id, provider), None) is not None
            for job in [*self.jobs.values(), *self.openalex_search_jobs.values()]:
                if (
                    job.get("requested_by_user_id") == user_id
                    and job.get("status") == "pending"
                ):
                    job.update(
                        status="failed",
                        last_error=f"{provider} credential removed by user",
                        finished_at=_iso(),
                        updated_at=_iso(),
                    )
                    author_id = job.get("author_id")
                    if author_id in self.profiles:
                        self.profiles[author_id]["refresh_status"] = "failed"
                        self.profiles[author_id]["payload"]["refreshStatus"] = "failed"
            return deleted

    def create_password_user(self, username: str, password_hash: str) -> dict:
        normalized_username = username.strip().casefold()
        with self._lock:
            if normalized_username in self.users:
                raise UsernameTaken("Username already exists")
            user = {
                "id": str(uuid.uuid4()),
                "username": username.strip(),
                "normalized_username": normalized_username,
                "password_hash": password_hash,
                "is_active": True,
            }
            self.users[normalized_username] = user
        return deepcopy(user)

    def set_password(self, username: str, password_hash: str) -> bool:
        user = self.users.get(username.strip().casefold())
        if not user:
            return False
        user["password_hash"] = password_hash
        for session in self.sessions.values():
            if session["user_id"] == user["id"] and not session["revoked_at"]:
                session["revoked_at"] = _now()
        return True

    def list_users(self) -> list[dict]:
        return [
            {
                "id": user["id"],
                "username": user["username"],
                "is_active": user["is_active"],
            }
            for user in sorted(self.users.values(), key=lambda item: item["normalized_username"])
        ]

    def get_user_for_login(self, username: str) -> dict | None:
        user = self.users.get(username.strip().casefold())
        return deepcopy(user) if user else None

    def enforce_login_rate_limit(self, username: str, request_ip: str | None) -> None:
        cutoff = _now() - timedelta(minutes=15)
        normalized_username = username.strip().casefold()
        failures = [row for row in self.login_attempts if not row["success"] and row["created_at"] >= cutoff]
        username_failures = sum(row["normalized_username"] == normalized_username for row in failures)
        ip_failures = sum(bool(request_ip) and row["request_ip"] == request_ip for row in failures)
        if username_failures >= 5 or ip_failures >= 20:
            raise LoginRateLimitExceeded("Too many failed login attempts")

    def record_login_attempt(self, username: str, request_ip: str | None, success: bool) -> None:
        self.login_attempts.append({
            "normalized_username": username.strip().casefold(),
            "request_ip": request_ip,
            "success": success,
            "created_at": _now(),
        })

    def enforce_registration_rate_limit(self, request_ip: str | None) -> None:
        if not request_ip:
            return
        cutoff = _now() - timedelta(hours=1)
        recent_count = sum(
            row["request_ip"] == request_ip and row["created_at"] >= cutoff
            for row in self.registration_attempts
        )
        if recent_count >= 10:
            raise RegistrationRateLimitExceeded("Too many registration attempts")

    def record_registration_attempt(self, request_ip: str | None, success: bool) -> None:
        self.registration_attempts.append({
            "request_ip": request_ip,
            "success": success,
            "created_at": _now(),
        })

    def consume_api_quota(
        self,
        action: str,
        user_id: str,
        request_ip: str | None,
        user_limit: int,
        ip_limit: int,
        window_seconds: int,
    ) -> None:
        cutoff = _now() - timedelta(seconds=window_seconds)
        with self._lock:
            recent = [
                row for row in self.api_rate_limit_events
                if row["action"] == action and row["created_at"] >= cutoff
            ]
            user_count = sum(row["user_id"] == user_id for row in recent)
            ip_count = sum(bool(request_ip) and row["request_ip"] == request_ip for row in recent)
            if user_count >= user_limit or ip_count >= ip_limit:
                raise APIQuotaExceeded("API quota exceeded")
            self.api_rate_limit_events.append({
                "action": action,
                "user_id": user_id,
                "request_ip": request_ip,
                "created_at": _now(),
            })

    def create_user_session(
        self,
        user_id: str,
        session_hash: str,
        session_expires_at: datetime,
        user_agent: str = "",
        request_ip: str | None = None,
    ) -> None:
        self.sessions[session_hash] = {
            "user_id": user_id,
            "expires_at": session_expires_at,
            "revoked_at": None,
            "user_agent": user_agent,
            "request_ip": request_ip,
        }

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
            analysis_topics = _analysis_topics_by_index(state)
            for work_index, work in enumerate(works):
                work_source_id = work.get("id")
                if not work_source_id:
                    continue
                stored_work = deepcopy(work)
                stored_work["analysis_topics"] = analysis_topics.get(work_index, [])
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
                    "raw_json": _json(stored_work),
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

    def list_works(
        self,
        author_id: str,
        limit: int,
        offset: int,
        sort: str,
        year: int | None = None,
        topic: str | None = None,
    ) -> dict:
        order = "w.publication_year desc nulls last, w.id" if sort == "year" else "w.cited_by_count desc, w.id"
        filters = [
            "s.source = 'openalex'",
            "s.source_author_id = :author_id",
        ]
        params: dict[str, Any] = {
            "author_id": author_id,
            "limit": limit,
            "offset": offset,
        }
        if year is not None:
            filters.append("w.publication_year = :year")
            params["year"] = year
        if topic:
            filters.append("""
                (
                    position(lower(:topic) in lower(w.title)) > 0
                    or lower(coalesce(w.raw_json #>> '{primary_topic,display_name}', '')) = lower(:topic)
                    or exists (
                        select 1
                        from jsonb_array_elements_text(
                            case
                                when jsonb_typeof(w.raw_json -> 'analysis_topics') = 'array'
                                then w.raw_json -> 'analysis_topics'
                                else '[]'::jsonb
                            end
                        ) as item(value)
                        where lower(item.value) = lower(:topic)
                    )
                    or exists (
                        select 1
                        from jsonb_array_elements(
                            case
                                when jsonb_typeof(w.raw_json -> 'topics') = 'array'
                                then w.raw_json -> 'topics'
                                else '[]'::jsonb
                            end
                        ) as item(value)
                        where lower(coalesce(item.value ->> 'display_name', '')) = lower(:topic)
                    )
                    or exists (
                        select 1
                        from jsonb_array_elements(
                            case
                                when jsonb_typeof(w.raw_json -> 'keywords') = 'array'
                                then w.raw_json -> 'keywords'
                                else '[]'::jsonb
                            end
                        ) as item(value)
                        where lower(coalesce(item.value ->> 'display_name', '')) = lower(:topic)
                    )
                    or exists (
                        select 1
                        from jsonb_array_elements(
                            case
                                when jsonb_typeof(w.raw_json -> 'concepts') = 'array'
                                then w.raw_json -> 'concepts'
                                else '[]'::jsonb
                            end
                        ) as item(value)
                        where lower(coalesce(item.value ->> 'display_name', '')) = lower(:topic)
                    )
                )
            """)
            params["topic"] = topic.strip()
        where_clause = " and ".join(filters)
        with self.engine.connect() as conn:
            total = conn.execute(text(f"""
                select count(*) from public.works w
                join public.authorships a on a.work_id = w.id
                join public.scholars s on s.id = a.scholar_id
                where {where_clause}
            """), params).scalar_one()
            rows = conn.execute(text(f"""
                select w.source_work_id as id, w.title, w.publication_year as year,
                       w.cited_by_count as citations, w.doi,
                       coalesce(
                           w.raw_json ->> 'adjudicated_journal',
                           w.raw_json #>> '{{primary_location,source,display_name}}',
                           ''
                       ) as journal,
                       coalesce(w.raw_json -> 'source_records', '[]'::jsonb) as source_records,
                       coalesce(w.raw_json ->> 'verification_status', '') as verification_status,
                       coalesce(w.raw_json -> 'analysis_topics', '[]'::jsonb) as topics
                from public.works w
                join public.authorships a on a.work_id = w.id
                join public.scholars s on s.id = a.scholar_id
                where {where_clause}
                order by {order}
                limit :limit offset :offset
            """), params).mappings().all()
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
                insert into public.favorites (
                    user_id, scholar_id, last_seen_profile_version,
                    last_seen_total_papers, last_seen_total_citations, last_seen_at
                )
                select cast(:user_id as uuid), s.id, coalesce(ps.version, 0),
                       coalesce((p.payload ->> 'totalPapers')::integer, 0),
                       coalesce((p.payload ->> 'totalCitations')::bigint, 0), now()
                from public.scholars s
                left join public.profile_status ps on ps.scholar_id = s.id
                left join public.scholar_profiles p on p.scholar_id = s.id
                where s.source = 'openalex' and s.source_author_id = :author_id
                on conflict (user_id, scholar_id) do update set user_id = excluded.user_id
                returning scholar_id, created_at
            """), {"user_id": user_id, "author_id": author_id}).mappings().first()
            if not row:
                raise KeyError("scholar not found")
        cached = self.get_profile(author_id)
        if not cached or not self.is_fresh(cached, max_age_days=1):
            self.enqueue_refresh(author_id, "favorite", requested_by_user_id=user_id)
        return {"author_id": author_id, "scholar_id": str(row["scholar_id"]), "created_at": _iso(row["created_at"])}

    def is_tracking(self, user_id: str, author_id: str) -> bool:
        with self.engine.connect() as conn:
            return bool(conn.execute(text("""
                select exists (
                    select 1
                    from public.favorites f
                    join public.scholars s on s.id = f.scholar_id
                    where f.user_id = cast(:user_id as uuid)
                      and s.source = 'openalex'
                      and s.source_author_id = :author_id
                )
            """), {"user_id": user_id, "author_id": author_id}).scalar_one())

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
                       p.payload, p.generated_at as updated_at, f.created_at,
                       ps.version as profile_version, ps.status as refresh_status,
                       f.last_seen_profile_version, f.last_seen_total_papers,
                       f.last_seen_total_citations, f.last_seen_at,
                       latest_job.last_error as refresh_error
                from public.favorites f
                join public.scholars s on s.id = f.scholar_id
                left join public.scholar_profiles p on p.scholar_id = s.id
                left join public.profile_status ps on ps.scholar_id = s.id
                left join lateral (
                    select j.last_error
                    from public.refresh_jobs j
                    where j.scholar_id = s.id
                      and j.requested_by_user_id = cast(:user_id as uuid)
                    order by j.updated_at desc
                    limit 1
                ) latest_job on true
                where f.user_id = cast(:user_id as uuid)
                order by f.created_at desc
            """), {"user_id": user_id}).mappings().all()
        result = []
        for raw_row in rows:
            row = dict(raw_row)
            summary = self._scholar_summary(row)
            current_papers = int(summary.get("total_papers") or 0)
            current_citations = int(summary.get("total_citations") or 0)
            new_papers = max(0, current_papers - int(row["last_seen_total_papers"] or 0))
            new_citations = max(0, current_citations - int(row["last_seen_total_citations"] or 0))
            profile_version = int(row["profile_version"] or 0)
            unseen_version = profile_version > int(row["last_seen_profile_version"] or 0)
            research_changes = _research_change_summary(row.get("payload") or {}) if unseen_version else []
            result.append(summary | {
                "created_at": _iso(row["created_at"]),
                "profile_version": profile_version,
                "refresh_status": row["refresh_status"] or "ready",
                "refresh_error": row["refresh_error"],
                "last_seen_profile_version": int(row["last_seen_profile_version"] or 0),
                "last_seen_at": _iso(row["last_seen_at"]) if row["last_seen_at"] else None,
                "new_papers": new_papers,
                "new_citations": new_citations,
                "research_changes": research_changes,
                "has_research_changes": bool(research_changes),
                "has_updates": new_papers > 0 or new_citations > 0 or bool(research_changes),
            })
        return result

    def mark_favorite_seen(self, user_id: str, author_id: str, profile_version: int) -> None:
        with self.engine.begin() as conn:
            conn.execute(text("""
                with current_profile as (
                    select s.id as scholar_id, ps.version, p.payload
                    from public.scholars s
                    join public.profile_status ps on ps.scholar_id = s.id
                    join public.scholar_profiles p on p.scholar_id = s.id
                    where s.source = 'openalex' and s.source_author_id = :author_id
                )
                update public.favorites f
                set last_seen_profile_version = greatest(
                        f.last_seen_profile_version,
                        least(:profile_version, cp.version)
                    ),
                    last_seen_total_papers = case
                        when cp.version <= :profile_version
                        then coalesce((cp.payload ->> 'totalPapers')::integer, 0)
                        else f.last_seen_total_papers
                    end,
                    last_seen_total_citations = case
                        when cp.version <= :profile_version
                        then coalesce((cp.payload ->> 'totalCitations')::bigint, 0)
                        else f.last_seen_total_citations
                    end,
                    last_seen_at = now()
                from current_profile cp
                where f.scholar_id = cp.scholar_id
                  and f.user_id = cast(:user_id as uuid)
            """), {
                "user_id": user_id,
                "author_id": author_id,
                "profile_version": max(0, profile_version),
            })

    def enqueue_refresh(
        self,
        author_id: str,
        reason: str,
        requested_by_user_id: str | None = None,
    ) -> str:
        with self.engine.begin() as conn:
            scholar_id = conn.execute(text("""
                select id from public.scholars where source = 'openalex' and source_author_id = :author_id
            """), {"author_id": author_id}).scalar_one_or_none()
            if not scholar_id:
                raise KeyError("scholar not found")
            job_id = conn.execute(text("""
                insert into public.refresh_jobs (
                    scholar_id, reason, requested_by_user_id, status, scheduled_at
                )
                values (
                    :scholar_id, :reason, cast(:requested_by_user_id as uuid), 'pending', now()
                )
                on conflict do nothing
                returning id
            """), {
                "scholar_id": scholar_id,
                "reason": reason,
                "requested_by_user_id": requested_by_user_id,
            }).scalar_one_or_none()
            if not job_id:
                job_id = conn.execute(text("""
                    select id from public.refresh_jobs
                    where scholar_id = :scholar_id and status in ('pending', 'running')
                    order by created_at limit 1
                """), {"scholar_id": scholar_id}).scalar_one()
            conn.execute(text("""
                update public.profile_status
                set status = case
                        when exists (
                            select 1 from public.refresh_jobs
                            where scholar_id = :scholar_id and status = 'running'
                        ) then 'updating'
                        else 'queued'
                    end,
                    updated_at = now()
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
                          j.reason, j.attempts, j.status, j.requested_by_user_id
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

    def get_openalex_search_cache(self, query_key: str) -> dict | None:
        with self.engine.connect() as conn:
            row = conn.execute(text("""
                select query_key, query_text, candidates, expires_at, created_at, updated_at,
                       expires_at > now() as fresh
                from public.openalex_search_cache
                where query_key = :query_key
            """), {"query_key": query_key}).mappings().first()
        if not row:
            return None
        result = dict(row)
        result["expires_at"] = _iso(result["expires_at"])
        result["created_at"] = _iso(result["created_at"])
        result["updated_at"] = _iso(result["updated_at"])
        return result

    def search_local_openalex_authors(self, query_text: str, limit: int = 50) -> list[dict]:
        normalized = " ".join(query_text.casefold().split())
        with self.engine.connect() as conn:
            rows = conn.execute(text("""
                select s.source_author_id, s.display_name, s.orcid,
                       s.works_count, s.cited_by_count, s.h_index,
                       s.raw_json, p.payload
                from public.scholars s
                left join public.scholar_profiles p on p.scholar_id = s.id
                where s.source = 'openalex'
                  and (
                      lower(btrim(s.display_name)) = :normalized
                      or exists (
                          select 1
                          from public.scholar_aliases a
                          where a.scholar_id = s.id
                            and a.normalized_alias = :normalized
                      )
                  )
                order by s.cited_by_count desc, s.id
                limit :limit
            """), {"normalized": normalized, "limit": max(1, min(limit, 100))}).mappings().all()
        result = []
        for raw_row in rows:
            row = dict(raw_row)
            author = dict(row.get("raw_json") or {})
            author.update({
                "id": row["source_author_id"],
                "display_name": row["display_name"],
                "orcid": row["orcid"],
                "works_count": int(row["works_count"] or 0),
                "cited_by_count": int(row["cited_by_count"] or 0),
                "summary_stats": {
                    **(author.get("summary_stats") or {}),
                    "h_index": int(row["h_index"] or 0),
                },
            })
            payload = row.get("payload") or {}
            if payload.get("institution") and not author.get("last_known_institutions"):
                author["last_known_institutions"] = [{
                    "display_name": payload["institution"],
                }]
            result.append(author)
        return result

    def save_openalex_search_cache(
        self,
        query_key: str,
        query_text: str,
        candidates: list[dict],
        ttl_seconds: int,
    ) -> None:
        with self.engine.begin() as conn:
            conn.execute(text("""
                insert into public.openalex_search_cache (
                    query_key, query_text, candidates, expires_at
                ) values (
                    :query_key, :query_text, cast(:candidates as jsonb),
                    now() + (:ttl_seconds * interval '1 second')
                )
                on conflict (query_key) do update set
                    query_text = excluded.query_text,
                    candidates = excluded.candidates,
                    expires_at = excluded.expires_at,
                    updated_at = now()
            """), {
                "query_key": query_key,
                "query_text": query_text,
                "candidates": _json(candidates),
                "ttl_seconds": max(1, ttl_seconds),
            })

    def get_openalex_identity_cache(self, author_id: str) -> dict | None:
        with self.engine.connect() as conn:
            row = conn.execute(text("""
                select author_id, fingerprint, expires_at, created_at, updated_at,
                       expires_at > now() as fresh
                from public.openalex_identity_cache
                where author_id = :author_id
            """), {"author_id": author_id}).mappings().first()
        if not row:
            return None
        result = dict(row)
        result["expires_at"] = _iso(result["expires_at"])
        result["created_at"] = _iso(result["created_at"])
        result["updated_at"] = _iso(result["updated_at"])
        return result

    def get_openalex_identity_caches(self, author_ids: list[str]) -> dict[str, dict]:
        unique_ids = list(dict.fromkeys(author_id for author_id in author_ids if author_id))
        if not unique_ids:
            return {}
        with self.engine.connect() as conn:
            rows = conn.execute(text("""
                select author_id, fingerprint, expires_at, created_at, updated_at,
                       expires_at > now() as fresh
                from public.openalex_identity_cache
                where author_id = any(cast(:author_ids as text[]))
            """), {"author_ids": unique_ids}).mappings().all()
        result = {}
        for raw_row in rows:
            row = dict(raw_row)
            row["expires_at"] = _iso(row["expires_at"])
            row["created_at"] = _iso(row["created_at"])
            row["updated_at"] = _iso(row["updated_at"])
            result[row["author_id"]] = row
        return result

    def save_openalex_identity_cache(
        self,
        author_id: str,
        fingerprint: dict,
        ttl_seconds: int,
    ) -> None:
        with self.engine.begin() as conn:
            conn.execute(text("""
                insert into public.openalex_identity_cache (
                    author_id, fingerprint, expires_at
                ) values (
                    :author_id, cast(:fingerprint as jsonb),
                    now() + (:ttl_seconds * interval '1 second')
                )
                on conflict (author_id) do update set
                    fingerprint = excluded.fingerprint,
                    expires_at = excluded.expires_at,
                    updated_at = now()
            """), {
                "author_id": author_id,
                "fingerprint": _json(fingerprint),
                "ttl_seconds": max(1, ttl_seconds),
            })

    def enqueue_openalex_search(
        self,
        query_key: str,
        query_text: str,
        requested_by_user_id: str | None = None,
    ) -> str:
        with self.engine.begin() as conn:
            job_id = conn.execute(text("""
                insert into public.openalex_search_jobs (
                    query_key, query_text, requested_by_user_id, status, scheduled_at
                ) values (
                    :query_key, :query_text, cast(:requested_by_user_id as uuid),
                    'pending', now()
                )
                on conflict do nothing
                returning id
            """), {
                "query_key": query_key,
                "query_text": query_text,
                "requested_by_user_id": requested_by_user_id,
            }).scalar_one_or_none()
            if not job_id:
                job_id = conn.execute(text("""
                    select id from public.openalex_search_jobs
                    where query_key = :query_key and status in ('pending', 'running')
                    order by created_at limit 1
                """), {"query_key": query_key}).scalar_one()
            return str(job_id)

    def claim_openalex_search_job(self, query_key: str | None = None) -> dict | None:
        with self.engine.begin() as conn:
            row = conn.execute(text("""
                with candidate as (
                    select id
                    from public.openalex_search_jobs
                    where status = 'pending'
                      and scheduled_at <= now()
                      and (
                          cast(:query_key as text) is null
                          or query_key = cast(:query_key as text)
                      )
                    order by scheduled_at
                    for update skip locked
                    limit 1
                )
                update public.openalex_search_jobs j set
                    status = 'running',
                    attempts = attempts + 1,
                    started_at = now(),
                    locked_at = now(),
                    updated_at = now()
                from candidate c
                where j.id = c.id
                returning j.id, j.query_key, j.query_text, j.attempts, j.status,
                          j.requested_by_user_id
            """), {"query_key": query_key}).mappings().first()
        return dict(row) if row else None

    def complete_openalex_search_job(self, job_id: str) -> None:
        with self.engine.begin() as conn:
            conn.execute(text("""
                update public.openalex_search_jobs
                set status = 'succeeded', finished_at = now(), locked_at = null, updated_at = now()
                where id = cast(:job_id as uuid)
            """), {"job_id": job_id})

    def fail_openalex_search_job(
        self,
        job_id: str,
        error: str,
        retry: bool,
        retry_after_seconds: int | None = None,
    ) -> None:
        with self.engine.begin() as conn:
            conn.execute(text("""
                update public.openalex_search_jobs set
                    status = case when :retry then 'pending' else 'failed' end,
                    last_error = :error,
                    scheduled_at = case
                        when :retry then now() + (
                            coalesce(:retry_after_seconds, power(2, greatest(attempts, 1))::int * 60)
                            * interval '1 second'
                        )
                        else scheduled_at
                    end,
                    locked_at = null,
                    finished_at = case when :retry then null else now() end,
                    updated_at = now()
                where id = cast(:job_id as uuid)
            """), {
                "job_id": job_id,
                "error": error[:4000],
                "retry": retry,
                "retry_after_seconds": retry_after_seconds,
            })

    def record_upstream_rate_limit(
        self,
        provider: str,
        limit_credits: int | None,
        remaining_credits: int | None,
        reset_after_seconds: int | None,
    ) -> None:
        with self.engine.begin() as conn:
            conn.execute(text("""
                insert into public.upstream_rate_limits (
                    provider, limit_credits, remaining_credits, reset_at
                ) values (
                    :provider, :limit_credits, :remaining_credits,
                    case
                        when :reset_after_seconds is null then null
                        else now() + (:reset_after_seconds * interval '1 second')
                    end
                )
                on conflict (provider) do update set
                    limit_credits = coalesce(excluded.limit_credits, upstream_rate_limits.limit_credits),
                    remaining_credits = coalesce(
                        excluded.remaining_credits,
                        upstream_rate_limits.remaining_credits
                    ),
                    reset_at = coalesce(excluded.reset_at, upstream_rate_limits.reset_at),
                    updated_at = now()
            """), {
                "provider": provider,
                "limit_credits": limit_credits,
                "remaining_credits": remaining_credits,
                "reset_after_seconds": reset_after_seconds,
            })

    def get_upstream_retry_after(self, provider: str, min_remaining_credits: int) -> int | None:
        with self.engine.connect() as conn:
            seconds = conn.execute(text("""
                select case
                    when remaining_credits <= :min_remaining_credits
                         and reset_at > now()
                    then greatest(1, ceil(extract(epoch from (reset_at - now())))::integer)
                    else null
                end
                from public.upstream_rate_limits
                where provider = :provider
            """), {
                "provider": provider,
                "min_remaining_credits": max(0, min_remaining_credits),
            }).scalar_one_or_none()
        return int(seconds) if seconds is not None else None

    def save_user_api_credential(
        self,
        user_id: str,
        provider: str,
        encrypted_secret: str,
        key_hint: str,
    ) -> dict:
        with self.engine.begin() as conn:
            row = conn.execute(text("""
                insert into public.user_api_credentials (
                    user_id, provider, encrypted_secret, key_hint, validated_at
                ) values (
                    cast(:user_id as uuid), :provider, :encrypted_secret, :key_hint, now()
                )
                on conflict (user_id, provider) do update set
                    encrypted_secret = excluded.encrypted_secret,
                    key_hint = excluded.key_hint,
                    validated_at = now(),
                    updated_at = now()
                returning user_id, provider, encrypted_secret, key_hint,
                          validated_at, created_at, updated_at
            """), {
                "user_id": user_id,
                "provider": provider,
                "encrypted_secret": encrypted_secret,
                "key_hint": key_hint,
            }).mappings().one()
        return {**dict(row), "user_id": str(row["user_id"])}

    def get_user_api_credential(self, user_id: str, provider: str) -> dict | None:
        with self.engine.connect() as conn:
            row = conn.execute(text("""
                select user_id, provider, encrypted_secret, key_hint,
                       validated_at, created_at, updated_at
                from public.user_api_credentials
                where user_id = cast(:user_id as uuid) and provider = :provider
            """), {"user_id": user_id, "provider": provider}).mappings().first()
        return {**dict(row), "user_id": str(row["user_id"])} if row else None

    def delete_user_api_credential(self, user_id: str, provider: str) -> bool:
        with self.engine.begin() as conn:
            deleted = conn.execute(text("""
                delete from public.user_api_credentials
                where user_id = cast(:user_id as uuid) and provider = :provider
            """), {"user_id": user_id, "provider": provider}).rowcount > 0
            error = f"{provider} credential removed by user"
            conn.execute(text("""
                update public.refresh_jobs
                set status = 'failed', last_error = :error,
                    finished_at = now(), updated_at = now()
                where requested_by_user_id = cast(:user_id as uuid)
                  and status = 'pending'
            """), {"user_id": user_id, "error": error})
            conn.execute(text("""
                update public.profile_status ps
                set status = 'failed', updated_at = now()
                where exists (
                    select 1
                    from public.refresh_jobs j
                    where j.scholar_id = ps.scholar_id
                      and j.requested_by_user_id = cast(:user_id as uuid)
                      and j.status = 'failed'
                      and j.last_error = :error
                )
                  and not exists (
                    select 1
                    from public.refresh_jobs active
                    where active.scholar_id = ps.scholar_id
                      and active.status in ('pending', 'running')
                )
            """), {"user_id": user_id, "error": error})
            conn.execute(text("""
                update public.openalex_search_jobs
                set status = 'failed', last_error = :error,
                    finished_at = now(), updated_at = now()
                where requested_by_user_id = cast(:user_id as uuid)
                  and status = 'pending'
            """), {"user_id": user_id, "error": error})
        return deleted

    def create_password_user(self, username: str, password_hash: str) -> dict:
        normalized_username = username.strip().casefold()
        try:
            with self.engine.begin() as conn:
                row = conn.execute(text("""
                    insert into public.app_users (
                        username, normalized_username, password_hash
                    ) values (
                        :username, :normalized_username, :password_hash
                    )
                    returning id, username, normalized_username, password_hash, is_active
                """), {
                    "username": username.strip(),
                    "normalized_username": normalized_username,
                    "password_hash": password_hash,
                }).mappings().one()
        except IntegrityError as exc:
            if "app_users_normalized_username" in str(exc):
                raise UsernameTaken("Username already exists") from exc
            raise
        return {**dict(row), "id": str(row["id"])}

    def set_password(self, username: str, password_hash: str) -> bool:
        with self.engine.begin() as conn:
            user_id = conn.execute(text("""
                update public.app_users
                set password_hash = :password_hash, updated_at = now()
                where normalized_username = :normalized_username
                returning id
            """), {
                "normalized_username": username.strip().casefold(),
                "password_hash": password_hash,
            }).scalar_one_or_none()
            if user_id:
                conn.execute(text("""
                    update public.user_sessions
                    set revoked_at = now()
                    where user_id = :user_id and revoked_at is null
                """), {"user_id": user_id})
        return user_id is not None

    def list_users(self) -> list[dict]:
        with self.engine.connect() as conn:
            rows = conn.execute(text("""
                select id, username, is_active
                from public.app_users
                order by normalized_username
            """)).mappings().all()
        return [
            {"id": str(row["id"]), "username": row["username"], "is_active": row["is_active"]}
            for row in rows
        ]

    def get_user_for_login(self, username: str) -> dict | None:
        with self.engine.connect() as conn:
            row = conn.execute(text("""
                select id, username, normalized_username, password_hash, is_active
                from public.app_users
                where normalized_username = :normalized_username
            """), {"normalized_username": username.strip().casefold()}).mappings().first()
        return {**dict(row), "id": str(row["id"])} if row else None

    def enforce_login_rate_limit(self, username: str, request_ip: str | None) -> None:
        normalized_username = username.strip().casefold()
        with self.engine.connect() as conn:
            username_failures = conn.execute(text("""
                select count(*) from public.auth_login_attempts
                where normalized_username = :normalized_username
                  and success = false
                  and created_at >= now() - interval '15 minutes'
            """), {"normalized_username": normalized_username}).scalar_one()
            ip_failures = 0
            if request_ip:
                ip_failures = conn.execute(text("""
                    select count(*) from public.auth_login_attempts
                    where request_ip = cast(:request_ip as inet)
                      and success = false
                      and created_at >= now() - interval '15 minutes'
                """), {"request_ip": request_ip}).scalar_one()
        if username_failures >= 5 or ip_failures >= 20:
            raise LoginRateLimitExceeded("Too many failed login attempts")

    def record_login_attempt(self, username: str, request_ip: str | None, success: bool) -> None:
        with self.engine.begin() as conn:
            conn.execute(text("""
                insert into public.auth_login_attempts (
                    normalized_username, request_ip, success
                ) values (
                    :normalized_username, cast(:request_ip as inet), :success
                )
            """), {
                "normalized_username": username.strip().casefold(),
                "request_ip": request_ip,
                "success": success,
            })

    def enforce_registration_rate_limit(self, request_ip: str | None) -> None:
        if not request_ip:
            return
        with self.engine.connect() as conn:
            recent_count = conn.execute(text("""
                select count(*) from public.auth_registration_attempts
                where request_ip = cast(:request_ip as inet)
                  and created_at >= now() - interval '1 hour'
            """), {"request_ip": request_ip}).scalar_one()
        if recent_count >= 10:
            raise RegistrationRateLimitExceeded("Too many registration attempts")

    def record_registration_attempt(self, request_ip: str | None, success: bool) -> None:
        with self.engine.begin() as conn:
            conn.execute(text("""
                insert into public.auth_registration_attempts (request_ip, success)
                values (cast(:request_ip as inet), :success)
            """), {"request_ip": request_ip, "success": success})

    def consume_api_quota(
        self,
        action: str,
        user_id: str,
        request_ip: str | None,
        user_limit: int,
        ip_limit: int,
        window_seconds: int,
    ) -> None:
        params = {
            "action": action,
            "user_id": user_id,
            "request_ip": request_ip,
            "user_limit": user_limit,
            "ip_limit": ip_limit,
            "window_seconds": window_seconds,
        }
        with self.engine.begin() as conn:
            conn.execute(text(
                "select pg_advisory_xact_lock(hashtextextended('api-user:' || :action || ':' || :user_id, 0))"
            ), params)
            if request_ip:
                conn.execute(text(
                    "select pg_advisory_xact_lock(hashtextextended('api-ip:' || :action || ':' || :request_ip, 0))"
                ), params)
            row = conn.execute(text("""
                select
                    count(*) filter (where user_id = cast(:user_id as uuid)) as user_count,
                    count(*) filter (
                        where cast(:request_ip as inet) is not null
                          and request_ip = cast(:request_ip as inet)
                    ) as ip_count
                from public.api_rate_limit_events
                where action = :action
                  and created_at >= now() - (:window_seconds * interval '1 second')
            """), params).mappings().one()
            if int(row["user_count"]) >= user_limit or int(row["ip_count"]) >= ip_limit:
                raise APIQuotaExceeded("API quota exceeded")
            conn.execute(text("""
                insert into public.api_rate_limit_events (user_id, request_ip, action)
                values (cast(:user_id as uuid), cast(:request_ip as inet), :action)
            """), params)

    def create_user_session(
        self,
        user_id: str,
        session_hash: str,
        session_expires_at: datetime,
        user_agent: str = "",
        request_ip: str | None = None,
    ) -> None:
        with self.engine.begin() as conn:
            conn.execute(text("""
                insert into public.user_sessions (
                    user_id, token_hash, expires_at, user_agent, request_ip
                ) values (
                    cast(:user_id as uuid), :token_hash, :expires_at, :user_agent,
                    cast(:request_ip as inet)
                )
            """), {
                "user_id": user_id,
                "token_hash": session_hash,
                "expires_at": session_expires_at,
                "user_agent": user_agent[:1000],
                "request_ip": request_ip,
            })
            conn.execute(text("""
                update public.app_users set last_login_at = now(), updated_at = now()
                where id = cast(:user_id as uuid)
            """), {"user_id": user_id})

    def get_user_by_session(self, session_hash: str) -> dict | None:
        with self.engine.begin() as conn:
            row = conn.execute(text("""
                select u.id, u.username
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
        return {"id": str(row["id"]), "username": row["username"]} if row else None

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
                update public.openalex_search_jobs
                set status = case when attempts < 3 then 'pending' else 'failed' end,
                    scheduled_at = case when attempts < 3 then now() else scheduled_at end,
                    finished_at = case when attempts < 3 then null else now() end,
                    last_error = 'worker lease expired',
                    locked_at = null,
                    updated_at = now()
                where status = 'running'
                  and locked_at < now() - interval '10 minutes'
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
                insert into public.refresh_jobs (
                    scholar_id, reason, requested_by_user_id, status, scheduled_at
                )
                select s.id,
                       case when exists (
                           select 1 from public.favorites f where f.scholar_id = s.id
                       ) then 'favorite' else 'recent_access' end,
                       requester.user_id, 'pending', now()
                from public.scholars s
                cross join lateral (
                    select candidate.user_id
                    from (
                        select f.user_id, 0 as priority, f.created_at as activity_at
                        from public.favorites f
                        where f.scholar_id = s.id
                        union all
                        select h.user_id, 1 as priority, h.last_viewed_at as activity_at
                        from public.user_history h
                        where h.scholar_id = s.id
                    ) candidate
                    join public.user_api_credentials credential
                      on credential.user_id = candidate.user_id
                     and credential.provider = 'openalex'
                    order by candidate.priority, candidate.activity_at desc
                    limit 1
                ) requester
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
                "delete from public.openalex_search_jobs where status in ('succeeded', 'failed') and updated_at < now() - interval '30 days'",
                "delete from public.openalex_search_cache where updated_at < now() - interval '90 days'",
                "delete from public.openalex_identity_cache where updated_at < now() - interval '180 days'",
                "delete from public.auth_login_attempts where created_at < now() - interval '1 day'",
                "delete from public.auth_registration_attempts where created_at < now() - interval '1 day'",
                "delete from public.api_rate_limit_events where created_at < now() - interval '1 day'",
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
