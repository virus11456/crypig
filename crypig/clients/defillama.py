"""DefiLlama 資金動向 client（免費、無金鑰）。

提供：DeFi 總 TVL（risk-on/off）、穩定幣總市值（場邊資金/乾火藥）、各鏈 TVL（資金輪動）。
全部一次抓並快取；失敗沿用上次快取。
"""
from __future__ import annotations

import time
import copy
import math

import httpx


class DefiLlamaClient:
    def __init__(self, timeout: float = 25.0):
        self._client = httpx.Client(
            timeout=timeout, headers={"User-Agent": "crypig/0.1"}, follow_redirects=True)
        self._cache: dict | None = None
        self._ts: float = 0.0

    @staticmethod
    def daily_summary(rows, value):
        if not isinstance(rows, list):
            raise ValueError("Invalid daily history")
        points = {}
        for row in rows:
            try:
                ts = int(row["date"])
                raw = value(row)
                if isinstance(raw, bool):
                    continue
                amount = float(raw)
                if not 0 < ts <= time.time()+60 or not math.isfinite(amount) or amount <= 0:
                    continue
            except (KeyError, TypeError, ValueError):
                continue
            if ts in points and points[ts] != amount:
                raise ValueError("Conflicting daily observations")
            points[ts] = amount
        if not points:
            raise ValueError("No valid daily observations")
        # Keep the last observation for each UTC calendar day.
        days = {}
        for ts in sorted(points):
            days[ts//86400] = {"t": ts, "v": points[ts]}
        latest = days[max(days)]
        out = {"value": latest["v"], "observed_at": latest["t"],
               "history": list(days.values())[-60:]}
        for length in (7, 30):
            reference = days.get(max(days)-length)
            out[f"chg_{length}d"] = latest["v"]/reference["v"]-1 if reference else None
        return out

    @staticmethod
    def circulating(row):
        values = row["totalCirculatingUSD"]
        if isinstance(values, dict):
            numbers = list(values.values())
            if not numbers or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v < 0 for v in numbers):
                raise ValueError("Invalid circulating value")
            return sum(numbers)
        return values

    @staticmethod
    def top_chains(rows):
        if not isinstance(rows, list):
            raise ValueError("Invalid chain response")
        out = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            name, value = row.get("name"), row.get("tvl")
            if isinstance(name, str) and name and not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value) and value >= 0:
                out.append({"name": name, "tvl": value})
        if not out:
            raise ValueError("No valid chains")
        return sorted(out, key=lambda row: -row["tvl"])[:6]

    def snapshot(self, ttl: float = 600.0, previous=None) -> dict:
        if self._cache is not None and time.time() - self._ts < ttl:
            return self._cache
        out = copy.deepcopy(self._cache if self._cache is not None else previous or {})
        sources = out.setdefault("sources", {})
        jobs = [
            ("tvl", "https://api.llama.fi/v2/historicalChainTvl", lambda rows: self.daily_summary(rows, lambda row: row["tvl"])),
            ("chains", "https://api.llama.fi/v2/chains", self.top_chains),
            ("stablecoin", "https://stablecoins.llama.fi/stablecoincharts/all", lambda rows: self.daily_summary(rows, self.circulating)),
        ]
        for key, url, normalize in jobs:
            prior = sources.get(key, {})
            attempted = time.time()
            try:
                response = self._client.get(url)
                response.raise_for_status()
                data = normalize(response.json())
                observed = data.get("observed_at") if isinstance(data, dict) else None
                if observed and prior.get("observed_at") and observed < prior["observed_at"]:
                    raise ValueError("Source moved backwards")
                out[key] = data
                sources[key] = {"fetched_at": time.time(), "observed_at": observed,
                                "attempted_at": attempted, "refresh_failed": False}
            except Exception:
                # A failed component keeps its own last good data and original time.
                sources[key] = {**prior, "attempted_at": attempted, "refresh_failed": True}
        self._cache, self._ts = out, time.time()
        return out

    def stablecoin_history(self, ttl: float = 21600.0) -> list[dict]:
        """穩定幣總供應完整日頻歷史（2017 至今），供區間可選走勢圖。回 [{t,v}] 由舊到新。

        日資料，預設快取 6 小時省流量。失敗回上次快取。
        """
        now = time.time()
        hit = getattr(self, "_sc_hist", None)
        if hit and now - hit[0] < ttl:
            return hit[1]
        response = self._client.get("https://stablecoins.llama.fi/stablecoincharts/all")
        response.raise_for_status()
        sc = response.json()
        if not isinstance(sc, list):
            raise ValueError("Invalid stablecoin history")
        import math
        points = {}
        for x in sc:
            try:
                t = int(x["date"])
                values = x["totalCirculatingUSD"]
                v = sum(float(a) for a in values.values()) if isinstance(values, dict) else float(values)
                if t > 0 and math.isfinite(v) and v > 0:
                    points[t] = v
            except (KeyError, TypeError, ValueError):
                continue
        out = [{"t": t, "v": points[t]} for t in sorted(points)]
        if not out:
            raise ValueError("Empty stablecoin history")
        self._sc_hist = (now, out)
        return out

    def close(self) -> None:
        self._client.close()
