"""訊號 → 前瞻報酬 驗證層。

把歷史訊號（散戶恐懼貪婪、大戶 vs 散戶雷達背離）對齊「未來價格報酬」，量化
「**訊號出現後 N 期價格實際怎麼走、勝率多少、期望報酬多少**」——這才是把「觀察到
背離」變成「能不能預判價格」的證明。

- 恐懼貪婪（alternative.me 2018 至今，日頻）：散戶情緒極端能否預判反轉（立即可算）
- 雷達背離 gap（每輪落地）：大戶 vs 散戶背離能否預判（隨累積變強）

price_series 皆為 [(epoch_ms, close)] 由舊到新。前瞻報酬只計「訊號時點與 t+H 都有價、
且 t+H 未超過最後一根 K 線」者（未到期的不算），避免前視偏誤。
"""
from __future__ import annotations

import bisect
import statistics
from datetime import datetime, timezone


def _price_at(series: list[tuple[int, float]], ts_ms: int) -> float | None:
    """≤ ts_ms 的最後一根收盤（找不到回 None）。"""
    if not series:
        return None
    times = [s[0] for s in series]
    if ts_ms < times[0]:
        return None
    i = bisect.bisect_right(times, ts_ms) - 1
    return series[i][1] if i >= 0 else None


def _forward_pairs(signals: list[tuple[int, float]],
                   series: list[tuple[int, float]],
                   horizon_ms: int) -> list[tuple[float, float]]:
    """回 [(訊號值, 前瞻報酬)]；t 與 t+H 都有價、且 t+H 未超過最後一根才計。"""
    if not series:
        return []
    last_t = series[-1][0]
    out: list[tuple[float, float]] = []
    for t, val in signals:
        if t + horizon_ms > last_t:      # 尚未到期：不算（避免前視）
            continue
        p0 = _price_at(series, t)
        p1 = _price_at(series, t + horizon_ms)
        if p0 and p1 and p0 > 0:
            out.append((val, (p1 - p0) / p0))
    return out


def _stats(rets: list[float]) -> dict:
    """一組前瞻報酬的統計：樣本數、勝率(>0)、平均、中位。"""
    n = len(rets)
    if not n:
        return {"n": 0, "win_rate": None, "mean": None, "median": None}
    wins = sum(1 for r in rets if r > 0)
    return {
        "n": n,
        "win_rate": round(wins / n * 100, 1),
        "mean": round(statistics.mean(rets) * 100, 2),       # %
        "median": round(statistics.median(rets) * 100, 2),   # %
    }


def _bucketize(pairs: list[tuple[float, float]],
               buckets: list[tuple[str, float, float]]) -> list[dict]:
    """pairs:[(值,報酬)]，buckets:[(標籤, lo, hi)] 半開 [lo,hi)。回每桶統計。"""
    out = []
    for label, lo, hi in buckets:
        rets = [r for v, r in pairs if lo <= v < hi]
        out.append({"bucket": label, "range": [lo, hi], **_stats(rets)})
    return out


# 恐懼貪婪分桶（0~100）：極端兩側是反指標候選
_FG_BUCKETS = [
    ("極度恐懼 <25", 0, 25),
    ("恐懼 25–45", 25, 45),
    ("中性 45–55", 45, 55),
    ("貪婪 55–75", 55, 75),
    ("極度貪婪 ≥75", 75, 101),
]


def fear_greed_study(fg_history: list[dict],
                     price_series: list[tuple[int, float]],
                     horizon_days: tuple[int, ...] = (7, 30)) -> dict:
    """散戶恐懼貪婪 → BTC 前瞻報酬。fg_history:[{'v':int,'t':unix秒(字串/數字)}]。"""
    signals: list[tuple[int, float]] = []
    for x in fg_history:
        try:
            t = int(str(x["t"])) * 1000     # 秒→毫秒
            signals.append((t, float(x["v"])))
        except (KeyError, ValueError, TypeError):
            continue
    horizons = {}
    for d in horizon_days:
        pairs = _forward_pairs(signals, price_series, d * 86400_000)
        horizons[f"{d}d"] = {
            "overall": _stats([r for _, r in pairs]),
            "buckets": _bucketize(pairs, _FG_BUCKETS),
        }
    return {"signal": "fear_greed", "asset": "BTC", "samples": len(signals),
            "horizons": horizons}


# 雷達背離 gap 分桶（gap = 群眾 - 聰明錢，正=群眾較多頭/聰明錢較空）
_GAP_BUCKETS = [
    ("群眾極多/聰明空 ≥0.5", 0.5, 9),
    ("背離偏正 0.15–0.5", 0.15, 0.5),
    ("接近一致 -0.15–0.15", -0.15, 0.15),
    ("背離偏負 -0.5–-0.15", -0.5, -0.15),
    ("群眾極空/聰明多 <-0.5", -9, -0.5),
]


def _iso_ms(s: str) -> int | None:
    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp() * 1000)
    except (ValueError, TypeError):
        return None


# 逐幣大戶持倉分桶（net = 該幣淨多空 -1..+1）
_POS_BUCKETS = [
    ("大戶極多 ≥0.5", 0.5, 9),
    ("偏多 0.15–0.5", 0.15, 0.5),
    ("中性 -0.15–0.15", -0.15, 0.15),
    ("偏空 -0.5–-0.15", -0.5, -0.15),
    ("大戶極空 <-0.5", -9, -0.5),
]


def positioning_study(history_by_coin: dict[str, list[dict]],
                      price_by_coin: dict[str, list[tuple[int, float]]],
                      cohort: str = "smart",
                      horizon_hours: tuple[int, ...] = (24, 72)) -> dict:
    """逐幣『大戶(聰明錢/鯨魚)對該幣淨多空』→ 該幣前瞻報酬。

    history_by_coin: {coin: [{'ts':iso, 'net':float}]}（pos_series.history 輸出）。
    跨幣彙整（pool）成方向桶，回答「大戶淨多某幣時、該幣後續是否上漲」；另附逐幣統計。
    隨 pos_series 累積，樣本變多統計力變強。
    """
    # 預轉每幣訊號點 [(ts_ms, net)]
    sig_by_coin: dict[str, list[tuple[int, float]]] = {}
    for coin, rows in history_by_coin.items():
        pts = []
        for r in rows:
            t = _iso_ms(r.get("ts", ""))
            n = r.get("net")
            if t is not None and n is not None:
                pts.append((t, float(n)))
        if pts:
            sig_by_coin[coin] = pts

    horizons = {}
    for h in horizon_hours:
        pooled: list[tuple[float, float]] = []
        by_coin: dict[str, dict] = {}
        for coin, pts in sig_by_coin.items():
            series = price_by_coin.get(coin)
            if not series:
                continue
            pairs = _forward_pairs(pts, series, h * 3600_000)
            if pairs:
                pooled += pairs
                by_coin[coin] = _stats([r for _, r in pairs])
        horizons[f"{h}h"] = {
            "overall": _stats([r for _, r in pooled]),
            "buckets": _bucketize(pooled, _POS_BUCKETS),
            "by_coin": dict(sorted(by_coin.items(), key=lambda kv: -(kv[1]["n"] or 0))),
        }
    return {"signal": f"positioning_{cohort}", "cohort": cohort,
            "coins": len(sig_by_coin), "horizons": horizons}


def radar_study(radar_history: list[dict],
                price_series: list[tuple[int, float]],
                horizon_hours: tuple[int, ...] = (24, 72)) -> dict:
    """雷達背離 gap → BTC 前瞻報酬（大戶 vs 散戶背離能否預判）。隨累積變強。"""
    signals: list[tuple[int, float]] = []
    for r in radar_history:
        t = _iso_ms(r.get("ts", ""))
        g = r.get("gap")
        if t is not None and g is not None:
            signals.append((t, float(g)))
    horizons = {}
    for h in horizon_hours:
        pairs = _forward_pairs(signals, price_series, h * 3600_000)
        horizons[f"{h}h"] = {
            "overall": _stats([r for _, r in pairs]),
            "buckets": _bucketize(pairs, _GAP_BUCKETS),
        }
    return {"signal": "radar_gap", "asset": "BTC", "samples": len(signals),
            "horizons": horizons}
