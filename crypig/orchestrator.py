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
        logger.info("知識圖譜新增 %d 條關係；決策落地 %d 筆；圖譜現況 %s",
                    added, saved, self.rag.stats())
        return {"signals": signals, "kg": self.rag.stats(),
                "ingested": added, "decisions_saved": saved, "ts": ts}

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
