"""協調中台：跑所有 agent → 餵知識圖譜 → 算綜合評分。"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from .config import Config, get_config
from .agents import SmartMoneyAgent, WhaleAgent, DivergenceAgent, LTHAgent
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
        cfg = self.config.agents.smart_money
        funding: dict[str, float] = {}
        try:
            from .clients.hyperliquid import HyperliquidClient
            hlc = sm._client or HyperliquidClient()
            funding = {r["symbol"]: r["funding_ann"] for r in hlc.funding_scan()}
        except Exception:
            funding = {}

        out: dict[str, dict] = {}
        for coin, agg in aggs.items():
            obs: list[Observation] = []
            if agg["long"] + agg["short"] > 0:            # 聰明錢持倉訊號
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
            if obs:
                r = aggregate(obs, self.config).get(coin)
                if r:
                    out[coin] = {"score": r["score"], "label": r["label"],
                                 "confidence": r["confidence"]}
        return out

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
