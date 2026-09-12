"""Independent, atomic last-known-good market snapshot for dashboard readers."""
from __future__ import annotations

import copy
import json
import logging
import math
import os
from pathlib import Path
import threading
import time

logger = logging.getLogger(__name__)


class QuoteStore:
    def __init__(self, path: str | Path, loader=None):
        self.path = Path(path)
        self._loader = loader
        self._client = None
        self._refresh_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._snapshot = {"coins": [], "fetched_at": None}
        self._failed = False
        self._persist_failed = False
        try:
            saved = json.loads(self.path.read_text())
            self._validate(saved["coins"])
            ts = saved["fetched_at"]
            if not isinstance(ts, (int, float)) or not math.isfinite(ts) or not 0 < ts <= time.time() + 60:
                raise ValueError("Invalid saved timestamp")
            self._snapshot = {"coins": saved["coins"], "fetched_at": ts}
        except (OSError, ValueError, TypeError, KeyError):
            pass

    @staticmethod
    def _validate(coins):
        if not isinstance(coins, list) or not coins:
            raise ValueError("Empty market snapshot")
        seen = set()
        for row in coins:
            if not isinstance(row, dict):
                raise ValueError("Invalid quote row")
            symbol = row.get("symbol")
            if not isinstance(symbol, str) or not symbol or symbol in seen:
                raise ValueError("Invalid or duplicate symbol")
            seen.add(symbol)
            for key in ("price", "open_interest_usd", "funding_ann", "premium"):
                value = row.get(key)
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                    raise ValueError("Invalid quote")
            if row["price"] <= 0 or row["open_interest_usd"] < 0:
                raise ValueError("Invalid price or open interest")

    def refresh(self):
        if not self._refresh_lock.acquire(blocking=False):
            return False
        try:
            if self._loader is None:
                if self._client is None:
                    from ..clients.hyperliquid import HyperliquidClient
                    self._client = HyperliquidClient()
                    self._client._mc_ttl = 0  # the scheduler owns the refresh interval
                coins = self._client.funding_scan()
            else:
                coins = self._loader()
            self._validate(coins)
            snapshot = {"coins": copy.deepcopy(coins), "fetched_at": time.time()}
            with self._state_lock:
                self._snapshot = snapshot
                self._failed = False
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                temporary = self.path.with_suffix(".tmp")
                with temporary.open("w") as stream:
                    json.dump(snapshot, stream, allow_nan=False)
                    stream.flush()
                    os.fsync(stream.fileno())
                temporary.replace(self.path)
                self._persist_failed = False
            except OSError:
                self._persist_failed = True
                logger.warning("Market snapshot persistence failed")
            return True
        except Exception:
            with self._state_lock:
                self._failed = True
            logger.warning("Market refresh failed; retaining previous snapshot")
            return False
        finally:
            self._refresh_lock.release()

    def read(self):
        with self._state_lock:
            snapshot = copy.deepcopy(self._snapshot)
            failed = self._failed
        ts = snapshot["fetched_at"]
        age = max(0, time.time() - ts) if ts is not None else None
        return snapshot["coins"], {
            "source": "hyperliquid", "fetched_at": ts,
            "age_seconds": round(age, 1) if age is not None else None,
            "stale": age is None or age > 180,
            "refresh_failed": failed, "refreshing": self._refresh_lock.locked(),
            "persist_failed": self._persist_failed,
            "timestamp_kind": "fetched_at",  # upstream context has no observation timestamp
        }
