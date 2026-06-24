"""交易所行情 client（OHLCV）。

用 httpx 直打交易所公開 REST，回傳正規化的收盤價與成交量序列（時間由舊到新）。
預設 OKX（美國可達、USDT 永續/現貨、API 乾淨）；可擴充其他交易所。

註：未用 ccxt 是因部分沙箱環境下 ccxt 的 HTTP client 無法走 proxy；
    httpx 在本環境與正式環境皆可用。要支援多交易所正規化時可再引入 ccxt。
"""
from __future__ import annotations

import statistics
import time
from collections import defaultdict

import httpx

# 通用 timeframe -> 各交易所 bar 代碼
_OKX_BAR = {
    "1m": "1m", "3m": "3m", "5m": "5m", "15m": "15m", "30m": "30m",
    "1h": "1H", "2h": "2H", "4h": "4H", "6h": "6H", "12h": "12H",
    "1d": "1D", "1w": "1W",
}


class MarketDataClient:
    def __init__(self, exchange: str = "okx", timeout: float = 15.0):
        self.exchange = exchange
        self._client = httpx.Client(
            timeout=timeout, headers={"User-Agent": "crypig/0.1"})
        self._deriv_cache: dict | None = None
        self._deriv_ts: float = 0.0
        self._macro_cache: dict | None = None
        self._macro_ts: float = 0.0

    def aggregate_derivatives(self, ttl: float = 60.0) -> dict[str, dict]:
        """全市場合約持倉量：聚合 CoinGecko 各交易所衍生品（免金鑰）。

        回傳 {base: {open_interest_usd, funding_rate_med, contracts}}。
        funding_rate_med 取各所中位數（避免小交易所離群值拉歪），
        單位百分比/8h（CoinGecko 原始單位）。
        """
        if self._deriv_cache is not None and time.time() - self._deriv_ts < ttl:
            return self._deriv_cache
        resp = self._client.get("https://api.coingecko.com/api/v3/derivatives")
        resp.raise_for_status()
        agg: dict[str, dict] = defaultdict(
            lambda: {"open_interest_usd": 0.0, "_fr": [], "contracts": 0})
        for x in resp.json():
            base = (x.get("index_id") or "").upper()
            oi = x.get("open_interest")
            if not base or not oi:
                continue
            a = agg[base]
            a["open_interest_usd"] += float(oi)
            a["contracts"] += 1
            fr = x.get("funding_rate")
            if fr is not None:
                a["_fr"].append(float(fr))
        out: dict[str, dict] = {}
        for base, a in agg.items():
            frs = a.pop("_fr")
            a["funding_rate_med"] = statistics.median(frs) if frs else 0.0
            out[base] = a
        self._deriv_cache = out
        self._deriv_ts = time.time()
        return out

    # symbol -> CoinGecko coin id（取各幣市值/成交量用）
    _CG_ID = {"BTC": "bitcoin", "ETH": "ethereum", "SOL": "solana",
              "BNB": "binancecoin", "XRP": "ripple", "DOGE": "dogecoin"}

    def global_macro(self, ttl: float = 120.0) -> dict:
        """全市場宏觀：總市值、24h 量、全市場 OI，及 OI/Cap、Vol/Cap。"""
        if self._macro_cache is not None and time.time() - self._macro_ts < ttl:
            return self._macro_cache
        g = self._client.get("https://api.coingecko.com/api/v3/global").json()["data"]
        cap = float(g["total_market_cap"]["usd"])
        vol = float(g["total_volume"]["usd"])
        deriv = self._client.get("https://api.coingecko.com/api/v3/derivatives").json()
        oi = sum(float(x["open_interest"]) for x in deriv if x.get("open_interest"))
        out = {
            "market_cap": cap, "volume_24h": vol, "open_interest": oi,
            "oi_cap": oi / cap if cap else 0.0,
            "vol_cap": vol / cap if cap else 0.0,
            "btc_dominance": float(g.get("market_cap_percentage", {}).get("btc", 0.0)),
        }
        self._macro_cache, self._macro_ts = out, time.time()
        return out

    def coin_macro(self, symbols: list[str], ttl: float = 120.0) -> dict[str, dict]:
        """各幣 OI/Cap、Vol/Cap：市值/量取自 CoinGecko，OI 取自聚合衍生品。"""
        ids = ",".join(self._CG_ID[s] for s in symbols if s in self._CG_ID)
        markets = self._client.get(
            "https://api.coingecko.com/api/v3/coins/markets",
            params={"vs_currency": "usd", "ids": ids}).json()
        by_id = {m["id"]: m for m in markets}
        deriv = self.aggregate_derivatives()
        out: dict[str, dict] = {}
        for s in symbols:
            cid = self._CG_ID.get(s)
            m = by_id.get(cid) if cid else None
            if not m:
                continue
            cap = float(m.get("market_cap") or 0.0)
            vol = float(m.get("total_volume") or 0.0)
            oi = float(deriv.get(s, {}).get("open_interest_usd", 0.0))
            out[s] = {
                "market_cap": cap, "volume_24h": vol, "open_interest": oi,
                "oi_cap": oi / cap if cap else 0.0,
                "vol_cap": vol / cap if cap else 0.0,
            }
        return out

    def close(self) -> None:
        self._client.close()

    def fetch_ohlcv(self, symbol: str, timeframe: str = "1h",
                    limit: int = 200) -> dict[str, list[float]]:
        if self.exchange == "okx":
            return self._okx(symbol, timeframe, limit)
        raise ValueError(f"不支援的交易所：{self.exchange}")

    def fetch_candles(self, symbol: str, timeframe: str = "1h",
                      limit: int = 300) -> list[tuple[int, float]]:
        """帶時間戳的 K 線（回測對齊用）：回 [(epoch_ms, close), ...] 由舊到新。"""
        if self.exchange != "okx":
            raise ValueError(f"不支援的交易所：{self.exchange}")
        bar = _OKX_BAR.get(timeframe)
        if not bar:
            raise ValueError(f"OKX 不支援的 timeframe：{timeframe}")
        resp = self._client.get(
            "https://www.okx.com/api/v5/market/candles",
            params={"instId": f"{symbol}-USDT", "bar": bar, "limit": str(limit)},
        )
        resp.raise_for_status()
        payload = resp.json()
        if payload.get("code") != "0":
            raise RuntimeError(f"OKX 錯誤：{payload.get('msg')} (instId={symbol}-USDT)")
        rows = list(reversed(payload.get("data", [])))   # OKX 由新到舊→反轉
        return [(int(r[0]), float(r[4])) for r in rows]

    def _okx(self, symbol: str, timeframe: str, limit: int) -> dict[str, list[float]]:
        bar = _OKX_BAR.get(timeframe)
        if not bar:
            raise ValueError(f"OKX 不支援的 timeframe：{timeframe}")
        inst = f"{symbol}-USDT"
        resp = self._client.get(
            "https://www.okx.com/api/v5/market/candles",
            params={"instId": inst, "bar": bar, "limit": str(limit)},
        )
        resp.raise_for_status()
        payload = resp.json()
        if payload.get("code") != "0":
            raise RuntimeError(f"OKX 錯誤：{payload.get('msg')} (instId={inst})")
        # OKX 回傳由新到舊：[ts, o, h, l, c, vol, ...]
        rows = list(reversed(payload.get("data", [])))
        closes = [float(r[4]) for r in rows]
        volumes = [float(r[5]) for r in rows]
        return {"closes": closes, "volumes": volumes}
