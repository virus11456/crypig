"""Reddit 散戶討論熱度 client（公開 RSS，免 OAuth／免 app 憑證）。

子版的熱門 RSS（`/r/<sub>/hot/.rss`）公開可取，**不需要 API 金鑰**；在雲端/VPS IP
上比未授權的 `.json`（常被 Reddit 回 403）更穩。對熱門貼文標題做：
  1) 各幣提及數（＝散戶討論熱度，本就是主要訊號）
  2) 利多/利空情緒傾向（共用新聞的加密語境關鍵字詞庫）

**不被限流的關鍵：每輪只抓「一個」版、輪流抓**（Reddit 對連續未授權請求會 429，
一輪一個請求就永遠不會撞）。每版各自留最近一次快照，彙整時用「所有版最近快照」，
幾輪後全部版都有資料、之後持續滾動刷新——以時間換取不被限流。

散戶熱炒某幣常是局部頂部/反指標，與聰明錢方向對照找 alpha。
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
# 加密大版（熱門 RSS 公開）。每輪只抓其中「一個」(輪轉)，永不撞 Reddit 限流。
# 版多沒關係——靠輪轉慢慢補齊、持續刷新；各版最舊約 len(_SUBS) 輪前。
_SUBS = ["CryptoCurrency", "CryptoMarkets", "Bitcoin", "ethtrader",
         "altcoin", "SatoshiStreetBets"]


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
        self._idx = 0                              # 輪轉指標：每輪抓 _SUBS[_idx]
        self._sub_titles: dict[str, list[str]] = {}  # 每版最近一次快照(標題清單)
        self._sub_ts: dict[str, float] = {}        # 每版最近一次抓取時間

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

    def crypto_buzz(self, ttl: float = 300.0) -> dict:
        """各幣 Reddit 討論熱度（提及數）＋標題利多/利空傾向。

        每輪只抓「一個」版(輪轉)＝單一請求，永不撞 Reddit 限流；彙整時用所有版的
        最近快照。幾輪後全部版都有資料、之後持續滾動刷新。抓不到回上次結果。
        """
        now = time.time()
        if self._cache is not None and now - self._cache_ts < ttl:
            return self._cache
        # 本輪只抓一個版
        sub = _SUBS[self._idx % len(_SUBS)]
        self._idx += 1
        fresh = self._fetch_sub(sub)
        if fresh:
            self._sub_titles[sub] = fresh
            self._sub_ts[sub] = now

        # 用所有版的最近快照彙整(跨版去重，避免轉貼重複計數)
        titles: list[str] = []
        seen: set[str] = set()
        for lst in self._sub_titles.values():
            for t in lst:
                k = t.strip().lower()
                if k and k not in seen:
                    seen.add(k)
                    titles.append(t)
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
            "subs": len(self._sub_titles),   # 已收集到資料的版數(輪轉中會慢慢長到 subs_total)
            "subs_total": len(_SUBS),
            "source": "reddit_rss",
        }
        self._cache, self._cache_ts = out, now
        return out

    def close(self) -> None:
        self._client.close()
