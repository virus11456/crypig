"""加密新聞分析 client（免費 RSS、無金鑰）。

抓多家加密媒體 RSS，對每則標題做：
  1) 利多/利空情緒分級（關鍵字詞庫，加密語境）
  2) 影響幣標記（標題/摘要比對幣名）
再彙整成「整體新聞偏多/偏空、最受關注幣的新聞淨情緒」——呈現結論而非生標題牆，
並可與聰明錢持倉對照（新聞很多看多但聰明錢做空＝潛在頂部反指標）。

RSS 非 IP 限流，client 自帶 TTL 快取即可。
"""
from __future__ import annotations

import re
import time
from xml.etree import ElementTree as ET

import httpx

# 來源（CoinDesk 新版 feed 已空，移除）：名稱 → RSS
_FEEDS = {
    "Cointelegraph": "https://cointelegraph.com/rss",
    "Decrypt": "https://decrypt.co/feed",
    "CryptoSlate": "https://cryptoslate.com/feed/",
    "NewsBTC": "https://www.newsbtc.com/feed/",
    "CryptoPotato": "https://cryptopotato.com/feed/",
    "AMBCrypto": "https://ambcrypto.com/feed/",
}

# 加密語境利多/利空詞庫（標題小寫比對；含詞幹）
_BULL = [
    "surge", "soar", "rally", "rallies", "jump", "gain", "bullish", "breakout",
    "record", "all-time high", "ath", "adoption", "approve", "approval", "etf",
    "partnership", "upgrade", "launch", "integrat", "accumulat", "inflow",
    "institutional", "milestone", "pump", "rise", "rises", "climb", "rebound",
    "recovery", "optimis", "boost", "greenlight", "halving", "soars", "surges",
    "momentum", "buy", "buys", "bought", "winning", "wins", "support", "backs",
    "unlock", "treasury", "reserve", "outperform", "rebounds", "skyrocket",
]
_BEAR = [
    "crash", "plunge", "plummet", "drop", "fall", "dump", "bearish", "sell-off",
    "selloff", "hack", "exploit", "lawsuit", "sue", "sues", "sec ", "ban ",
    "banned", "fraud", "scam", "liquidat", "outflow", "fear", "fud", "decline",
    "slump", "tumble", "collapse", "warning", "bankruncy", "bankrupt", "default",
    "delist", "breach", "stolen", "steal", "rug", "correction", "downturn",
    "sink", "slide", "slides", "bleed", "fine", "penalty", "charge", "charges",
    "investigat", "halt", "freeze", "frozen", "loss", "losses", "drain", "panic",
    "crackdown", "probe", "warn", "warns", "risk", "weak", "down",
]

# 幣 → 標題比對用名稱（出現即標記影響幣）
_COIN_NAMES = {
    "BTC": ["btc", "bitcoin"], "ETH": ["eth", "ethereum", "ether"],
    "SOL": ["sol", "solana"], "XRP": ["xrp", "ripple"], "DOGE": ["doge", "dogecoin"],
    "BNB": ["bnb", "binance coin"], "ADA": ["ada", "cardano"], "AVAX": ["avax", "avalanche"],
    "LINK": ["chainlink"], "MATIC": ["matic", "polygon"], "DOT": ["polkadot"],
    "SHIB": ["shib", "shiba"], "PEPE": ["pepe"], "WIF": ["dogwifhat"],
    "SUI": ["sui"], "TRX": ["tron"], "TON": ["toncoin"], "HYPE": ["hyperliquid"],
    "LTC": ["litecoin"], "BCH": ["bitcoin cash"], "NEAR": ["near protocol"],
    "APT": ["aptos"], "ARB": ["arbitrum"], "OP": ["optimism"], "INJ": ["injective"],
    "TIA": ["celestia"], "SEI": ["sei network"], "UNI": ["uniswap"], "AAVE": ["aave"],
    "FIL": ["filecoin"], "ATOM": ["cosmos"], "ENA": ["ethena"], "ONDO": ["ondo"],
}


def _score_sentiment(text: str) -> tuple[str, int]:
    """回 (sentiment, net)：net = 利多詞命中 - 利空詞命中。"""
    t = text.lower()
    bull = sum(1 for w in _BULL if w in t)
    bear = sum(1 for w in _BEAR if w in t)
    net = bull - bear
    return ("bull" if net > 0 else "bear" if net < 0 else "neutral"), net


def _tag_coins(text: str) -> list[str]:
    t = text.lower()
    out = []
    for sym, names in _COIN_NAMES.items():
        if any(re.search(rf"\b{re.escape(n)}\b", t) for n in names):
            out.append(sym)
    return out


def _parse_ts(s: str | None) -> int | None:
    if not s:
        return None
    from email.utils import parsedate_to_datetime
    try:
        return int(parsedate_to_datetime(s).timestamp())
    except Exception:
        return None


class NewsClient:
    def __init__(self, timeout: float = 15.0):
        self._client = httpx.Client(
            timeout=timeout, headers={"User-Agent": "crypig/0.1"}, follow_redirects=True)
        self._cache: dict | None = None
        self._ts: float = 0.0

    def _fetch_feed(self, source: str, url: str) -> list[dict]:
        try:
            r = self._client.get(url)
            if r.status_code != 200:
                return []
            root = ET.fromstring(r.content)
        except Exception:
            return []
        items = []
        for it in root.iter("item"):
            title = (it.findtext("title") or "").strip()
            if not title:
                continue
            link = (it.findtext("link") or "").strip()
            desc = re.sub(r"<[^>]+>", " ", it.findtext("description") or "")[:300]
            ts = _parse_ts(it.findtext("pubDate"))
            sentiment, net = _score_sentiment(title + " " + desc)
            coins = _tag_coins(title + " " + desc)
            items.append({"title": title, "link": link, "source": source, "ts": ts,
                          "sentiment": sentiment, "net": net, "coins": coins})
        return items

    def analyze(self, ttl: float = 600.0, limit: int = 60) -> dict:
        """彙整新聞：整體偏多/偏空、各幣新聞淨情緒、標題清單（含利多/利空＋影響幣）。"""
        if self._cache is not None and time.time() - self._ts < ttl:
            return self._cache
        items: list[dict] = []
        for source, url in _FEEDS.items():
            items += self._fetch_feed(source, url)
        if not items:
            return self._cache or {"items": [], "summary": {}, "total": 0}
        # 依時間新到舊（無時間者排後）
        items.sort(key=lambda x: x["ts"] or 0, reverse=True)

        bull = sum(1 for i in items if i["sentiment"] == "bull")
        bear = sum(1 for i in items if i["sentiment"] == "bear")
        neutral = len(items) - bull - bear
        # 各幣新聞淨情緒（被提及的幣，聚合 net 與則數）
        coin_stats: dict[str, dict] = {}
        for i in items:
            for sym in i["coins"]:
                b = coin_stats.setdefault(sym, {"mentions": 0, "net": 0, "bull": 0, "bear": 0})
                b["mentions"] += 1
                b["net"] += i["net"]
                if i["sentiment"] == "bull":
                    b["bull"] += 1
                elif i["sentiment"] == "bear":
                    b["bear"] += 1
        top_coins = sorted(coin_stats.items(), key=lambda kv: kv[1]["mentions"], reverse=True)[:12]
        out = {
            "items": items[:limit],
            "summary": {
                "bull": bull, "bear": bear, "neutral": neutral,
                "net": bull - bear,
                "bias": "偏多" if bull - bear > 2 else "偏空" if bull - bear < -2 else "中性",
                "top_coins": [{"symbol": s, **v} for s, v in top_coins],
                "sources": len(_FEEDS),
            },
            "total": len(items),
        }
        self._cache, self._ts = out, time.time()
        return out

    def close(self) -> None:
        self._client.close()
