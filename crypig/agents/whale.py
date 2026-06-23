"""鯨魚 / 全市場持倉 Agent。

「鯨魚是否在賣」字面意義需要現貨託管/鏈上充提資料（Hyperliquid 為衍生品
DEX，沒有這類資料）。改用 Hyperliquid 的兩個真實免費訊號：
  - open_interest：全市場持倉量
  - funding：資金費率（多空擁擠度）
並把每輪快照落地，據此算「持倉量變化」判斷加倉/減倉（是否在賣）。

判讀：
  - 持倉量增 + 價格跌 → 空單進場（市場在做空/賣壓）→ 偏空
  - 持倉量減 + 價格跌 → 多單去槓桿/平倉（賣壓但動能衰竭）
  - 資金費率明顯為正 → 多單擁擠（潛在見頂）→ 偏空
  - 資金費率明顯為負 → 空單擁擠（潛在軋空）→ 偏多（反向）
mock 版用合成資料，介面一致。
"""
from __future__ import annotations

import random
import time

from .base import Agent
from ..clients.hyperliquid import HyperliquidClient
from ..storage.models import Observation
from ..storage.snapshots import SnapshotStore

_HOURS_PER_YEAR = 24 * 365


class WhaleAgent(Agent):
    name = "whale_flow"

    def __init__(self, config):
        super().__init__(config)
        self._client: HyperliquidClient | None = None
        self._store = SnapshotStore(config.snapshot_db)
        self._ctx: dict | None = None
        self._ctx_ts: float = 0.0

    def _contexts(self) -> dict:
        if self._ctx is not None and time.time() - self._ctx_ts < 90:
            return self._ctx
        if self._client is None:
            self._client = HyperliquidClient()
        self._ctx = self._client.market_contexts()
        self._ctx_ts = time.time()
        return self._ctx

    def fetch(self, symbol: str) -> dict:
        if not self.config.use_mock:
            ctx = self._contexts().get(symbol, {})
            oi = ctx.get("open_interest", 0.0)
            price = ctx.get("mark_px", 0.0)
            funding = ctx.get("funding", 0.0)
            prev_oi = self._store.latest(self.name, symbol, "open_interest")
            prev_px = self._store.latest(self.name, symbol, "mark_px")
            return {
                "open_interest": oi,
                "mark_px": price,
                "funding": funding,
                "prev_open_interest": prev_oi[1] if prev_oi else None,
                "prev_mark_px": prev_px[1] if prev_px else None,
            }

        rng = random.Random(f"{symbol}-whale-{int(time.time()/600)}")
        oi = rng.uniform(1e4, 1e6)
        return {
            "open_interest": oi,
            "mark_px": rng.uniform(50, 60000),
            "funding": rng.uniform(-3e-5, 3e-5),
            "prev_open_interest": oi * rng.uniform(0.9, 1.1),
            "prev_mark_px": None,
        }

    def analyze(self, symbol: str, raw: dict) -> Observation:
        oi = raw["open_interest"]
        funding = raw["funding"]
        funding_ann = funding * _HOURS_PER_YEAR          # 年化資金費率
        prev_oi = raw.get("prev_open_interest")
        prev_px = raw.get("prev_mark_px")
        price = raw["mark_px"]

        # 落地本輪快照（供下一輪算變化）
        ts = None
        from datetime import datetime, timezone
        ts = datetime.now(timezone.utc).isoformat()
        self._store.record(self.name, symbol, "open_interest", oi, ts)
        self._store.record(self.name, symbol, "mark_px", price, ts)

        # 1) 資金費率：擁擠度
        if funding_ann > 0.05:
            f_dir, f_note = "bear", f"多單擁擠（年化資金費率 {funding_ann:+.1%}）"
        elif funding_ann < -0.05:
            f_dir, f_note = "bull", f"空單擁擠，潛在軋空（年化資金費率 {funding_ann:+.1%}）"
        else:
            f_dir, f_note = "neutral", f"資金費率中性（年化 {funding_ann:+.1%}）"

        # 2) 持倉量變化 + 價格 → 加倉/減倉方向
        oi_note = "（無前一輪快照，持倉變化待累積）"
        oi_dir = "neutral"
        if prev_oi:
            oi_chg = (oi - prev_oi) / prev_oi if prev_oi else 0.0
            px_chg = (price - prev_px) / prev_px if prev_px else 0.0
            if oi_chg > 0.01 and px_chg < 0:
                oi_dir, oi_note = "bear", f"持倉量增 {oi_chg:+.1%} 且價跌，空單進場（賣壓）"
            elif oi_chg > 0.01 and px_chg > 0:
                oi_dir, oi_note = "bull", f"持倉量增 {oi_chg:+.1%} 且價漲，多單進場"
            elif oi_chg < -0.01:
                oi_dir, oi_note = "neutral", f"持倉量減 {oi_chg:+.1%}，去槓桿/平倉"
            else:
                oi_note = f"持倉量變化 {oi_chg:+.1%}（平穩）"

        # 綜合：資金費率與持倉變化各半，取較強者方向
        scores = {"bull": 0, "bear": 0, "neutral": 0}
        scores[f_dir] += 1
        scores[oi_dir] += 1
        direction = max(scores, key=scores.get)
        if scores["bull"] == scores["bear"]:
            direction = "neutral"
        magnitude = min(abs(funding_ann) / 0.3 + 0.2, 1.0) if direction != "neutral" else 0.1

        summary = f"{symbol} 全市場持倉：{oi_note}；{f_note}。OI={oi:,.0f}。"
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
