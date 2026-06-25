"""協調中台：跑所有 agent → 餵知識圖譜 → 算綜合評分。"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from .config import Config, get_config
from .agents import SmartMoneyAgent, WhaleAgent, DivergenceAgent, LTHAgent
from .clients.market_data import MarketDataClient
from .aggregate import aggregate
from .kg import SelfLearningRAG
from .storage.models import Observation
from .storage.decisions import DecisionStore

logger = logging.getLogger(__name__)


class Orchestrator:
    def __init__(self, config: Config | None = None):
        self.config = config or get_config()
        self.rag = SelfLearningRAG(self.config)
        self.decisions = DecisionStore(self.config.decisions_db)
        self.all_scores: dict[str, dict] = {}   # 全市場各幣輕量決策(聰明錢+資金費率)
        self.radar: dict = {}                   # 分歧雷達：群眾(情緒/費率) vs 大戶(聰明錢/鯨魚)
        self._prev_pos: dict[str, dict] = {}    # 上一輪各幣 聰明錢/鯨魚 淨多空(算20分鐘變化)
        self.trader_summary: dict = {}          # 前N名交易者多空人數/比例/槓桿(看決心)
        # 以下 CoinGecko 資料只在每輪(背景)抓一次並快取，請求端只讀不打 API（避免被封）
        self.macro: dict | None = None          # 全市場宏觀
        self.market_caps: dict[str, dict] = {}  # SYMBOL -> {market_cap, volume_24h}
        self.deriv_agg: dict[str, dict] = {}    # SYMBOL -> 跨所聚合 OI/funding
        self.social: dict[str, dict] = {}       # SYMBOL -> LunarCrush 社群情緒(需付費金鑰)
        self.fear_greed: dict = {}              # 全市場恐懼貪婪指數(免費 alternative.me)
        self.defi: dict = {}                    # DefiLlama 資金動向(TVL/穩定幣/各鏈，免費)
        self.reddit: dict = {}                  # Reddit 散戶討論熱度/情緒(需 app 憑證)
        self._md: MarketDataClient | None = None
        self._lc = None
        self._dl = None
        self._rd = None
        self.agents = []
        a = self.config.agents
        if a.smart_money.enabled:
            self.agents.append(SmartMoneyAgent(self.config))
        if a.whales.enabled:
            self.agents.append(WhaleAgent(self.config))
        if a.divergence.enabled:
            self.agents.append(DivergenceAgent(self.config))
        if a.lth.enabled:
            self.agents.append(LTHAgent(self.config))

    def run_cycle(self) -> dict:
        observations: list[Observation] = []
        for agent in self.agents:
            obs = agent.run()
            logger.info("agent %s 產出 %d 筆觀察", agent.name, len(obs))
            observations.extend(obs)

        added = self.rag.ingest_many(observations)
        signals = aggregate(observations, self.config)
        prices = self._prices(observations)
        ts = datetime.now(timezone.utc).isoformat()
        saved = self.decisions.record_cycle(signals, ts, prices)
        self.all_scores = self._compute_all_scores()      # 全市場各幣輕量決策
        self._refresh_market_data()                       # 背景抓一次 CoinGecko 並快取
        self.radar = self._divergence_radar()             # 群眾 vs 大戶 分歧雷達
        logger.info("知識圖譜新增 %d 條關係；決策落地 %d 筆；全市場評分 %d 幣；圖譜現況 %s",
                    added, saved, len(self.all_scores), self.rag.stats())
        return {"signals": signals, "kg": self.rag.stats(), "ingested": added,
                "decisions_saved": saved, "scored_coins": len(self.all_scores), "ts": ts}

    def _compute_all_scores(self) -> dict[str, dict]:
        """用每輪已抓回的整批資料（聰明錢全幣持倉 + 全幣資金費率擁擠）幫**所有幣**
        算 score/label/信心。不額外打 per-coin API。mock 模式略過。
        """
        if self.config.use_mock:
            return {}
        sm = next((a for a in self.agents if a.name == "smart_money"), None)
        if sm is None:
            return {}
        try:
            aggs = sm._coin_aggregates()                  # coin -> {long,short,count}（已快取）
        except Exception:
            logger.exception("全市場評分：聰明錢聚合失敗")
            return {}
        self.trader_summary = sm._trader_summary       # 多空人數/槓桿摘要
        cfg = self.config.agents.smart_money
        from .clients.hyperliquid import HyperliquidClient
        hlc = sm._client or HyperliquidClient()
        funding: dict[str, float] = {}
        try:
            funding = {r["symbol"]: r["funding_ann"] for r in hlc.funding_scan()}
        except Exception:
            funding = {}

        coins = set(aggs) | set(funding)
        div = self._divergence_scan(hlc, sorted(coins))   # {coin: (direction,mag,note)}

        out: dict[str, dict] = {}
        new_pos: dict[str, dict] = {}
        for coin in coins:
            obs: list[Observation] = []
            agg = aggs.get(coin)
            if agg and agg["long"] + agg["short"] > 0:    # 聰明錢持倉訊號
                obs.append(sm.analyze(coin, {
                    "threshold_usd": cfg.pnl_threshold_usd, "window": cfg.window,
                    "trader_count": sm._trader_count, "position_count": agg["count"],
                    "long_notional_usd": agg["long"], "short_notional_usd": agg["short"]}))
            fa = funding.get(coin)
            if fa is not None:                            # 資金費率擁擠（反向）訊號
                if fa > 0.25:
                    fdir, fmag = "bear", min(abs(fa) + 0.2, 1.0)
                elif fa < -0.05:
                    fdir, fmag = "bull", min(abs(fa) + 0.2, 1.0)
                else:
                    fdir, fmag = "neutral", 0.1
                obs.append(Observation(
                    source="whale_flow", symbol=coin, signal_type="funding",
                    direction=fdir, magnitude=fmag,
                    summary=f"{coin} 資金費率年化 {fa*100:+.1f}%"))
            ddir, dmag, dnote = div.get(coin, ("neutral", 0.0, ""))
            if ddir != "neutral":                         # 日線量價背離訊號
                obs.append(Observation(
                    source="divergence", symbol=coin, signal_type="divergence",
                    direction=ddir, magnitude=dmag, summary=dnote))
            # 聰明錢 / 鯨魚 淨多空 + 與上一輪(約20分鐘)的變化
            sm_net = whale_net = None
            if agg:
                tot = agg["long"] + agg["short"]
                if tot > 0:
                    sm_net = (agg["long"] - agg["short"]) / tot
                wtot = agg.get("whale_long", 0) + agg.get("whale_short", 0)
                if wtot > 0:
                    whale_net = (agg["whale_long"] - agg["whale_short"]) / wtot
            prev = self._prev_pos.get(coin, {})
            entry = {}
            if sm_net is not None:
                entry["sm_net"] = round(sm_net, 4)
                if "sm_net" in prev:
                    entry["sm_delta"] = round(sm_net - prev["sm_net"], 4)
            if whale_net is not None:
                entry["whale_net"] = round(whale_net, 4)
                entry["whale_count"] = agg.get("whale_count", 0)
                if "whale_net" in prev:
                    entry["whale_delta"] = round(whale_net - prev["whale_net"], 4)
            new_pos[coin] = {k: entry[k] for k in ("sm_net", "whale_net") if k in entry}

            if obs:
                r = aggregate(obs, self.config).get(coin)
                if r:
                    entry.update({"score": r["score"], "label": r["label"],
                                  "confidence": r["confidence"], "divergence": ddir})
            if fa is not None:
                entry["funding_ann"] = round(fa, 4)
            if entry:
                out[coin] = entry
        self._prev_pos = new_pos
        return out

    def _divergence_radar(self) -> dict:
        """分歧雷達：群眾 vs 大戶反向 = alpha。

        群眾(各幣)：資金費率→市場擁擠方向(正費率=群眾做多/擁擠多單)。
        大戶(各幣)：聰明錢淨多空 sm_net。
        市場層級：恐懼貪婪(群眾) vs 聰明錢整體淨多空。
        反向且都有份量才算背離；依強度排序，列出 alpha 候選。
        """
        coins = []
        for sym, sc in (self.all_scores or {}).items():
            sm = sc.get("sm_net")
            fa = sc.get("funding_ann")
            if sm is None or fa is None:
                continue
            crowd = max(-1.0, min(1.0, fa / 0.5))         # 群眾(費率)多空
            if crowd > 0.1 and sm < -0.1:                 # 群眾做多 vs 聰明錢做空
                typ, bias, score = "頂部反指標", "看空", min(crowd, 1) + min(-sm, 1)
            elif crowd < -0.1 and sm > 0.1:               # 群眾做空 vs 聰明錢做多
                typ, bias, score = "底部機會", "看多", min(-crowd, 1) + min(sm, 1)
            else:
                continue
            coins.append({"symbol": sym, "crowd": round(crowd, 3), "smart": round(sm, 3),
                          "whale": sc.get("whale_net"), "funding_ann": fa,
                          "type": typ, "bias": bias, "score": round(score, 3)})
        coins.sort(key=lambda c: c["score"], reverse=True)

        # 市場層級：恐懼貪婪(群眾) vs 聰明錢整體
        sms = [s["sm_net"] for s in (self.all_scores or {}).values() if s.get("sm_net") is not None]
        smart_avg = sum(sms) / len(sms) if sms else 0.0
        fg = self.fear_greed or {}
        fgv = fg.get("value")
        crowd_m = (fgv - 50) / 50 if fgv is not None else 0.0   # 貪婪=+1群眾多 / 恐懼=-1群眾空
        market = {"fear_greed": fgv, "fg_label": fg.get("label"),
                  "fg_percentile": fg.get("percentile"),
                  "smart_avg": round(smart_avg, 3),
                  "crowd_dir": "貪婪偏多" if crowd_m > 0.1 else "恐懼偏空" if crowd_m < -0.1 else "中性",
                  "smart_dir": "偏多" if smart_avg > 0.05 else "偏空" if smart_avg < -0.05 else "中性"}
        if crowd_m > 0.1 and smart_avg < -0.05:
            market["verdict"] = "🔺 群眾貪婪、聰明錢做空 → 頂部反指標，偏空"
            market["diverging"] = True
        elif crowd_m < -0.1 and smart_avg > 0.05:
            market["verdict"] = "🔻 群眾恐懼、聰明錢做多 → 底部機會，偏多"
            market["diverging"] = True
        else:
            align = "偏空" if smart_avg < 0 else "偏多"
            market["verdict"] = (f"群眾與聰明錢同向（{market['crowd_dir']}＋聰明錢{market['smart_dir']}）"
                                 f"→ 順勢{align}，尚無反轉背離（盯聰明錢何時翻向）")
            market["diverging"] = False
        return {"market": market, "coins": coins[:20]}

    def _refresh_market_data(self) -> None:
        """每輪(背景)抓一次 CoinGecko：全市場宏觀、各幣市值、跨所聚合 OI。
        全部快取在本物件，請求端只讀，CoinGecko 從『每次刷新都打』降到 20 分鐘 3 支。
        失敗時沿用上次快取（不清空）。"""
        if self.config.use_mock:
            return
        if self._md is None:
            self._md = MarketDataClient()
        for name, fn in (("deriv", lambda: self._md.aggregate_derivatives(ttl=0)),
                         ("macro", self._md.global_macro),
                         ("caps", self._md.top_markets)):
            try:
                val = fn()
                if name == "deriv" and val:
                    self.deriv_agg = val
                elif name == "macro" and val:
                    self.macro = val
                elif name == "caps" and val:
                    self.market_caps = val
            except Exception:
                logger.warning("CoinGecko %s 抓取失敗，沿用上次快取", name)
        # 恐懼貪婪指數（免費、無金鑰、全市場情緒）—— 全區間歷史(2018至今)
        try:
            r = self._md._client.get("https://api.alternative.me/fng/?limit=0")
            d = r.json().get("data") if r.status_code == 200 else None
            if isinstance(d, list) and d:
                vals = [int(x["value"]) for x in d]
                cur = int(d[0]["value"])
                below = sum(1 for v in vals if v < cur)
                self.fear_greed = {
                    "value": cur,
                    "label": d[0]["value_classification"],
                    "percentile": round(below / len(vals) * 100),   # 歷史百分位(越低=越罕見的恐懼)
                    "hist_min": min(vals), "hist_max": max(vals), "days": len(vals),
                    "history": [{"v": int(x["value"]), "t": x["timestamp"]} for x in reversed(d)],
                }
        except Exception:
            logger.warning("Fear&Greed 抓取失敗")
        # DefiLlama 資金動向（免費）
        try:
            if self._dl is None:
                from .clients.defillama import DefiLlamaClient
                self._dl = DefiLlamaClient()
            snap = self._dl.snapshot()
            if snap:
                self.defi = snap
        except Exception:
            logger.warning("DefiLlama 抓取失敗")
        # Reddit 散戶討論熱度（需 app 憑證才抓）
        try:
            if self._rd is None:
                from .clients.reddit import RedditClient
                self._rd = RedditClient()
            if self._rd.enabled:
                buzz = self._rd.crypto_buzz()
                if buzz:
                    self.reddit = buzz
        except Exception:
            logger.warning("Reddit 討論熱度抓取失敗")
        # LunarCrush 社群情緒（需付費金鑰；有才抓）
        try:
            if self._lc is None:
                from .clients.lunarcrush import LunarCrushClient
                self._lc = LunarCrushClient()
            if self._lc.enabled:
                soc = self._lc.fetch_coins_sentiment()
                if soc:
                    self.social = soc
        except Exception:
            logger.warning("LunarCrush 社群情緒抓取失敗")

    def _divergence_scan(self, hlc, coins: list[str]) -> dict[str, tuple]:
        """並發抓日線、算每幣量價背離（direction, magnitude, note）。失敗回空。"""
        try:
            from .agents.divergence import classify_divergence
            bulk = hlc.daily_closes_bulk(coins)
            out: dict[str, tuple] = {}
            for coin, (closes, vols) in bulk.items():
                if len(closes) >= 31:
                    out[coin] = classify_divergence(closes, vols)
            return out
        except Exception:
            logger.exception("全市場背離掃描失敗")
            return {}

    @staticmethod
    def _prices(observations: list[Observation]) -> dict[str, float]:
        """取各幣決策當下價（divergence 觀察帶 price=OHLCV 收盤；real=OKX、mock=合成）。"""
        prices: dict[str, float] = {}
        for o in observations:
            if not isinstance(o.raw, dict):
                continue
            p = o.raw.get("price")
            if p is None and o.raw.get("closes"):
                p = o.raw["closes"][-1]
            if p is not None:
                prices[o.symbol] = float(p)
        return prices

    def ask(self, question: str) -> dict:
        return self.rag.ask(question)
