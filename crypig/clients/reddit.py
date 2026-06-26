"""Reddit 散戶討論熱度 client（公開 RSS，免 OAuth／免 app 憑證）。

子版的熱門 RSS（`/r/<sub>/hot/.rss`）公開可取，**不需要 API 金鑰**；在雲端/VPS IP
上比未授權的 `.json`（常被 Reddit 回 403）更穩。對熱門貼文標題做：
  1) 各幣提及數（＝散戶討論熱度，本就是主要訊號）
  2) 利多/利空情緒傾向（共用新聞的加密語境關鍵字詞庫）

散戶熱炒某幣常是局部頂部/反指標，與聰明錢方向對照找 alpha。
RSS 自帶 TTL 快取即可（非 OAuth、無權杖）。
"""
from __future__ import annotations

import re
import time
from xml.etree import ElementTree as ET

import httpx

from .news import _BULL, _BEAR  # 共用加密語境利多/利空詞庫

# 幣 → 標題比對用名稱（標題出現即算一次討論）
_COIN_NAMES = {
    "BTC": ["btc", "bitcoin"], "ETH": ["eth", "ethereum", "ether"],
    "SOL": ["sol", "solana"], "XRP": ["xrp", "ripple"], "DOGE": ["doge", "dogecoin"],
    "BNB": ["bnb", "binance coin"], "ADA": ["ada", "cardano"], "AVAX": ["avax", "avalanche"],
    "LINK": ["link", "chainlink"], "MATIC": ["matic", "polygon"], "DOT": ["dot", "polkadot"],
    "SHIB": ["shib", "shiba"], "PEPE": ["pepe"], "WIF": ["wif", "dogwifhat"],
    "SUI": ["sui"], "TRX": ["trx", "tron"], "TON": ["toncoin"], "HYPE": ["hype", "hyperliquid"],
    "LTC": ["ltc", "litecoin"], "NEAR": ["near"], "APT": ["apt", "aptos"],
    "ARB": ["arb", "arbitrum"], "OP": ["optimism"], "INJ": ["injective"],
}
# 加密大版（熱門 RSS 公開）。多版彙整提高樣本量；Reddit 對連續未授權請求會 429，
# 故每版間隔抓、單次退避重試，抓不到的版略過（至少 CryptoCurrency 通常可得 50 篇）。
_SUBS = ["CryptoCurrency", "CryptoMarkets", "Bitcoin", "ethtrader"]


def _local(tag: str) -> str:
    """去掉 XML 命名空間（Reddit RSS 是 Atom：{http://www.w3.org/2005/Atom}entry）。"""
    return tag.rsplit("}", 1)[-1]


class RedditClient:
    def __init__(self, timeout: float = 15.0):
        # 帶具識別性的 User-Agent；Reddit 對預設/空 UA 較易擋
        self._client = httpx.Client(
            timeout=timeout, follow_redirects=True,
            headers={"User-Agent": "crypig/0.2 (crypto retail sentiment; +https://hypeboss.cc)"})
        self._cache: dict | None = None
        self._cache_ts = 0.0

    @property
    def enabled(self) -> bool:
        return True   # 公開 RSS 不需憑證，恆可用

    def _fetch_sub(self, sub: str) -> list[str]:
        """回某子版熱門貼文標題清單。429 時退避重試一次。"""
        url = f"https://www.reddit.com/r/{sub}/hot/.rss?limit=50"
        content = None
        for attempt in range(2):
            try:
                r = self._client.get(url)
                if r.status_code == 200:
                    content = r.content
                    break
                if r.status_code == 429 and attempt == 0:
                    time.sleep(5.0)   # Reddit 限流，退避後再試一次
                    continue
                return []
            except Exception:
                return []
        if content is None:
            return []
        try:
            root = ET.fromstring(content)
        except Exception:
            return []
        titles: list[str] = []
        for e in root.iter():
            if _local(e.tag) != "entry":
                continue
            for ch in e:
                if _local(ch.tag) == "title":
                    t = (ch.text or "").strip()
                    if t:
                        titles.append(t)
                    break
        return titles

    def crypto_buzz(self, ttl: float = 600.0) -> dict:
        """各幣 Reddit 討論熱度（提及數）＋標題利多/利空傾向。抓不到回快取/空。"""
        if self._cache is not None and time.time() - self._cache_ts < ttl:
            return self._cache
        titles: list[str] = []
        for i, sub in enumerate(_SUBS):
            if i:
                time.sleep(3.0)   # 拉開間隔，降低被 Reddit 限流(429)機率
            titles += self._fetch_sub(sub)
        if not titles:
            return self._cache or {}

        coins: dict[str, dict] = {}
        for title in titles:
            t = title.lower()
            bull = sum(1 for w in _BULL if w in t)
            bear = sum(1 for w in _BEAR if w in t)
            for sym, names in _COIN_NAMES.items():
                if any(re.search(rf"\b{re.escape(n)}\b", t) for n in names):
                    b = coins.setdefault(sym, {"mentions": 0, "bull": 0, "bear": 0, "net": 0})
                    b["mentions"] += 1
                    b["bull"] += bull
                    b["bear"] += bear
                    b["net"] += bull - bear
        for b in coins.values():
            tot = b["bull"] + b["bear"]
            # 情緒%＝標題偏多比例(0~100)；標題無情緒詞時為 None（顯示「—」）
            b["sentiment"] = round(b["bull"] / tot * 100, 1) if tot else None
        out = {
            "coins": coins,
            "total_posts": len(titles),
            "subs": len(_SUBS),
            "source": "reddit_rss",
        }
        self._cache, self._cache_ts = out, time.time()
        return out

    def close(self) -> None:
        self._client.close()
