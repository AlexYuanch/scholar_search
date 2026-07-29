"""Version-aware in-process cache for deterministic intelligence results."""
from __future__ import annotations

from collections import OrderedDict
from copy import deepcopy
from dataclasses import dataclass, field
from threading import Lock, RLock
from time import monotonic
from typing import Callable
from weakref import WeakKeyDictionary

from intelligence_repository import intelligence_snapshot_token
from scholar_intelligence import (
    ANALYSIS_VERSION,
    build_scholar_intelligence,
    compare_scholar_intelligence,
)


@dataclass
class _CacheEntry:
    expires_at: float
    payload: dict


@dataclass
class _RepositoryCache:
    entries: OrderedDict[tuple, _CacheEntry] = field(
        default_factory=OrderedDict
    )
    in_flight: dict[tuple, Lock] = field(default_factory=dict)
    hits: int = 0
    misses: int = 0


class ScholarIntelligenceService:
    """Compute once per graph snapshot and return caller-owned payload copies."""

    def __init__(
        self,
        *,
        max_entries: int = 32,
        ttl_seconds: float = 300,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        if max_entries < 1:
            raise ValueError("max_entries must be positive")
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        self._max_entries = max_entries
        self._ttl_seconds = ttl_seconds
        self._clock = clock
        self._lock = RLock()
        self._repositories: WeakKeyDictionary = WeakKeyDictionary()

    def analyze(self, repository, author_id: str, *, limit: int = 8) -> dict:
        snapshot = intelligence_snapshot_token(repository, [author_id])
        key = ("analysis", ANALYSIS_VERSION, author_id, limit, snapshot)
        return self._get_or_build(
            repository,
            key,
            lambda: build_scholar_intelligence(
                repository,
                author_id,
                limit=limit,
            ),
        )

    def compare(
        self,
        repository,
        left_author_id: str,
        right_author_id: str,
        *,
        mode: str = "scholar",
    ) -> dict:
        snapshot = intelligence_snapshot_token(
            repository,
            [left_author_id, right_author_id],
        )
        key = (
            "comparison",
            ANALYSIS_VERSION,
            mode,
            left_author_id,
            right_author_id,
            snapshot,
        )
        return self._get_or_build(
            repository,
            key,
            lambda: compare_scholar_intelligence(
                repository,
                left_author_id,
                right_author_id,
                mode=mode,
            ),
        )

    def cache_info(self, repository) -> dict:
        with self._lock:
            cache = self._repositories.get(repository)
            return {
                "entries": len(cache.entries) if cache else 0,
                "hits": cache.hits if cache else 0,
                "misses": cache.misses if cache else 0,
                "in_flight": len(cache.in_flight) if cache else 0,
            }

    def _repository_cache(self, repository) -> _RepositoryCache:
        cache = self._repositories.get(repository)
        if cache is None:
            cache = _RepositoryCache()
            self._repositories[repository] = cache
        return cache

    def _cached_payload(
        self,
        cache: _RepositoryCache,
        key: tuple,
    ) -> dict | None:
        entry = cache.entries.get(key)
        if entry is None:
            return None
        if entry.expires_at <= self._clock():
            cache.entries.pop(key, None)
            return None
        cache.entries.move_to_end(key)
        cache.hits += 1
        return deepcopy(entry.payload)

    def _get_or_build(
        self,
        repository,
        key: tuple,
        builder: Callable[[], dict],
    ) -> dict:
        with self._lock:
            cache = self._repository_cache(repository)
            cached = self._cached_payload(cache, key)
            if cached is not None:
                return cached
            build_lock = cache.in_flight.setdefault(key, Lock())

        try:
            with build_lock:
                with self._lock:
                    cached = self._cached_payload(cache, key)
                    if cached is not None:
                        return cached
                    cache.misses += 1
                payload = builder()
                with self._lock:
                    cache.entries[key] = _CacheEntry(
                        expires_at=self._clock() + self._ttl_seconds,
                        payload=deepcopy(payload),
                    )
                    cache.entries.move_to_end(key)
                    while len(cache.entries) > self._max_entries:
                        cache.entries.popitem(last=False)
                return deepcopy(payload)
        finally:
            with self._lock:
                if cache.in_flight.get(key) is build_lock:
                    cache.in_flight.pop(key, None)
