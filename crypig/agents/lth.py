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

    def __init__(self, config, history=None):
        super().__init__(config)
        self._history = history
        self._store = SnapshotStore(config.snapshot_db)
        self._client: BitcoinDataClient | None = None

    def fetch(self, symbol: str) -> dict:
        cfg = self.config.agents.lth
        if not self.config.use_mock:
            if symbol != cfg.onchain_symbol:
                return {"threshold_days": cfg.threshold_days, "lth_supply": None,
                        "note": f"鏈上 LTH 為 {cfg.onchain_symbol} 指標，{symbol} 不適用"}
            if self._history is not None:
                data, meta = self._history.read()
                return {"threshold_days": cfg.threshold_days,
                        "lth_supply": data["balance_btc"] if data else None,
                        "as_of": data["as_of"] if data else None,
                        "freshness": meta,
                        "note": "日資料更新失敗，等待重試" if meta["refresh_failed"] else "日資料等待背景取得"}
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

        freshness = raw.get("freshness", {})
        state = ("更新失敗，保留上次日資料；" if freshness.get("refresh_failed") else
                 "背景更新中，保留上次日資料；" if freshness.get("refreshing") else
                 "快取待更新；" if freshness.get("stale") else "")
        # Daily supply is descriptive: ageing and transfers are not trade evidence.
        return Observation(
            source=self.name, symbol=symbol, signal_type="lth_supply",
            direction="neutral", magnitude=0.0, status="informational",
            summary=f"{symbol} 長期持有者供給 {supply:,.0f} BTC（截至 {raw.get('as_of') or '來源日期未提供'}）；{state}請看獨立日資料分析。供給變化不直接代表買賣。",
            entities=[("cohort", "long_term_holders"), ("asset", symbol)],
            relations=[], raw=raw,
        )
