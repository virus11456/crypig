"""bitcoin-data.com 免費 BTC 鏈上指標 client。

免金鑰，但**每小時僅 10 次**請求（429 RATE_LIMIT_HOUR_EXCEEDED）。
僅比特幣有這類 UTXO 幣齡/長期持有者指標。

可用指標(slug，取 /v1/<slug>/last)範例：
  hodlers           LTH/STH 供給與淨持倉變化（欄位 lthSupplyBtc=≥155天長期持有者總量）
  illiquid-supply   長期不動(非流動)供給——長期持有者代理
  coin-age          幣齡總和(SCA)
  hodlers/hodl-waves 幣齡分 band（age3m6m、age6m1y… 為各齡段供給占比）
回傳 {"date": str, "value": float}。可用 value_key 指定欄位，
否則取非 d/unixTs 的主要數值欄位（優先含 lth 或與 slug 同名者）。
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

    def fetch_metric(self, slug: str, value_key: str | None = None) -> dict:
        resp = self._client.get(f"{BASE}/{slug}/last")
        if resp.status_code == 404:        # 部分端點不支援 /last，退回 base 路徑
            resp = self._client.get(f"{BASE}/{slug}")
        if resp.status_code == 429:
            raise RateLimited("bitcoin-data.com 每小時 10 次額度已用完")
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, list):         # 時序陣列取最後一筆
            data = data[-1]
        date = data.get("d") or data.get("day")

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
