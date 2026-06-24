"""量價背離 Agent：偵測頂背離 / 底背離，以及量價是否同步。

偵測邏輯為真實可用（非 mock）：
  - 底背離(bullish)：價格創更低低點，但 RSI 創更高低點 → 偏多
  - 頂背離(bearish)：價格創更高高點，但 RSI 創更低高點 → 偏空
  - 輔以成交量：越跌量縮 / 越漲量縮 視為動能衰竭，強化背離判讀
mock 模式只負責產生合成 OHLCV，指標與背離計算對真實資料一樣適用。
"""
from __future__ import annotations

import math
import random
import time

from .base import Agent
from ..clients.market_data import MarketDataClient
from ..storage.models import Observation


def rsi(closes: list[float], period: int = 14) -> list[float]:
    if len(closes) < period + 1:
        return []
    gains, losses = [], []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i - 1]
        gains.append(max(diff, 0.0))
        losses.append(max(-diff, 0.0))
    out: list[float] = []
    avg_g = sum(gains[:period]) / period
    avg_l = sum(losses[:period]) / period
    for i in range(period, len(gains) + 1):
        if i > period:
            avg_g = (avg_g * (period - 1) + gains[i - 1]) / period
            avg_l = (avg_l * (period - 1) + losses[i - 1]) / period
        rs = math.inf if avg_l == 0 else avg_g / avg_l
        out.append(100.0 if avg_l == 0 else 100 - 100 / (1 + rs))
    return out


def classify_divergence(closes: list[float], vols: list[float] | None = None):
    """從收盤(+成交量)判斷量價背離，回 (direction, magnitude, note)。
    底背離(價更低、RSI走高)=bull；頂背離(價更高、RSI走弱)=bear；否則 neutral。
    """
    direction, magnitude, note = "neutral", 0.0, "量價同步，無明顯背離"
    rsis = rsi(closes)
    if len(rsis) >= 30:
        seg_c = closes[-len(rsis):]
        half = len(rsis) // 2
        p_prev_low, p_now_low = min(seg_c[:half]), min(seg_c[half:])
        r_prev_low, r_now_low = min(rsis[:half]), min(rsis[half:])
        p_prev_high, p_now_high = max(seg_c[:half]), max(seg_c[half:])
        r_prev_high, r_now_high = max(rsis[:half]), max(rsis[half:])
        if p_now_low < p_prev_low and r_now_low > r_prev_low:
            direction = "bull"
            magnitude = min((r_now_low - r_prev_low) / 100 + 0.2, 1.0)
            note = "底背離：價格創更低低點但 RSI 走高，下跌動能衰竭"
        elif p_now_high > p_prev_high and r_now_high < r_prev_high:
            direction = "bear"
            magnitude = min((r_prev_high - r_now_high) / 100 + 0.2, 1.0)
            note = "頂背離：價格創更高高點但 RSI 走弱，上漲動能衰竭"
        if vols and direction != "neutral":
            v_prev = sum(vols[:half]) / half
            v_now = sum(vols[half:]) / (len(vols) - half)
            if v_now < v_prev:
                magnitude = min(magnitude + 0.1, 1.0)
                note += "；量能萎縮印證"
    return direction, magnitude, note


class DivergenceAgent(Agent):
    name = "divergence"

    def __init__(self, config):
        super().__init__(config)
        self._client: MarketDataClient | None = None

    def fetch(self, symbol: str) -> dict:
        cfg = self.config.agents.divergence
        if not self.config.use_mock:
            if self._client is None:
                self._client = MarketDataClient(exchange=cfg.exchange)
            return self._client.fetch_ohlcv(symbol, cfg.timeframe, limit=200)

        # 種子帶時間桶，讓 mock 價格隨輪次緩慢漂移（否則每輪同價、回測報酬恆為 0）
        rng = random.Random(f"{symbol}-div-{int(time.time() / 3)}")
        closes, vols = [], []
        price = 100.0
        for i in range(120):
            price *= 1 + rng.uniform(-0.03, 0.03)
            closes.append(price)
            vols.append(rng.uniform(0.5, 1.5) * 1000)
        return {"closes": closes, "volumes": vols}

    def analyze(self, symbol: str, raw: dict) -> Observation:
        closes = raw["closes"]
        vols = raw["volumes"]
        direction, magnitude, note = classify_divergence(closes, vols)
        summary = f"{symbol} 量價分析：{note}。"
        return Observation(
            source=self.name,
            symbol=symbol,
            signal_type="divergence",
            direction=direction,
            magnitude=magnitude,
            summary=summary,
            entities=[("asset", symbol), ("indicator", "RSI")],
            relations=[("RSI", f"shows_{direction}_divergence_on", symbol)]
            if direction != "neutral" else [],
            raw={"note": note, "price": closes[-1]},   # 決策當下價（供回測）
        )
