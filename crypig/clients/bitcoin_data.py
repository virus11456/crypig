"""bitcoin-data.com 免費 BTC 鏈上指標 client。

免金鑰，但**每小時僅 10 次**請求（429 RATE_LIMIT_HOUR_EXCEEDED）。
僅比特幣有這類 UTXO 幣齡/長期持有者指標。

可用指標(slug，取 /v1/<slug>/last)範例：
  hodlers           LTH/STH 淨持倉變化
  illiquid-supply   長期不動(非流動)供給——長期持有者代理
  coin-age          幣齡總和(SCA)
  hodlers/hodl-waves 幣齡分 band
回傳 {"date": str, "value": float}（取非 d/unixTs 的主要數值欄位）。
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

    def fetch_metric(self, slug: str) -> dict:
        resp = self._client.get(f"{BASE}/{slug}/last")
        if resp.status_code == 429:
            raise RateLimited("bitcoin-data.com 每小時 10 次額度已用完")
        resp.raise_for_status()
        data = resp.json()
        date = data.get("d")
        # 取主要數值欄位（排除日期/時間戳）
        prefer = slug.split("/")[-1].replace("-", "").lower()
        value = None
        for k, v in data.items():
            if k in ("d", "unixTs"):
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
