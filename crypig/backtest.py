"""回測引擎：用已落地的決策歷史，評估訊號方向的事後表現。

做法（簡化的單倉序列回測）：
  - 對每筆「非中性」決策，於決策當下價進場（偏多=做多、偏空=做空），
    持有 horizon_hours 後出場，signed_return = 後續報酬 × 方向；命中＝>0。
  - 尚未到期 / 無價可對齊的決策計為 pending（不納入統計）。

出/進場價兩種來源：
  - 預設：用決策表內落地的價（需系統實際跑滿一個 horizon 才有出場價）。
  - price_fn：注入真實價歷史（OHLCVPriceHistory 從交易所拉 K 線），依
    決策時間直接查進/出場價，免等系統跑滿，可立刻回測既有決策。

輸出（每幣＋整體）：hit_rate / avg_return / total_return / equity 曲線 /
pending / by_confidence（低中高信心分層命中率）。
"""
from __future__ import annotations

import bisect
from datetime import datetime, timedelta
from typing import Callable

from .storage.decisions import DecisionStore

PriceFn = Callable[[str, datetime], "float | None"]


# label → 方向：偏多/強烈偏多=+1、偏空/強烈偏空=-1、中性/訊號分歧=0
def _sign(label: str) -> int:
    if "多" in label:
        return 1
    if "空" in label:
        return -1
    return 0


def _bucket(conf: float) -> str:
    return "high" if conf >= 0.6 else "mid" if conf >= 0.35 else "low"


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts)


class OHLCVPriceHistory:
    """真實價歷史 price_fn：從交易所 K 線查「某時點的價」（≤該時點的最後一根收盤）。

    末根之後超過一根 bar 寬 → 視為尚未發生（回 None → 該決策 pending）；
    早於最早 K 線 → 無資料（回 None → 跳過）。各 symbol K 線快取一次。
    """

    def __init__(self, client, timeframe: str = "1h", limit: int = 300):
        self._client = client
        self._tf = timeframe
        self._limit = limit
        self._cache: dict[str, list[tuple[int, float]]] = {}

    def _series(self, symbol: str) -> list[tuple[int, float]]:
        if symbol not in self._cache:
            try:
                self._cache[symbol] = self._client.fetch_candles(symbol, self._tf, self._limit)
            except Exception:
                self._cache[symbol] = []
        return self._cache[symbol]

    def __call__(self, symbol: str, dt: datetime) -> float | None:
        series = self._series(symbol)
        if not series:
            return None
        target = int(dt.timestamp() * 1000)
        ts = [s[0] for s in series]
        if target < ts[0]:
            return None
        i = bisect.bisect_right(ts, target) - 1
        if i < 0:
            return None
        if i == len(series) - 1 and len(series) >= 2:   # 超過末根+一根 bar → 未到期
            barw = ts[-1] - ts[-2]
            if target > ts[-1] + barw:
                return None
        return series[i][1]


def _summarize(trades: list[dict], pending: int) -> dict:
    n = len(trades)
    equity, cum = [], 1.0
    for t in trades:
        cum *= (1 + t["signed_return"])
        equity.append({"ts": t["ts"], "equity": round(cum, 5)})

    by_conf: dict[str, dict] = {}
    for b in ("low", "mid", "high"):
        sel = [t for t in trades if _bucket(t["confidence"]) == b]
        by_conf[b] = {
            "trades": len(sel),
            "hit_rate": round(sum(t["hit"] for t in sel) / len(sel), 4) if sel else None,
        }

    return {
        "trades": n,
        "pending": pending,
        "hit_rate": round(sum(t["hit"] for t in trades) / n, 4) if n else None,
        "avg_return": round(sum(t["signed_return"] for t in trades) / n, 5) if n else None,
        "total_return": round(cum - 1, 5) if n else None,
        "equity": equity,
        "by_confidence": by_conf,
        "trade_log": trades,
    }


def _trade(d: dict, sig: int, entry: float, exit_px: float) -> dict:
    fwd = (exit_px - entry) / entry
    signed = fwd * sig
    return {
        "ts": d["ts"], "label": d["label"], "confidence": d["confidence"],
        "entry": round(entry, 6), "exit": round(exit_px, 6),
        "fwd_return": round(fwd, 5), "signed_return": round(signed, 5),
        "hit": signed > 0,
    }


def _eval_stored(rows: list[dict], horizon: timedelta) -> dict:
    """出場價＝最接近到期的下一筆決策落地價。"""
    rows = [r for r in rows if r.get("price") is not None]
    trades, pending = [], 0
    for i, d in enumerate(rows):
        sig = _sign(d["label"])
        if sig == 0 or not d["price"]:
            continue
        target = _parse(d["ts"]) + horizon
        exit_row = next((r for r in rows[i + 1:]
                         if _parse(r["ts"]) >= target and r.get("price")), None)
        if exit_row is None:
            pending += 1
            continue
        trades.append(_trade(d, sig, d["price"], exit_row["price"]))
    return _summarize(trades, pending)


def _eval_priced(rows: list[dict], horizon: timedelta,
                 price_fn: PriceFn, symbol: str) -> dict:
    """進/出場價＝真實價歷史 price_fn 依決策時間查得。"""
    trades, pending = [], 0
    for d in rows:
        sig = _sign(d["label"])
        if sig == 0:
            continue
        t0 = _parse(d["ts"])
        entry = price_fn(symbol, t0)
        if entry is None or entry == 0:        # 進場時點無 K 線 → 跳過
            continue
        exit_px = price_fn(symbol, t0 + horizon)
        if exit_px is None:                     # 出場尚無資料 → 未到期
            pending += 1
            continue
        trades.append(_trade(d, sig, entry, exit_px))
    return _summarize(trades, pending)


def backtest(store: DecisionStore, horizon_hours: float = 24.0,
             symbols: list[str] | None = None,
             price_fn: PriceFn | None = None) -> dict:
    horizon = timedelta(hours=horizon_hours)
    syms = symbols or store.symbols()

    per_symbol: dict[str, dict] = {}
    for s in syms:
        rows = store.series(s)
        per_symbol[s] = (_eval_priced(rows, horizon, price_fn, s)
                         if price_fn else _eval_stored(rows, horizon))

    # 整體：彙整各幣交易（依進場時間排序）後重算
    all_trades: list[dict] = []
    for v in per_symbol.values():
        all_trades.extend(v["trade_log"])
    all_trades.sort(key=lambda t: t["ts"])
    overall = _summarize(all_trades, sum(v["pending"] for v in per_symbol.values()))

    overall.pop("trade_log", None)
    for v in per_symbol.values():
        v.pop("trade_log", None)

    return {
        "horizon_hours": horizon_hours,
        "price_source": "ohlcv" if price_fn else "decisions",
        "overall": overall,
        "per_symbol": per_symbol,
    }
