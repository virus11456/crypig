"""LunarCrush v4 社群情緒 client（合法聚合 X/Reddit 等社群資料）。

需免費 API 金鑰（env LUNARCRUSH_API_KEY），Bearer 認證，免費層 500 次/天。
一支 coins/list 呼叫即回所有幣的社群情緒，配合背景快取每天僅數十次。

欄位：
  sentiment       正面貼文佔比 %（100=全正面、50=中性、0=全負面）
  galaxy_score    LunarCrush 綜合社群+價格分數（0~100）
  social_volume   社群貼文量
  alt_rank        社群+市場綜合排名（小=強）
"""
from __future__ import annotations

import os
import time

import httpx

BASE = "https://lunarcrush.com/api4/public"


class LunarCrushClient:
    def __init__(self, timeout: float = 15.0):
        self._key = os.getenv("LUNARCRUSH_API_KEY", "")
        self._client = httpx.Client(
            timeout=timeout,
            headers={"Authorization": f"Bearer {self._key}",
                     "User-Agent": "crypig/0.1"})
        self._cache: dict | None = None
        self._ts: float = 0.0

    @property
    def enabled(self) -> bool:
        return bool(self._key)

    def fetch_coins_sentiment(self, ttl: float = 600.0) -> dict[str, dict]:
        """回 {SYMBOL: {sentiment, galaxy_score, social_volume, alt_rank}}。
        無金鑰回空；限流/失敗沿用上次快取。"""
        if not self._key:
            return {}
        if self._cache is not None and time.time() - self._ts < ttl:
            return self._cache
        try:
            r = self._client.get(f"{BASE}/coins/list/v1")
            data = r.json().get("data") if r.status_code == 200 else None
        except Exception:
            return self._cache or {}
        if not isinstance(data, list):
            return self._cache or {}
        out: dict[str, dict] = {}
        for c in data:
            if not isinstance(c, dict):
                continue
            sym = (c.get("symbol") or "").upper()
            if not sym or sym in out:
                continue
            out[sym] = {
                "sentiment": c.get("sentiment"),
                "galaxy_score": c.get("galaxy_score"),
                "social_volume": c.get("social_volume_24h") or c.get("social_volume"),
                "alt_rank": c.get("alt_rank"),
            }
        if out:
            self._cache, self._ts = out, time.time()
            return out
        return self._cache or {}

    def top_creators(self, topic: str = "bitcoin", limit: int = 10) -> list[dict]:
        """某主題的頂尖 KOL/創作者（X/YouTube…），含影響力與情緒。無金鑰回空。"""
        if not self._key:
            return []
        try:
            r = self._client.get(f"{BASE}/topic/{topic}/creators/v1")
            data = r.json().get("data") if r.status_code == 200 else None
        except Exception:
            return []
        if not isinstance(data, list):
            return []
        return data[:limit]

    def close(self) -> None:
        self._client.close()
