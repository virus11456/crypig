"""Bounded background refresh: readers never wait for an upstream service."""
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
import time


class SnapshotCache:
    def __init__(self, workers=2, retry_seconds=60):
        self._executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="snapshot")
        self._lock = Lock()
        self._entries = {}
        self.retry_seconds = retry_seconds

    def read(self, key, loader, ttl):
        with self._lock:
            entry = self._entries.setdefault(key, {
                "data": None, "updated_at": None, "refreshing": False,
                "retry_at": 0, "error": False,
            })
            now = time.time()
            stale = entry["updated_at"] is None or now - entry["updated_at"] >= ttl
            if stale and not entry["refreshing"] and now >= entry["retry_at"]:
                entry["refreshing"] = True
                self._executor.submit(self._refresh, key, loader)
            return entry["data"], {
                "updated_at": entry["updated_at"], "stale": stale,
                "refreshing": entry["refreshing"], "refresh_failed": entry["error"],
            }

    def _refresh(self, key, loader):
        try:
            value = loader()
            if not value or not value.get("history"):
                raise ValueError("No usable history")
        except Exception:
            with self._lock:
                self._entries[key].update(refreshing=False, error=True,
                                          retry_at=time.time() + self.retry_seconds)
        else:
            with self._lock:
                self._entries[key].update(data=value, updated_at=time.time(),
                                          refreshing=False, error=False, retry_at=0)

    def close(self):
        self._executor.shutdown(wait=False, cancel_futures=True)
