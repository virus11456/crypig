"""Reddit 散戶討論熱度 client（官方 API、唯讀 app-only OAuth）。

取代推特當「群眾情緒」源：抓加密大版熱門貼文，算各幣討論熱度＋情緒(upvote 比)。
散戶熱炒某幣常是局部頂部/反指標，與聰明錢方向對照找 alpha。

需免費憑證（Reddit 建立 script app）：env REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET。
唯讀 grant_type=client_credentials，雲端可用、不像爬蟲被封 IP。
"""
from __future__ import annotations

import os
import re
import time

import httpx

# 幣 → 比對用名稱（標題裡出現就算一次討論）
_COIN_NAMES = {
    "BTC": ["btc", "bitcoin"], "ETH": ["eth", "ethereum", "ether"],
    "SOL": ["sol", "solana"], "XRP": ["xrp", "ripple"], "DOGE": ["doge", "dogecoin"],
    "BNB": ["bnb", "binance coin"], "ADA": ["ada", "cardano"], "AVAX": ["avax", "avalanche"],
    "LINK": ["link", "chainlink"], "MATIC": ["matic", "polygon"], "DOT": ["dot", "polkadot"],
    "SHIB": ["shib", "shiba"], "PEPE": ["pepe"], "WIF": ["wif", "dogwifhat"],
    "SUI": ["sui"], "TRX": ["trx", "tron"], "TON": ["toncoin"], "HYPE": ["hype", "hyperliquid"],
}
_SUBS = ["CryptoCurrency", "CryptoMarkets"]


class RedditClient:
    def __init__(self, timeout: float = 15.0):
        self._id = os.getenv("REDDIT_CLIENT_ID", "")
        self._secret = os.getenv("REDDIT_CLIENT_SECRET", "")
        self._ua = "crypig/0.1 (crypto sentiment)"
        self._client = httpx.Client(timeout=timeout, headers={"User-Agent": self._ua})
        self._token = ""
        self._token_ts = 0.0
        self._cache: dict | None = None
        self._cache_ts = 0.0

    @property
    def enabled(self) -> bool:
        return bool(self._id and self._secret)

    def _get_token(self) -> str:
        if self._token and time.time() - self._token_ts < 3000:
            return self._token
        r = self._client.post(
            "https://www.reddit.com/api/v1/access_token",
            data={"grant_type": "client_credentials"},
            auth=(self._id, self._secret))
        r.raise_for_status()
        self._token = r.json()["access_token"]
        self._token_ts = time.time()
        return self._token

    def crypto_buzz(self, ttl: float = 600.0) -> dict:
        """各幣 Reddit 討論熱度（提及數/互動）+ 平均 upvote 比(情緒)。無憑證回 {}。"""
        if not self.enabled:
            return {}
        if self._cache is not None and time.time() - self._cache_ts < ttl:
            return self._cache
        try:
            token = self._get_token()
        except Exception:
            return self._cache or {}
        posts = []
        for sub in _SUBS:
            try:
                r = self._client.get(
                    f"https://oauth.reddit.com/r/{sub}/hot",
                    params={"limit": 100},
                    headers={"Authorization": f"bearer {token}", "User-Agent": self._ua})
                if r.status_code == 200:
                    posts += [c["data"] for c in r.json().get("data", {}).get("children", [])]
            except Exception:
                continue
        if not posts:
            return self._cache or {}

        coins: dict[str, dict] = {}
        for p in posts:
            title = (p.get("title") or "").lower()
            score = p.get("score") or 0
            ratio = p.get("upvote_ratio")
            comments = p.get("num_comments") or 0
            for sym, names in _COIN_NAMES.items():
                if any(re.search(rf"\b{re.escape(n)}\b", title) for n in names):
                    b = coins.setdefault(sym, {"mentions": 0, "score": 0, "comments": 0, "_ratios": []})
                    b["mentions"] += 1
                    b["score"] += score
                    b["comments"] += comments
                    if ratio is not None:
                        b["_ratios"].append(ratio)
        for sym, b in coins.items():
            rs = b.pop("_ratios")
            b["sentiment"] = round(sum(rs) / len(rs) * 100, 1) if rs else None   # upvote 比→情緒%
        out = {
            "coins": coins,
            "total_posts": len(posts),
            "total_score": sum(p.get("score") or 0 for p in posts),
            "total_comments": sum(p.get("num_comments") or 0 for p in posts),
        }
        self._cache, self._cache_ts = out, time.time()
        return out

    def close(self) -> None:
        self._client.close()
