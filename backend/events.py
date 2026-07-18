"""PostgreSQL LISTEN/NOTIFY bridge used by the browser SSE endpoint."""
from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from collections import defaultdict

import psycopg


logger = logging.getLogger(__name__)


def _psycopg_url(database_url: str) -> str:
    return database_url.replace("postgresql+psycopg://", "postgresql://", 1)


class ProfileEventBroker:
    def __init__(self, database_url: str | None):
        self.database_url = _psycopg_url(database_url) if database_url else ""
        self._subscribers: dict[str, list[tuple[asyncio.AbstractEventLoop, asyncio.Queue]]] = defaultdict(list)
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def configured(self) -> bool:
        return bool(self.database_url)

    def start(self) -> None:
        if not self.configured or (self._thread and self._thread.is_alive()):
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._listen, name="profile-events", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)

    def subscribe(self, scholar_id: str) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=8)
        loop = asyncio.get_running_loop()
        with self._lock:
            self._subscribers[scholar_id].append((loop, queue))
        return queue

    def unsubscribe(self, scholar_id: str, queue: asyncio.Queue) -> None:
        with self._lock:
            subscribers = self._subscribers.get(scholar_id, [])
            self._subscribers[scholar_id] = [item for item in subscribers if item[1] is not queue]
            if not self._subscribers[scholar_id]:
                self._subscribers.pop(scholar_id, None)

    @staticmethod
    def _deliver(queue: asyncio.Queue, event: dict) -> None:
        if queue.full():
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
        queue.put_nowait(event)

    def _publish(self, event: dict) -> None:
        scholar_id = str(event.get("scholar_id", ""))
        if not scholar_id:
            return
        with self._lock:
            subscribers = list(self._subscribers.get(scholar_id, []))
        for loop, queue in subscribers:
            loop.call_soon_threadsafe(self._deliver, queue, event)

    def _listen(self) -> None:
        while not self._stop.is_set():
            try:
                with psycopg.connect(
                    self.database_url,
                    autocommit=True,
                    connect_timeout=10,
                    application_name="scholar-profile-events",
                ) as connection:
                    connection.execute("listen profile_status")
                    while not self._stop.is_set():
                        for notification in connection.notifies(timeout=2, stop_after=1):
                            try:
                                self._publish(json.loads(notification.payload))
                            except (TypeError, ValueError, json.JSONDecodeError):
                                logger.warning("Ignored malformed profile_status notification")
            except Exception as exc:  # listener must recover after database restarts
                if not self._stop.is_set():
                    logger.warning("Profile event listener reconnecting: %s", exc)
                    time.sleep(2)
