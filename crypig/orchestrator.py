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
        self._prev_pos: dict[str, dict] = {}    # 上一輪各幣 聰明錢/鯨魚 淨多空(算20分鐘變化)
        self.trader_summary: dict = {}          # 前N名交易者多空人數/比例/槓桿(看決心)
        # 以下 CoinGecko 資料只在每輪(背景)抓一次並快取，請求端只讀不打 API（避免被封）
        self.macro: dict | None = None          # 全市場宏觀
        self.market_caps: dict[str, dict] = {}  # SYMBOL -> {market_cap, volume_24h}
        self.deriv_agg: dict[str, dict] = {}    # SYMBOL -> 跨所聚合 OI/funding
        self._md: MarketDataClient | None = None
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
            if entry:
                out[coin] = entry
        self._prev_pos = new_pos
        return out

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
