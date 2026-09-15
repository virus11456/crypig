"""Bounded background refresh: readers never wait for an upstream service."""
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
import time
import json
import math
import hashlib
from pathlib import Path


class SnapshotCache:
    def __init__(self, workers=2, retry_seconds=60, directory=None):
        self._executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="snapshot")
        self._lock = Lock()
        self._entries = {}
        self.retry_seconds = retry_seconds
        self.directory = Path(directory) if directory else None

    def read(self, key, loader, ttl):
        with self._lock:
            if key not in self._entries:
                self._entries[key] = self._restore(key)
            entry = self._entries[key]
            now = time.time()
            stale = entry["updated_at"] is None or now - entry["updated_at"] >= ttl
            if stale and not entry["refreshing"] and now >= entry["retry_at"]:
                entry["refreshing"] = True
                self._executor.submit(self._refresh, key, loader)
            return entry["data"], {
                "updated_at": entry["updated_at"], "stale": stale,
                "refreshing": entry["refreshing"], "refresh_failed": entry["error"],
                "persist_failed": entry.get("persist_failed", False),
            }

    def _path(self, key):
        return self.directory / (hashlib.sha256(key.encode()).hexdigest() + ".json")

    def _restore(self, key):
        entry = {
                "data": None, "updated_at": None, "refreshing": False,
                "retry_at": 0, "error": False,
            }
        if self.directory:
            try:
                saved = json.loads(self._path(key).read_text())
                ts = saved["updated_at"]
                if not isinstance(ts, (int, float)) or not math.isfinite(ts) or not 0 < ts <= time.time()+60:
                    raise ValueError("Invalid cache timestamp")
                if not isinstance(saved["data"], dict) or not isinstance(saved["data"].get("history"), list) or not saved["data"]["history"]:
                    raise ValueError("Invalid cached history")
                entry.update(data=saved["data"], updated_at=ts)
            except (OSError, ValueError, TypeError, KeyError):
                pass
        return entry

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
            updated_at = time.time()
            persist_failed = False
            if self.directory:
                try:
                    self.directory.mkdir(parents=True, exist_ok=True)
                    target = self._path(key)
                    temporary = target.with_suffix(".tmp")
                    temporary.write_text(json.dumps({"data": value, "updated_at": updated_at}, allow_nan=False))
                    temporary.replace(target)
                except (OSError, ValueError):
                    persist_failed = True
            with self._lock:
                self._entries[key].update(data=value, updated_at=updated_at, persist_failed=persist_failed,
                                          refreshing=False, error=False, retry_at=0)

    def close(self):
        self._executor.shutdown(wait=False, cancel_futures=True)
