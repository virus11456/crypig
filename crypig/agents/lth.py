"""LTH 供給僅作描述，不以供給差額推論成交或方向。"""
from __future__ import annotations

import random
from datetime import datetime, timezone

from .base import Agent
from ..clients.bitcoin_data import BitcoinDataClient, RateLimited
from ..storage.models import Observation
from ..storage.snapshots import SnapshotStore


class LTHAgent(Agent):
    name = "lth_supply"

    def __init__(self, config):
        super().__init__(config)
        self._store = SnapshotStore(config.snapshot_db)
        self._client: BitcoinDataClient | None = None

    def fetch(self, symbol: str) -> dict:
        cfg = self.config.agents.lth
        if not self.config.use_mock:
            if symbol != cfg.onchain_symbol:
                return {"threshold_days": cfg.threshold_days, "lth_supply": None,
                        "note": f"鏈上 LTH 為 {cfg.onchain_symbol} 指標，{symbol} 不適用"}
            if self._client is None:
                self._client = BitcoinDataClient()
            try:
                m = self._client.fetch_metric(
                    cfg.metric_slug, value_key=(cfg.value_key or None))
                return {"threshold_days": cfg.threshold_days,
                        "lth_supply": m["value"], "as_of": m.get("date")}
            except RateLimited:
                return {"threshold_days": cfg.threshold_days, "lth_supply": None,
                        "note": "bitcoin-data.com 每小時額度用完，本輪無新資料"}

        rng = random.Random(f"{symbol}-lth-{int(datetime.now().timestamp()/3600)}")
        return {
            "threshold_days": cfg.threshold_days,
            "lth_supply": rng.uniform(1e6, 2e7),   # 合成：LTH 持有量
        }

    def analyze(self, symbol: str, raw: dict) -> Observation:
        supply = raw["lth_supply"]
        threshold = raw["threshold_days"]

        # 無數值（非 BTC 或限流）→ 中性註記
        if supply is None:
            return Observation(
                source=self.name, symbol=symbol, signal_type="lth_supply",
                direction="neutral", magnitude=0.0, status="no_data",
                summary=f"{symbol} 長期持有者：{raw.get('note', '無資料')}。",
                entities=[("cohort", "long_term_holders"), ("asset", symbol)],
                relations=[], raw=raw,
            )

        # Daily supply is descriptive: ageing and transfers are not trade evidence.
        return Observation(
            source=self.name, symbol=symbol, signal_type="lth_supply",
            direction="neutral", magnitude=0.0, status="informational",
            summary=f"{symbol} 長期持有者供給 {supply:,.0f} BTC（截至 {raw.get('as_of') or '來源日期未提供'}）；請看獨立日資料分析。供給變化不直接代表買賣。",
            entities=[("cohort", "long_term_holders"), ("asset", symbol)],
            relations=[], raw=raw,
        )
