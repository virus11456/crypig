"""長期持有者（LTH）Agent：持有 ≥ 門檻天數（預設 151 天）的供給變化。

概念（鏈上經典指標）：
  - LTH 供給上升 → 長期持有者在「累積」（鎖倉）→ 偏多
  - LTH 供給下降 → 長期持有者在「分配/賣出」（常見於行情頂部）→ 偏空
把每輪 LTH 供給落地，據此算變化率。

真實資料源：bitcoin-data.com（免費 BTC 鏈上，每小時限 10 次）。
  - 預設指標 long-term-hodler-supply-btc（真正長期持有者供給，BTC）
  - 為 UTXO 幣齡指標，僅比特幣有；ETH/SOL 為帳戶模型，回中性註記
  - 業界 LTH 門檻約 155 天，與要求的「超過 151 天」相近
"""
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
                        "note": "bitcoin-data.com 每小時額度用完，沿用前次快照"}

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
                direction="neutral", magnitude=0.0,
                summary=f"{symbol} 長期持有者(≥{threshold}天)：{raw.get('note', '無資料')}。",
                entities=[("cohort", "long_term_holders"), ("asset", symbol)],
                relations=[], raw=raw,
            )

        ts = datetime.now(timezone.utc).isoformat()
        prev = self._store.latest(self.name, symbol, "lth_supply")
        self._store.record(self.name, symbol, "lth_supply", supply, ts)

        direction, magnitude, note = "neutral", 0.1, "（無前一輪快照，LTH 變化待累積）"
        if prev:
            chg = (supply - prev[1]) / prev[1] if prev[1] else 0.0
            if chg > 0.002:
                direction = "bull"
                note = f"長期持有者供給增 {chg:+.2%}，累積/鎖倉"
            elif chg < -0.002:
                direction = "bear"
                note = f"長期持有者供給減 {chg:+.2%}，分配/賣出"
            else:
                note = f"長期持有者供給變化 {chg:+.2%}（平穩）"
            magnitude = min(abs(chg) * 50 + 0.1, 1.0)

        summary = f"{symbol} 長期持有者(≥{threshold}天)：{note}。"
        return Observation(
            source=self.name,
            symbol=symbol,
            signal_type="lth_supply",
            direction=direction,
            magnitude=magnitude,
            summary=summary,
            entities=[("cohort", "long_term_holders"), ("asset", symbol)],
            relations=[("long_term_holders", f"is_{direction}_on", symbol)]
            if direction != "neutral" else [],
            raw=raw,
        )
