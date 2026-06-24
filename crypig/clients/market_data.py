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

_FUNDING_PER_YEAR = 3 * 365   # CoinGecko funding 為 %/8h → 一年 3*365 期

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
        self._coin_cache: dict | None = None
        self._coin_key: str = ""
        self._coin_ts: float = 0.0
        self._top_cache: dict | None = None
        self._top_ts: float = 0.0

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
        data = resp.json()
        if not isinstance(data, list):       # 限流/錯誤時回的是 dict，視為無資料
            return self._deriv_cache or {}
        agg: dict[str, dict] = defaultdict(
            lambda: {"open_interest_usd": 0.0, "_fr": [], "contracts": 0})
        for x in data:
            if not isinstance(x, dict):
                continue
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
        """全市場宏觀：總市值、24h 量、全市場 OI，及 OI/Cap、Vol/Cap。

        CoinGecko 對雲端 IP 可能限流→回非預期格式，故全程防護；OI 取不到時
        以 None 表示（前端忠實顯示「—」），市值/量仍盡量回傳。
        """
        if self._macro_cache is not None and time.time() - self._macro_ts < ttl:
            return self._macro_cache
        raw = self._client.get("https://api.coingecko.com/api/v3/global").json()
        g = raw.get("data") if isinstance(raw, dict) else None
        if not isinstance(g, dict) or "total_market_cap" not in g:
            raise RuntimeError("CoinGecko /global 回傳異常（可能限流）")
        cap = float(g["total_market_cap"]["usd"])
        vol = float(g["total_volume"]["usd"])
        oi = None
        try:                                 # 用聚合衍生品(共用快取)算總 OI，省一次重複呼叫
            deriv = self.aggregate_derivatives()
            tot = sum(float(v.get("open_interest_usd") or 0.0) for v in deriv.values())
            oi = tot or None
        except Exception:
            oi = None
        out = {
            "market_cap": cap, "volume_24h": vol, "open_interest": oi,
            "oi_cap": (oi / cap) if (oi and cap) else None,
            "vol_cap": (vol / cap) if cap else None,
            "btc_dominance": float(g.get("market_cap_percentage", {}).get("btc", 0.0)),
        }
        self._macro_cache, self._macro_ts = out, time.time()
        return out

    @staticmethod
    def _funding_flag(ann: float) -> str:
        """資金費率(年化小數)異常分級：
          hot     多單過度擁擠（年化 > 50%）→ 過熱、回調風險
          warm    多單偏擁擠（年化 > 25%）
          squeeze 空單擁擠/負費率（年化 < -5%）→ 潛在軋空
          normal  正常
        """
        if ann > 0.50:
            return "hot"
        if ann > 0.25:
            return "warm"
        if ann < -0.05:
            return "squeeze"
        return "normal"

    def top_markets(self, per_page: int = 250, ttl: float = 600.0) -> dict[str, dict]:
        """CoinGecko 前 N 大市值幣的 {SYMBOL: {market_cap, volume_24h}}（一次抓、快取）。

        用來補全市場列表中各幣的市值與量（同名取市值最大者）。CoinGecko 對雲端
        IP 會限流，故：失敗時沿用上次好的快取（不回空），TTL 拉長到 10 分鐘。
        """
        if self._top_cache is not None and time.time() - self._top_ts < ttl:
            return self._top_cache
        try:
            raw = self._client.get(
                "https://api.coingecko.com/api/v3/coins/markets",
                params={"vs_currency": "usd", "order": "market_cap_desc",
                        "per_page": str(per_page), "page": "1"}).json()
        except Exception:
            return self._top_cache or {}
        out: dict[str, dict] = {}
        if isinstance(raw, list):
            for m in raw:
                if not isinstance(m, dict):
                    continue
                sym = (m.get("symbol") or "").upper()
                if sym and sym not in out:        # 同名取第一個(市值最大)
                    out[sym] = {"market_cap": float(m.get("market_cap") or 0.0),
                                "volume_24h": float(m.get("total_volume") or 0.0)}
        if out:
            self._top_cache, self._top_ts = out, time.time()
            return out
        return self._top_cache or {}              # 限流回非 list → 用上次快取

    def coin_macro(self, symbols: list[str], ttl: float = 120.0) -> dict[str, dict]:
        """各幣 OI/Cap、Vol/Cap、資金費率(年化)與異常分級。快取以減少 CoinGecko 呼叫。"""
        key = ",".join(symbols)
        if (self._coin_cache is not None and self._coin_key == key
                and time.time() - self._coin_ts < ttl):
            return self._coin_cache
        ids = ",".join(self._CG_ID[s] for s in symbols if s in self._CG_ID)
        raw = self._client.get(
            "https://api.coingecko.com/api/v3/coins/markets",
            params={"vs_currency": "usd", "ids": ids}).json()
        markets = raw if isinstance(raw, list) else []
        by_id = {m["id"]: m for m in markets if isinstance(m, dict)}
        deriv = self.aggregate_derivatives()
        out: dict[str, dict] = {}
        for s in symbols:
            cid = self._CG_ID.get(s)
            m = by_id.get(cid) if cid else None
            if not m:
                continue
            cap = float(m.get("market_cap") or 0.0)
            vol = float(m.get("total_volume") or 0.0)
            d = deriv.get(s, {})
            oi = float(d.get("open_interest_usd") or 0.0)
            # CoinGecko funding 為 %/8h → 年化小數
            fund_ann = float(d.get("funding_rate_med") or 0.0) / 100 * _FUNDING_PER_YEAR
            out[s] = {
                "market_cap": cap, "volume_24h": vol, "open_interest": oi,
                "oi_cap": (oi / cap) if (oi and cap) else None,
                "vol_cap": (vol / cap) if cap else None,
                "funding_ann": fund_ann,
                "funding_flag": self._funding_flag(fund_ann),
            }
        if out:                              # 只快取成功結果（空的就讓下次重試）
            self._coin_cache, self._coin_key, self._coin_ts = out, key, time.time()
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
