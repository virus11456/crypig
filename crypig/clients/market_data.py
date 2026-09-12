"""交易所行情 client（OHLCV）。

用 httpx 直打交易所公開 REST，回傳正規化的收盤價與成交量序列（時間由舊到新）。
預設 OKX（美國可達、USDT 永續/現貨、API 乾淨）；可擴充其他交易所。

註：未用 ccxt 是因部分沙箱環境下 ccxt 的 HTTP client 無法走 proxy；
    httpx 在本環境與正式環境皆可用。要支援多交易所正規化時可再引入 ccxt。
"""
from __future__ import annotations

import math
import os
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
        # CoinGecko 免費 Demo 金鑰（env COINGECKO_API_KEY）：100 次/分、10k 次/月，
        # 且不會像無金鑰版那樣封鎖雲端 IP。沒設則用無金鑰(本地可、雲端易被擋)。
        headers = {"User-Agent": "crypig/0.1"}
        key = os.getenv("COINGECKO_API_KEY")
        if key:
            headers["x-cg-demo-api-key"] = key
        self._client = httpx.Client(timeout=timeout, headers=headers)
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
        原始費率不假設結算週期，不可直接跨所統一年化。
        """
        if self._deriv_cache is not None and time.time() - self._deriv_ts < ttl:
            return self._deriv_cache
        resp = self._client.get("https://api.coingecko.com/api/v3/derivatives")
        resp.raise_for_status()
        data = resp.json()
        out = self.normalize_derivatives(data)
        self._deriv_cache = out
        self._deriv_ts = time.time()
        return out

    @staticmethod
    def normalize_derivatives(data, now=None):
        """USD OI of deduplicated perpetuals traded within 24 hours; not all-market coverage."""
        now = time.time() if now is None else now
        if not isinstance(data, list) or not data:
            raise ValueError("Empty derivatives response")
        def number(value):
            try:
                value = float(value) if not isinstance(value, bool) else float('nan')
                return value if math.isfinite(value) else None
            except (TypeError, ValueError):
                return None
        selected = {}
        for row in data:
            if not isinstance(row, dict) or row.get("contract_type") != "perpetual":
                continue
            base, market, symbol = row.get("index_id"), row.get("market"), row.get("symbol")
            if not all(isinstance(v, str) and v for v in (base, market, symbol)):
                continue
            oi, traded, price = (number(row.get(k)) for k in ("open_interest", "last_traded_at", "price"))
            expiry = row.get("expired_at")
            if expiry is not None and (number(expiry) is None or number(expiry) <= now):
                continue
            if oi is None or oi < 0 or traded is None or not now-86400 <= traded <= now+300 or price is None or price <= 0:
                continue
            key = (market, symbol)
            if key not in selected or traded > selected[key][1]:
                selected[key] = (row, traded, oi, price)
        groups = defaultdict(list)
        for row, traded, oi, price in selected.values():
            groups[row["index_id"].upper()].append((row, traded, oi, price))
        out = {}
        for base, rows in groups.items():
            rates = [number(r[0].get("funding_rate")) for r in rows]
            rates = [r for r in rates if r is not None]
            out[base] = {"open_interest_usd": sum(r[2] for r in rows),
                         "contracts": len(rows), "exchanges": len({r[0]["market"] for r in rows}),
                         "reference_price": statistics.median(r[3] for r in rows),
                         "oldest_trade_at": min(r[1] for r in rows),
                         "latest_trade_at": max(r[1] for r in rows),
                         "coverage": "perpetuals_traded_within_24h", "unit": "USD",
                         "funding_rate_med": statistics.median(rates) if rates else 0.0}
        if not out:
            raise ValueError("No valid derivatives")
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
            "oi_cap": None,  # derivative coverage can include non-crypto underlyings
            "oi_coverage": "CoinGecko 有效永續合約樣本，可能包含非加密標的；不計算全市場 OI/Cap。",
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

    @classmethod
    def normalize_markets(cls, raw: list) -> dict[str, dict]:
        if not isinstance(raw, list) or not raw:
            raise ValueError("Empty market response")
        groups = defaultdict(list)
        for row in raw:
            if not isinstance(row, dict):
                raise ValueError("Invalid market row")
            symbol = row.get("symbol")
            if isinstance(symbol, str) and symbol and isinstance(row.get("id"), str):
                groups[symbol.upper()].append(row)
        out = {}
        for symbol, rows in groups.items():
            expected = cls._CG_ID.get(symbol)
            candidates = [r for r in rows if r["id"] == expected] if expected else rows
            if len(candidates) != 1:
                continue  # ambiguous or known ID missing: never pick the biggest namesake
            row = candidates[0]
            cap, volume = row.get("market_cap"), row.get("total_volume")
            def valid(value):
                return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value) and value >= 0
            if not valid(cap) or cap == 0:
                continue
            out[symbol] = {"market_cap": cap, "volume_24h": volume if valid(volume) else None,
                           "asset_id": row["id"],
                           "reference_price": row.get("current_price"),
                           "match_method": "asset_id" if expected else "symbol_candidate",
                           "source_updated_at": row.get("last_updated")}
        return out

    def top_markets(self, per_page: int = 250, ttl: float = 600.0) -> dict[str, dict]:
        """One page per refresh; reject ambiguous symbols and preserve valid cache on errors."""
        if self._top_cache is not None and time.time() - self._top_ts < ttl:
            return self._top_cache
        try:
            response = self._client.get(
                "https://api.coingecko.com/api/v3/coins/markets",
                params={"vs_currency": "usd", "order": "market_cap_desc",
                        "per_page": str(per_page), "page": "1"})
            response.raise_for_status()
            out = self.normalize_markets(response.json())
            if out:
                self._top_cache, self._top_ts = out, time.time()
        except Exception:
            pass
        return self._top_cache or {}

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
            fund_ann = None  # settlement intervals are not provided by this endpoint
            out[s] = {
                "market_cap": cap, "volume_24h": vol, "open_interest": oi,
                "oi_cap": (oi / cap) if (oi and cap) else None,
                "vol_cap": (vol / cap) if cap else None,
                "funding_ann": fund_ann,
                "funding_flag": None,
                "funding_note": "結算週期未知，不進行年化換算",
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

    def fetch_candles_history(self, symbol: str, timeframe: str = "1d",
                              max_bars: int = 1100) -> list[tuple[int, float]]:
        """分頁抓較長歷史 K 線（OKX history-candles，可回溯數年）。

        回 [(epoch_ms, close)] 由舊到新。OKX 單頁上限 100，用 `after` 游標往更早翻，
        直到湊滿 max_bars 或沒有更早資料。失敗時回目前已抓到的部分。
        """
        bar = _OKX_BAR.get(timeframe)
        if not bar:
            raise ValueError(f"OKX 不支援的 timeframe：{timeframe}")
        inst = f"{symbol}-USDT"
        closes: dict[int, float] = {}
        after: int | None = None
        for _ in range(max_bars // 100 + 2):     # 上限頁數，防無限迴圈
            if len(closes) >= max_bars:
                break
            params = {"instId": inst, "bar": bar, "limit": "100"}
            if after is not None:
                params["after"] = str(after)
            try:
                resp = self._client.get(
                    "https://www.okx.com/api/v5/market/history-candles", params=params)
                resp.raise_for_status()
                data = resp.json().get("data", [])
            except Exception:
                break
            if not data:
                break
            for r in data:                       # OKX 回傳新→舊
                closes[int(r[0])] = float(r[4])
            after = int(data[-1][0])             # 本頁最舊 ts → 下頁抓更早
            if len(data) < 100:                  # 沒有更早資料了
                break
        items = sorted(closes.items())
        return items[-max_bars:]

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
