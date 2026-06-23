"""回測引擎：用已落地的決策歷史，評估訊號方向的事後表現。

做法（簡化的單倉序列回測）：
  - 對每筆「非中性」決策，於決策當下價進場（偏多=做多、偏空=做空），
    持有 horizon_hours 後，以最接近到期時點的下一筆決策價出場。
  - signed_return = 後續報酬 × 方向；命中＝signed_return > 0。
  - 尚未到期的決策計為 pending（不納入統計）。

輸出（每幣＋整體）：
  hit_rate      方向命中率（非中性決策中）
  avg_return    平均單筆 signed_return
  trades        納入統計的筆數；pending 未到期筆數
  equity        累積損益曲線（(1+signed_return) 連乘），點為 {ts, equity}
  by_confidence 依信心度分層（低/中/高）的命中率與筆數，看「高信心是否更準」
"""
from __future__ import annotations

from datetime import datetime, timedelta

from .storage.decisions import DecisionStore

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


def _eval_symbol(rows: list[dict], horizon: timedelta) -> dict:
    rows = [r for r in rows if r.get("price") is not None]
    trades, pending = [], 0
    for i, d in enumerate(rows):
        sig = _sign(d["label"])
        if sig == 0:
            continue
        t0, p0 = _parse(d["ts"]), d["price"]
        if not p0:
            continue
        target = t0 + horizon
        exit_row = next((r for r in rows[i + 1:]
                         if _parse(r["ts"]) >= target and r.get("price")), None)
        if exit_row is None:                 # 尚未到期
            pending += 1
            continue
        fwd = (exit_row["price"] - p0) / p0
        signed = fwd * sig
        trades.append({
            "ts": d["ts"], "label": d["label"], "confidence": d["confidence"],
            "entry": p0, "exit": exit_row["price"],
            "fwd_return": round(fwd, 5), "signed_return": round(signed, 5),
            "hit": signed > 0,
        })
    return _summarize(trades, pending)


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


def backtest(store: DecisionStore, horizon_hours: float = 24.0,
             symbols: list[str] | None = None) -> dict:
    horizon = timedelta(hours=horizon_hours)
    syms = symbols or store.symbols()

    per_symbol = {s: _eval_symbol(store.series(s), horizon) for s in syms}

    # 整體：彙總所有幣的交易（依進場時間排序）後重算
    all_trades: list[dict] = []
    for s in syms:
        all_trades.extend(_eval_symbol(store.series(s), horizon)["trade_log"])
    all_trades.sort(key=lambda t: t["ts"])
    overall = _summarize(all_trades, sum(p["pending"] for p in per_symbol.values()))
    overall.pop("trade_log", None)
    for v in per_symbol.values():
        v.pop("trade_log", None)

    return {
        "horizon_hours": horizon_hours,
        "overall": overall,
        "per_symbol": per_symbol,
    }
