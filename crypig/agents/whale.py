"""鯨魚 Agent：交易所淨流入/流出，判斷鯨魚是否在賣。

淨流入交易所（充值）通常代表準備賣出；淨流出（提幣）代表囤幣。
正式版資料源：CryptoQuant / Glassnode netflow，或自追大額鏈上轉帳。
"""
from __future__ import annotations

import random

from .base import Agent
from ..storage.models import Observation


class WhaleAgent(Agent):
    name = "whale_flow"

    def fetch(self, symbol: str) -> dict:
        if not self.config.use_mock:
            # TODO: 接交易所淨流資料源（CryptoQuant/Glassnode）或鏈上大額轉帳
            raise NotImplementedError("交易所淨流整合待實作")

        rng = random.Random(f"{symbol}-whale")
        inflow = rng.uniform(0, 5) * 1e7
        outflow = rng.uniform(0, 5) * 1e7
        return {"exchange_inflow_usd": inflow, "exchange_outflow_usd": outflow}

    def analyze(self, symbol: str, raw: dict) -> Observation:
        inflow = raw["exchange_inflow_usd"]
        outflow = raw["exchange_outflow_usd"]
        total = inflow + outflow or 1.0
        net = (inflow - outflow) / total          # +:淨流入(偏賣)  -:淨流出(偏買)
        # 淨流入 = 賣壓 = 偏空
        direction = "bear" if net > 0.1 else "bull" if net < -0.1 else "neutral"
        if direction == "bear":
            stance = "鯨魚淨充值交易所，可能準備賣出"
        elif direction == "bull":
            stance = "鯨魚淨提幣離開交易所，傾向囤幣"
        else:
            stance = "鯨魚進出大致平衡"

        summary = f"{symbol}：{stance}（交易所淨流 {net:+.0%}）。"
        return Observation(
            source=self.name,
            symbol=symbol,
            signal_type="netflow",
            direction=direction,
            magnitude=min(abs(net), 1.0),
            summary=summary,
            entities=[("cohort", "whales"), ("asset", symbol), ("venue", "exchanges")],
            relations=[
                ("whales", "net_inflow_to_exchanges" if net > 0 else "net_outflow_from_exchanges", symbol),
            ],
            raw=raw,
        )
