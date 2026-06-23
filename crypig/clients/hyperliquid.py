"""Hyperliquid 公開 API client。

用途：
  - 取得 leaderboard（各帳號在不同時間窗的已實現獲利 pnl）
  - 取得單一帳號的永續合約持倉（clearinghouseState）
據此可統計「聰明錢」對某標的的多空名目價值。

設計：
  - 內建 TTL 快取，避免同一輪對多個標的重複打 API
  - 單一帳號查詢失敗不影響整體（呼叫端自行容錯）

參考端點：
  - leaderboard： https://stats-data.hyperliquid.xyz/Mainnet/leaderboard
  - info（POST）：https://api.hyperliquid.xyz/info
"""
from __future__ import annotations

import time
from typing import Any

import httpx

INFO_URL = "https://api.hyperliquid.xyz/info"
LEADERBOARD_URL = "https://stats-data.hyperliquid.xyz/Mainnet/leaderboard"

# Hyperliquid 提供的時間窗（無「一年」，allTime/month 為最接近代理）
WINDOWS = {"day", "week", "month", "allTime"}


class HyperliquidClient:
    def __init__(self, timeout: float = 15.0,
                 leaderboard_ttl: float = 3600.0,
                 state_ttl: float = 300.0):
        self._client = httpx.Client(timeout=timeout,
                                    headers={"Content-Type": "application/json"})
        self._lb_ttl = leaderboard_ttl
        self._state_ttl = state_ttl
        self._lb_cache: tuple[float, list[dict]] | None = None
        self._state_cache: dict[str, tuple[float, dict]] = {}

    def close(self) -> None:
        self._client.close()

    # ---- leaderboard ----
    def fetch_leaderboard(self) -> list[dict]:
        now = time.time()
        if self._lb_cache and now - self._lb_cache[0] < self._lb_ttl:
            return self._lb_cache[1]
        resp = self._client.get(LEADERBOARD_URL)
        resp.raise_for_status()
        rows = resp.json().get("leaderboardRows", [])
        self._lb_cache = (now, rows)
        return rows

    @staticmethod
    def _window_pnl(row: dict, window: str) -> float:
        for w, perf in row.get("windowPerformances", []):
            if w == window:
                try:
                    return float(perf.get("pnl", 0.0))
                except (TypeError, ValueError):
                    return 0.0
        return 0.0

    def top_traders(self, window: str = "allTime",
                    pnl_threshold: float = 1_000_000.0,
                    limit: int = 100) -> list[tuple[str, float]]:
        """回傳 (address, pnl) ，pnl 超過門檻、依 pnl 由大到小，取前 limit 名。"""
        if window not in WINDOWS:
            raise ValueError(f"window 必須是 {WINDOWS} 之一")
        scored = [
            (row.get("ethAddress", ""), self._window_pnl(row, window))
            for row in self.fetch_leaderboard()
        ]
        qualified = [(addr, pnl) for addr, pnl in scored if addr and pnl >= pnl_threshold]
        qualified.sort(key=lambda x: x[1], reverse=True)
        return qualified[:limit]

    # ---- 持倉 ----
    def clearinghouse_state(self, address: str) -> dict[str, Any]:
        now = time.time()
        cached = self._state_cache.get(address)
        if cached and now - cached[0] < self._state_ttl:
            return cached[1]
        resp = self._client.post(INFO_URL,
                                json={"type": "clearinghouseState", "user": address})
        resp.raise_for_status()
        data = resp.json()
        self._state_cache[address] = (now, data)
        return data

    @staticmethod
    def iter_positions(state: dict) -> list[dict]:
        out = []
        for ap in state.get("assetPositions", []):
            pos = ap.get("position", {})
            if pos.get("coin"):
                out.append(pos)
        return out
