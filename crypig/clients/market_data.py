"""交易所行情 client（OHLCV）。

用 httpx 直打交易所公開 REST，回傳正規化的收盤價與成交量序列（時間由舊到新）。
預設 OKX（美國可達、USDT 永續/現貨、API 乾淨）；可擴充其他交易所。

註：未用 ccxt 是因部分沙箱環境下 ccxt 的 HTTP client 無法走 proxy；
    httpx 在本環境與正式環境皆可用。要支援多交易所正規化時可再引入 ccxt。
"""
from __future__ import annotations

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
        self._client = httpx.Client(timeout=timeout)

    def close(self) -> None:
        self._client.close()

    def fetch_ohlcv(self, symbol: str, timeframe: str = "1h",
                    limit: int = 200) -> dict[str, list[float]]:
        if self.exchange == "okx":
            return self._okx(symbol, timeframe, limit)
        raise ValueError(f"不支援的交易所：{self.exchange}")

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
