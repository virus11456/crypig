"""DefiLlama 資金動向 client（免費、無金鑰）。

提供：DeFi 總 TVL（risk-on/off）、穩定幣總市值（場邊資金/乾火藥）、各鏈 TVL（資金輪動）。
全部一次抓並快取；失敗沿用上次快取。
"""
from __future__ import annotations

import time

import httpx


class DefiLlamaClient:
    def __init__(self, timeout: float = 25.0):
        self._client = httpx.Client(
            timeout=timeout, headers={"User-Agent": "crypig/0.1"}, follow_redirects=True)
        self._cache: dict | None = None
        self._ts: float = 0.0

    def snapshot(self, ttl: float = 600.0) -> dict:
        if self._cache is not None and time.time() - self._ts < ttl:
            return self._cache
        out: dict = {}
        try:
            tvl = self._client.get("https://api.llama.fi/v2/historicalChainTvl").json()
            if isinstance(tvl, list) and len(tvl) > 31:
                cur = tvl[-1]["tvl"]
                out["tvl"] = {
                    "value": cur,
                    "chg_7d": (cur - tvl[-8]["tvl"]) / tvl[-8]["tvl"],
                    "chg_30d": (cur - tvl[-31]["tvl"]) / tvl[-31]["tvl"],
                    "history": [{"v": x["tvl"], "t": x.get("date")} for x in tvl[-60:]],
                }
        except Exception:
            pass
        try:
            chains = self._client.get("https://api.llama.fi/v2/chains").json()
            if isinstance(chains, list):
                top = sorted(chains, key=lambda x: -(x.get("tvl") or 0))[:6]
                out["chains"] = [{"name": x.get("name"), "tvl": x.get("tvl")} for x in top]
        except Exception:
            pass
        try:
            sc = self._client.get("https://stablecoins.llama.fi/stablecoincharts/all").json()
            if isinstance(sc, list) and len(sc) > 31:
                def mc(x):
                    v = x.get("totalCirculatingUSD")
                    return sum(v.values()) if isinstance(v, dict) else (v or 0)
                cur = mc(sc[-1])
                out["stablecoin"] = {
                    "value": cur,
                    "chg_30d": (cur - mc(sc[-31])) / mc(sc[-31]) if mc(sc[-31]) else 0,
                    "history": [{"v": mc(x)} for x in sc[-60:]],
                }
        except Exception:
            pass
        if out:
            self._cache, self._ts = out, time.time()
            return out
        return self._cache or {}

    def close(self) -> None:
        self._client.close()
