"""鯨魚 / 全市場持倉 Agent。

監測「整個市場」的合約持倉量——聚合 CoinGecko 各交易所衍生品 OI（免金鑰），
不是單一場子。配合各所平均資金費率（多空擁擠度），並把每輪快照落地，
跨輪計算「全市場持倉量變化」判斷加倉/減倉（市場是否在賣）。

判讀：
  - 全市場 OI 增 + 價跌 → 空單進場（賣壓）→ 偏空
  - 全市場 OI 增 + 價漲 → 多單進場 → 偏多
  - 全市場 OI 減 → 去槓桿/平倉
  - 平均資金費率明顯為正 → 多單擁擠（潛在見頂）→ 偏空
  - 平均資金費率明顯為負 → 空單擁擠（潛在軋空）→ 偏多（反向）
mock 版用合成資料，介面一致。
"""
from __future__ import annotations

import random
import time
from datetime import datetime, timezone

from .base import Agent
from ..clients.market_data import MarketDataClient
from ..storage.models import Observation
from ..storage.snapshots import SnapshotStore

_FUNDING_PERIODS_PER_YEAR = 3 * 365   # CoinGecko funding 為 %/8h


class WhaleAgent(Agent):
    name = "whale_flow"

    def __init__(self, config):
        super().__init__(config)
        self._client: MarketDataClient | None = None
        self._store = SnapshotStore(config.snapshot_db)

    def _market(self) -> dict:
        if self._client is None:
            self._client = MarketDataClient()
        return self._client.aggregate_derivatives()

    def fetch(self, symbol: str) -> dict:
        if not self.config.use_mock:
            agg = self._market().get(symbol, {})
            oi = agg.get("open_interest_usd", 0.0)
            funding = agg.get("funding_rate_med", 0.0)
            contracts = agg.get("contracts", 0)
            price = 0.0  # 用價格快照算變化方向（OI 為 USD，價格另取）
            prev_oi = self._store.latest(self.name, symbol, "open_interest_usd")
            return {
                "open_interest_usd": oi,
                "funding_rate_avg": funding,
                "contracts": contracts,
                "mark_px": price,
                "prev_open_interest_usd": prev_oi[1] if prev_oi else None,
            }

        rng = random.Random(f"{symbol}-whale-{int(time.time()/600)}")
        oi = rng.uniform(1e9, 6e10)
        return {
            "open_interest_usd": oi,
            "funding_rate_avg": rng.uniform(-0.3, 0.3),
            "contracts": rng.randint(80, 200),
            "mark_px": 0.0,
            "prev_open_interest_usd": oi * rng.uniform(0.9, 1.1),
        }

    def analyze(self, symbol: str, raw: dict) -> Observation:
        oi = raw["open_interest_usd"]
        funding = raw["funding_rate_avg"]
        funding_ann = funding / 100 * _FUNDING_PERIODS_PER_YEAR   # 年化（小數）
        contracts = raw.get("contracts", 0)
        prev_oi = raw.get("prev_open_interest_usd")

        ts = datetime.now(timezone.utc).isoformat()
        self._store.record(self.name, symbol, "open_interest_usd", oi, ts)

        # 1) 資金費率：多空擁擠度
        if funding_ann > 0.05:
            f_dir, f_note = "bear", f"多單擁擠（年化資金費率 {funding_ann:+.1%}）"
        elif funding_ann < -0.05:
            f_dir, f_note = "bull", f"空單擁擠，潛在軋空（年化資金費率 {funding_ann:+.1%}）"
        else:
            f_dir, f_note = "neutral", f"資金費率中性（年化 {funding_ann:+.1%}）"

        # 2) 全市場持倉量變化
        oi_dir, oi_note = "neutral", "（無前一輪快照，持倉變化待累積）"
        if prev_oi:
            oi_chg = (oi - prev_oi) / prev_oi if prev_oi else 0.0
            if oi_chg > 0.02:
                oi_dir, oi_note = "bear", f"全市場持倉量增 {oi_chg:+.1%}（槓桿增加，留意賣壓）"
            elif oi_chg < -0.02:
                oi_dir, oi_note = "neutral", f"全市場持倉量減 {oi_chg:+.1%}（去槓桿/平倉）"
            else:
                oi_note = f"全市場持倉量變化 {oi_chg:+.1%}（平穩）"

        scores = {"bull": 0, "bear": 0, "neutral": 0}
        scores[f_dir] += 1
        scores[oi_dir] += 1
        direction = max(scores, key=scores.get)
        if scores["bull"] == scores["bear"]:
            direction = "neutral"
        magnitude = min(abs(funding_ann) / 0.3 + 0.2, 1.0) if direction != "neutral" else 0.1

        oi_b = oi / 1e9
        summary = (f"{symbol} 全市場持倉(聚合{contracts}合約)：{oi_note}；{f_note}。"
                   f"OI=${oi_b:,.1f}B。")
        return Observation(
            source=self.name,
            symbol=symbol,
            signal_type="market_positioning",
            direction=direction,
            magnitude=magnitude,
            summary=summary,
            entities=[("asset", symbol), ("metric", "open_interest"), ("metric", "funding")],
            relations=[("market", f"is_{direction}_positioned_on", symbol)]
            if direction != "neutral" else [],
            raw=raw,
        )
