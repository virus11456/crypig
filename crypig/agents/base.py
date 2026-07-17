"""Agent 基底類別。

每個 agent 負責一個資料源：抓資料 → 正規化成 Observation。
抓取（fetch）與分析（analyze）分離，方便 mock 與接真實 API 時只改 fetch。
"""
from __future__ import annotations

import abc
import logging

from ..config import Config
from ..storage.models import Observation

logger = logging.getLogger(__name__)


class Agent(abc.ABC):
    name: str = "agent"

    def __init__(self, config: Config):
        self.config = config

    @abc.abstractmethod
    def fetch(self, symbol: str) -> dict:
        """抓原始資料。mock 模式回傳假資料；正式接 API 時替換這裡。"""

    @abc.abstractmethod
    def analyze(self, symbol: str, raw: dict) -> Observation:
        """把原始資料轉成 Observation（含多空方向、強度、KG 三元組）。"""

    def run(self) -> list[Observation]:
        out: list[Observation] = []
        for symbol in self.config.symbols:
            try:
                raw = self.fetch(symbol)
                out.append(self.analyze(symbol, raw))
            except Exception:  # 單一標的失敗不影響其他
                logger.exception("%s failed on %s", self.name, symbol)
        return out
