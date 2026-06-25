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

import concurrent.futures
import time
from typing import Any

import httpx

INFO_URL = "https://api.hyperliquid.xyz/info"
LEADERBOARD_URL = "https://stats-data.hyperliquid.xyz/Mainnet/leaderboard"

# Hyperliquid 提供的時間窗（無「一年」，allTime/month 為最接近代理）
WINDOWS = {"day", "week", "month", "allTime"}


def funding_flag(ann: float) -> str:
    """資金費率(年化小數)異常分級：hot 多單過熱 / warm 偏擁擠 /
    squeeze 空方擁擠(負費率,潛在軋空) / normal 正常。"""
    if ann > 0.50:
        return "hot"
    if ann > 0.25:
        return "warm"
    if ann < -0.05:
        return "squeeze"
    return "normal"


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
        self._mc_cache: tuple[float, dict] | None = None
        self._mc_ttl = 120.0

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

    def states_bulk(self, addresses: list[str],
                    workers: int = 8) -> dict[str, dict]:
        """並發抓多個帳號的 clearinghouseState（各自走快取）。回 {address: state}。"""
        def fetch(addr: str):
            try:
                return addr, self.clearinghouse_state(addr)
            except Exception:
                return addr, None
        out: dict[str, dict] = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
            for addr, state in ex.map(fetch, addresses):
                if state is not None:
                    out[addr] = state
        return out

    # ---- 成交紀錄（算近期勝率/獲利）----
    def user_fills(self, address: str, ttl: float = 21600.0) -> list[dict]:
        """單帳號最近成交（最多 2000 筆，含每筆平倉 closedPnl）。預設快取 6 小時。"""
        now = time.time()
        cache = getattr(self, "_fills_cache", {})
        hit = cache.get(address)
        if hit and now - hit[0] < ttl:
            return hit[1]
        resp = self._client.post(INFO_URL, json={"type": "userFills", "user": address})
        resp.raise_for_status()
        data = resp.json()
        rows = data if isinstance(data, list) else []
        cache[address] = (now, rows)
        self._fills_cache = cache
        return rows

    def fills_bulk(self, addresses: list[str], workers: int = 5,
                   ttl: float = 21600.0) -> dict[str, list]:
        """並發抓多帳號成交（節流避免速率限制；各自走快取）。回 {address: fills}。"""
        def fetch(addr: str):
            try:
                return addr, self.user_fills(addr, ttl=ttl)
            except Exception:
                return addr, None
        out: dict[str, list] = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
            for addr, fills in ex.map(fetch, addresses):
                if fills is not None:
                    out[addr] = fills
        return out

    @staticmethod
    def fills_winrate(fills: list[dict], lookback: int = 100) -> dict | None:
        """從成交算近 lookback 筆平倉的勝率、獲利、時間跨度。無足夠平倉回 None。

        span_hours：近 lookback 筆平倉橫跨幾小時——用來剔除『幾小時內刷完上百筆』
        的高頻/做市商（他們多空中性，方向訊號無意義）。fills 為新到舊排列。
        """
        closes = [x for x in fills if (x.get("closedPnl") not in (None, "0", "0.0")
                                       and float(x.get("closedPnl") or 0) != 0.0)]
        closes = closes[:lookback]
        if not closes:
            return None
        pnls = [float(x.get("closedPnl") or 0) for x in closes]
        wins = sum(1 for p in pnls if p > 0)
        try:
            span_hours = (int(closes[0]["time"]) - int(closes[-1]["time"])) / 3_600_000
        except Exception:
            span_hours = 0.0
        return {"trades": len(closes), "win_rate": wins / len(closes),
                "recent_pnl": sum(pnls), "span_hours": round(span_hours, 1)}


    # ---- 全市場脈絡（持倉量 / 資金費率）----
    def market_contexts(self) -> dict[str, dict]:
        """回傳每個幣的 {funding, open_interest, mark_px, premium}（全市場，含快取）。

        funding 為「每小時」費率（小數）；open_interest 單位為幣數量。
        """
        now = time.time()
        if self._mc_cache and now - self._mc_cache[0] < self._mc_ttl:
            return self._mc_cache[1]
        resp = self._client.post(INFO_URL, json={"type": "metaAndAssetCtxs"})
        resp.raise_for_status()
        meta, ctxs = resp.json()
        out: dict[str, dict] = {}
        for u, ctx in zip(meta.get("universe", []), ctxs):
            name = u.get("name")
            if not name:
                continue
            out[name] = {
                "funding": float(ctx.get("funding", 0.0) or 0.0),
                "open_interest": float(ctx.get("openInterest", 0.0) or 0.0),
                "mark_px": float(ctx.get("markPx", 0.0) or 0.0),
                "premium": float(ctx.get("premium", 0.0) or 0.0),
            }
        self._mc_cache = (now, out)
        return out

    def funding_scan(self) -> list[dict]:
        """全市場資金費率掃描：每幣年化資金費率、OI(USD)、溢價、異常分級。

        funding(每小時) → 年化 ×24×365。依 |年化費率| 由大到小排序。
        """
        out: list[dict] = []
        for name, v in self.market_contexts().items():
            ann = v["funding"] * 24 * 365
            out.append({
                "symbol": name,
                "price": v["mark_px"],
                "funding_ann": ann,
                "open_interest_usd": v["open_interest"] * v["mark_px"],
                "premium": v["premium"],
                "funding_flag": funding_flag(ann),
            })
        out.sort(key=lambda r: abs(r["funding_ann"]), reverse=True)
        return out

    def daily_closes_bulk(self, coins: list[str], days: int = 45,
                          workers: int = 8) -> dict[str, tuple[list[float], list[float]]]:
        """並發抓多個幣的日線（收盤, 量）。回 {coin: (closes, volumes)}。

        230 幣循序約 100s；16 並發約 6-10s。httpx.Client 可跨執行緒共用。
        """
        now = int(time.time() * 1000)
        start = now - days * 24 * 3600 * 1000

        def fetch(coin: str):
            try:
                r = self._client.post(INFO_URL, json={
                    "type": "candleSnapshot",
                    "req": {"coin": coin, "interval": "1d",
                            "startTime": start, "endTime": now}})
                data = r.json()
                if not isinstance(data, list):
                    return coin, None
                closes = [float(c["c"]) for c in data]
                vols = [float(c["v"]) for c in data]
                return coin, (closes, vols)
            except Exception:
                return coin, None

        out: dict[str, tuple] = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
            for coin, res in ex.map(fetch, coins):
                if res:
                    out[coin] = res
        return out

    @staticmethod
    def iter_positions(state: dict) -> list[dict]:
        out = []
        for ap in state.get("assetPositions", []):
            pos = ap.get("position", {})
            if pos.get("coin"):
                out.append(pos)
        return out
