"""聰明錢 Agent：近一年實現獲利超過門檻者的多空持倉。

正式版資料源：Hyperliquid 公開 API（leaderboard + clearinghouseState 取持倉）。
mock 版用合成資料，介面與正式版一致。
"""
from __future__ import annotations

import random

from .base import Agent
from ..storage.models import Observation


class SmartMoneyAgent(Agent):
    name = "smart_money"

    def fetch(self, symbol: str) -> dict:
        cfg = self.config.agents.smart_money
        if not self.config.use_mock:
            # TODO: 接 Hyperliquid
            #   1) GET leaderboard，篩 window=year 且 pnl > pnl_threshold_usd
            #   2) 對每個地址 POST /info {type:"clearinghouseState"} 取 symbol 持倉
            #   3) 統計多單/空單名目價值，算淨多空比
            raise NotImplementedError("Hyperliquid 整合待實作")

        rng = random.Random(f"{symbol}-sm")
        n = rng.randint(20, 120)
        long_notional = rng.uniform(1, 10) * 1e6
        short_notional = rng.uniform(1, 10) * 1e6
        return {
            "threshold_usd": cfg.pnl_threshold_usd,
            "trader_count": n,
            "long_notional_usd": long_notional,
            "short_notional_usd": short_notional,
        }

    def analyze(self, symbol: str, raw: dict) -> Observation:
        longs = raw["long_notional_usd"]
        shorts = raw["short_notional_usd"]
        total = longs + shorts or 1.0
        net = (longs - shorts) / total            # -1(全空) ~ +1(全多)
        direction = "bull" if net > 0.1 else "bear" if net < -0.1 else "neutral"
        stance = "偏多" if direction == "bull" else "偏空" if direction == "bear" else "中性"

        summary = (
            f"聰明錢（{raw['trader_count']} 位近一年獲利>"
            f"{raw['threshold_usd']/1e6:.0f}M 交易者）對 {symbol} {stance}，"
            f"淨多空比 {net:+.0%}。"
        )
        return Observation(
            source=self.name,
            symbol=symbol,
            signal_type="positioning",
            direction=direction,
            magnitude=min(abs(net), 1.0),
            summary=summary,
            entities=[("cohort", "smart_money"), ("asset", symbol)],
            relations=[("smart_money", f"is_{direction}_on", symbol)],
            raw=raw,
        )
