"""bitcoin-data.com 免費 BTC 鏈上指標 client。

免金鑰，但**每小時僅 10 次**請求（429 RATE_LIMIT_HOUR_EXCEEDED）。
僅比特幣有這類 UTXO 幣齡/長期持有者指標。

可用指標(slug，取 /v1/<slug>/last)範例：
  long-term-hodler-supply-btc  真正長期持有者(≥155天)供給(BTC)，欄位 longTermHodlerSupplyBtc
  illiquid-supply              長期不動(非流動)供給——長期持有者代理
  wallet-bands                 鯨魚分級錢包持倉(一次回全部)：
                               whaleBtc(10-100)、humpbackBtc(100-1K)、megaWhaleBtc(≥1K)及各 count
  coins-addr-1K-100-BTC …      單一餘額級距持倉(BTC)
fetch_metric 回傳 {"date", "value"}（可用 value_key 指定欄位）。
fetch_raw 回傳整包 dict（多欄位端點如 wallet-bands 用）。
"""
from __future__ import annotations

import httpx

BASE = "https://bitcoin-data.com/v1"


class RateLimited(RuntimeError):
    pass


class BitcoinDataClient:
    def __init__(self, timeout: float = 15.0):
        self._client = httpx.Client(
            timeout=timeout,
            headers={"User-Agent": "crypig/0.1"},
            follow_redirects=True,
        )

    def close(self) -> None:
        self._client.close()

    def fetch_history(self, slug: str, ttl: float = 21600.0) -> list[dict]:
        """取整段歷史（不加 /last，回時序陣列）。日資料，預設快取 6 小時省額度。"""
        import time
        cache = getattr(self, "_hist_cache", {})
        hit = cache.get(slug)
        if hit and time.time() - hit[0] < ttl:
            return hit[1]
        resp = self._client.get(f"{BASE}/{slug}")
        if resp.status_code == 429:
            raise RateLimited("bitcoin-data.com 每小時 10 次額度已用完")
        resp.raise_for_status()
        data = resp.json()
        rows = data if isinstance(data, list) else []
        cache[slug] = (time.time(), rows)
        self._hist_cache = cache
        return rows

    def fetch_raw(self, slug: str) -> dict:
        """取整包欄位（多欄位端點，如 wallet-bands 鯨魚分級）。"""
        resp = self._client.get(f"{BASE}/{slug}/last")
        if resp.status_code == 404:
            resp = self._client.get(f"{BASE}/{slug}")
        if resp.status_code == 429:
            raise RateLimited("bitcoin-data.com 每小時 10 次額度已用完")
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, list):
            data = data[-1]
        return data

    def fetch_metric(self, slug: str, value_key: str | None = None) -> dict:
        data = self.fetch_raw(slug)
        date = data.get("d") or data.get("day") or data.get("theDate")

        if value_key is not None:        # 明確指定欄位
            if value_key not in data:
                raise ValueError(f"bitcoin-data {slug} 無欄位 {value_key}：{list(data)}")
            return {"date": date, "value": float(data[value_key])}

        # 否則取主要數值欄位（排除日期/時間戳）
        prefer = slug.split("/")[-1].replace("-", "").lower()
        value = None
        for k, v in data.items():
            if k in ("d", "unixTs", "day"):
                continue
            try:
                fv = float(v)
            except (TypeError, ValueError):
                continue
            if value is None:
                value = fv
            kl = k.lower()
            if "lth" in kl or prefer in kl:   # 偏好與指標同名/含 lth 的欄位
                value = fv
                break
        if value is None:
            raise ValueError(f"bitcoin-data {slug} 回傳無數值欄位：{data}")
        return {"date": date, "value": value}
