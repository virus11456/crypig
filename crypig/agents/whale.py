"""鯨魚 Agent：監控「大額錢包持有者」的持倉變化量。

鯨魚＝持有大量特定加密貨幣、足以影響市場的錢包。本 agent 用 bitcoin-data
的 wallet-bands（依錢包餘額分級），追蹤鯨魚級距的鏈上總持倉，跨輪算變化：
  - 鯨魚持倉增加 → 大戶在累積/鎖倉 → 偏多
  - 鯨魚持倉減少 → 大戶在分配/出貨（散戶常跟著清倉）→ 偏空
預設「鯨魚」＝餘額 ≥100 BTC 的大戶（駝背鯨 100-1K + 巨鯨 ≥1K），可在設定調整。

非 BTC（ETH/SOL 為帳戶模型，此源無鯨魚分級）退回「全市場合約持倉量(OI)＋
資金費率」的市場槓桿信號，保留多資產覆蓋。mock 版用合成資料，介面一致。
"""
from __future__ import annotations

import math
import random
import time
from datetime import datetime, timezone

from .base import Agent
from ..clients.market_data import MarketDataClient
from ..clients.hyperliquid import HyperliquidClient
from ..clients.bitcoin_data import BitcoinDataClient, RateLimited
from ..storage.models import Observation
from ..storage.snapshots import SnapshotStore

def valid_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


class WhaleAgent(Agent):
    name = "whale_flow"

    def __init__(self, config):
        super().__init__(config)
        self._client: MarketDataClient | None = None
        self._btc: BitcoinDataClient | None = None
        self._hl = None
        self._store = SnapshotStore(config.snapshot_db)

    # ---------- fetch ----------
    def fetch(self, symbol: str) -> dict:
        cfg = self.config.agents.whales
        if not self.config.use_mock:
            if symbol == cfg.onchain_symbol:
                return self._fetch_whale_wallets(symbol, cfg)
            return self._fetch_market(symbol)

        # mock：BTC 走鯨魚錢包路徑、其餘走市場路徑，兩條分支都測得到
        if symbol == cfg.onchain_symbol:
            rng = random.Random(f"{symbol}-whalew-{int(time.time()/600)}")
            whale_btc = rng.uniform(6.5e6, 7.5e6)
            return {"mode": "whale_wallet", "whale_btc": whale_btc,
                    "bands": {b: whale_btc / len(cfg.whale_bands) for b in cfg.whale_bands},
                    "counts": {"humpbackCount": 11000, "megaWhaleCount": 1150},
                    "prev_whale_btc": whale_btc * rng.uniform(0.99, 1.01)}
        rng = random.Random(f"{symbol}-whale-{int(time.time()/600)}")
        oi = rng.uniform(1e9, 6e10)
        return {"mode": "market", "open_interest_usd": oi,
                "funding_ann": rng.uniform(-0.3, 0.3), "funding_source": "mock",
                "contracts": rng.randint(80, 200),
                "prev_open_interest_usd": oi * rng.uniform(0.9, 1.1)}

    def _fetch_whale_wallets(self, symbol: str, cfg) -> dict:
        if self._btc is None:
            self._btc = BitcoinDataClient()
        try:
            data = self._btc.fetch_raw("wallet-bands")
        except RateLimited:
            return {"mode": "whale_wallet", "whale_btc": None,
                    "note": "bitcoin-data.com 每小時額度用完，沿用前次快照"}
        bands = {b: float(data.get(b, 0.0)) for b in cfg.whale_bands}
        whale_btc = sum(bands.values())
        counts = {k: data.get(k) for k in ("whaleCount", "humpbackCount", "megaWhaleCount")}
        prev = self._store.latest(self.name, symbol, "whale_btc")
        return {"mode": "whale_wallet", "whale_btc": whale_btc, "bands": bands,
                "counts": counts, "as_of": data.get("theDate"),
                "prev_whale_btc": prev[1] if prev else None}

    def _fetch_market(self, symbol: str) -> dict:
        if self._client is None:
            self._client = MarketDataClient()
        agg = self._client.aggregate_derivatives().get(symbol, {})
        oi = agg.get("open_interest_usd")
        funding_ann = None
        if valid_number(oi) and oi >= 0:
            try:
                if self._hl is None:
                    self._hl = HyperliquidClient()
                quote = next((r for r in self._hl.funding_scan() if r["symbol"] == symbol), {})
                value = quote.get("funding_ann")
                funding_ann = value if valid_number(value) else None
            except Exception:
                pass
        metric = "open_interest_usd_perpetual_v1"
        prev_oi = self._store.latest(self.name, symbol, metric)
        return {"mode": "market", "open_interest_usd": oi, "oi_metric": metric,
                "funding_ann": funding_ann, "funding_source": "hyperliquid_hourly" if funding_ann is not None else None,
                "contracts": agg.get("contracts", 0),
                "prev_open_interest_usd": prev_oi[1] if prev_oi else None}

    # ---------- analyze ----------
    def analyze(self, symbol: str, raw: dict) -> Observation:
        if raw.get("mode") == "whale_wallet":
            return self._analyze_whale(symbol, raw)
        return self._analyze_market(symbol, raw)

    def _analyze_whale(self, symbol: str, raw: dict) -> Observation:
        cfg = self.config.agents.whales
        whale_btc = raw.get("whale_btc")
        if whale_btc is None:                       # 限流無資料
            return Observation(
                source=self.name, symbol=symbol, signal_type="whale_holdings",
                direction="neutral", magnitude=0.0, status="no_data",
                summary=f"{symbol} 鯨魚持倉：{raw.get('note', '無資料')}。",
                entities=[("cohort", "whales"), ("asset", symbol)], raw=raw)

        ts = datetime.now(timezone.utc).isoformat()
        prev = raw.get("prev_whale_btc")
        self._store.record(self.name, symbol, "whale_btc", whale_btc, ts)

        direction, magnitude, note = "neutral", 0.1, "（無前一輪快照，鯨魚持倉變化待累積）"
        status = "ok" if prev else "warming"
        if prev:
            chg = (whale_btc - prev) / prev if prev else 0.0
            if chg > cfg.chg_threshold:
                direction, note = "bull", f"鯨魚持倉增 {chg:+.2%}（大戶累積/鎖倉）"
            elif chg < -cfg.chg_threshold:
                direction, note = "bear", f"鯨魚持倉減 {chg:+.2%}（大戶分配/出貨）"
            else:
                note = f"鯨魚持倉變化 {chg:+.2%}（平穩）"
            magnitude = min(abs(chg) * 80 + 0.1, 1.0)

        cnt = raw.get("counts", {})
        n = sum(v for v in (cnt.get("humpbackCount"), cnt.get("megaWhaleCount")) if v) or None
        held = f"{whale_btc:,.0f} BTC"
        tail = f"（{n:,} 個大戶錢包）" if n else ""
        summary = f"{symbol} 鯨魚持倉(≥100BTC大戶 共{held}{tail})：{note}。"
        return Observation(
            source=self.name, symbol=symbol, signal_type="whale_holdings",
            direction=direction, magnitude=magnitude, status=status, summary=summary,
            entities=[("cohort", "whales"), ("asset", symbol)],
            relations=[("whales", f"is_{direction}_on", symbol)] if direction != "neutral" else [],
            raw=raw)

    def _analyze_market(self, symbol: str, raw: dict) -> Observation:
        oi = raw.get("open_interest_usd")
        if not valid_number(oi) or oi < 0:
            return Observation(source=self.name, symbol=symbol, signal_type="market_positioning",
                               status="no_data", magnitude=0, summary=f"{symbol} 持倉資料未取得，不計入評分。", raw=raw)
        funding_ann = raw.get("funding_ann")
        if not valid_number(funding_ann):
            funding_ann = None
        prev_oi = raw.get("prev_open_interest_usd")
        self._store.record(self.name, symbol, raw.get("oi_metric", "open_interest_usd"), oi,
                           datetime.now(timezone.utc).isoformat())
        direction, magnitude = "neutral", 0.0
        if funding_ann is None:
            f_note = "資金費率未取得，不計入方向評分"
        elif funding_ann > 0.05:
            direction, f_note = "bear", f"Hyperliquid 費率偏正（年化 {funding_ann:+.1%}）"
        elif funding_ann < -0.05:
            direction, f_note = "bull", f"Hyperliquid 費率偏負（年化 {funding_ann:+.1%}）"
        else:
            f_note = f"Hyperliquid 資金費率中性（年化 {funding_ann:+.1%}）"
        if direction != "neutral":
            magnitude = min(abs(funding_ann) / 0.3 + 0.2, 1.0)
        oi_note = "比較基準待累積"
        if valid_number(prev_oi) and prev_oi > 0:
            oi_note = f"名目持倉變化 {(oi-prev_oi)/prev_oi:+.1%}（含價格與樣本變化，不能單獨判定買賣方向）"
        summary = f"{symbol} 覆蓋 {raw.get('contracts', 0)} 個合約，OI=${oi/1e9:,.2f}B；{oi_note}；{f_note}。"
        return Observation(source=self.name, symbol=symbol, signal_type="market_positioning",
                           direction=direction, magnitude=magnitude,
                           status="ok" if funding_ann is not None else "no_data",
                           summary=summary, entities=[("asset", symbol), ("metric", "open_interest")], raw=raw)
