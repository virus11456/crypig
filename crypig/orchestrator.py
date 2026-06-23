"""協調中台：跑所有 agent → 餵知識圖譜 → 算綜合評分。"""
from __future__ import annotations

import logging

from .config import Config, get_config
from .agents import SmartMoneyAgent, WhaleAgent, DivergenceAgent
from .aggregate import aggregate
from .kg import SelfLearningRAG
from .storage.models import Observation

logger = logging.getLogger(__name__)


class Orchestrator:
    def __init__(self, config: Config | None = None):
        self.config = config or get_config()
        self.rag = SelfLearningRAG(self.config)
        self.agents = []
        a = self.config.agents
        if a.smart_money.enabled:
            self.agents.append(SmartMoneyAgent(self.config))
        if a.whales.enabled:
            self.agents.append(WhaleAgent(self.config))
        if a.divergence.enabled:
            self.agents.append(DivergenceAgent(self.config))

    def run_cycle(self) -> dict:
        observations: list[Observation] = []
        for agent in self.agents:
            obs = agent.run()
            logger.info("agent %s 產出 %d 筆觀察", agent.name, len(obs))
            observations.extend(obs)

        added = self.rag.ingest_many(observations)
        signals = aggregate(observations, self.config)
        logger.info("知識圖譜新增 %d 條關係；圖譜現況 %s", added, self.rag.stats())
        return {"signals": signals, "kg": self.rag.stats(), "ingested": added}

    def ask(self, question: str) -> dict:
        return self.rag.ask(question)
