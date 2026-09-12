"""決策層：把各 agent 的 Observation 整合成每幣的綜合判斷。

輸出（每個 symbol）：
  score       -1~+1  加權淨偏向（負=空、正=多）
  label       強烈偏多 / 偏多 / 中性 / 偏空 / 強烈偏空 / 訊號分歧
  confidence  0~1    信心度＝訊號覆蓋率 × 方向一致度
  action      可讀的操作傾向建議
  reason      為什麼會得到這個結論（點名主導訊號）
  consensus   {bull, bear, neutral} 各方向的加權佔比
  signals     各 agent 的明細貢獻
  alerts      值得注意的劇烈變動（如長期持有者大幅增減）
"""
from __future__ import annotations

from .config import Config
from .storage.models import Observation

_SIGN = {"bull": 1.0, "bear": -1.0, "neutral": 0.0}
_DIR_ZH = {"bull": "偏多", "bear": "偏空", "neutral": "中性"}


def _label(score: float, conflict: bool) -> str:
    if conflict:
        return "訊號分歧"
    if score > 0.40:
        return "強烈偏多"
    if score > 0.15:
        return "偏多"
    if score < -0.40:
        return "強烈偏空"
    if score < -0.15:
        return "偏空"
    return "中性"


def _action(label: str, confidence: float) -> str:
    if label == "資料不足":
        return "資料不足，等待有效訊號"
    if label == "訊號分歧":
        return "訊號分歧，建議觀望、等待方向收斂"
    if label == "中性":
        return "方向不明，維持觀望"
    conf_word = "高信心" if confidence >= 0.6 else "中信心" if confidence >= 0.35 else "低信心"
    bias = "做多/加倉" if "多" in label else "減倉/防守"
    return f"{label}（{conf_word}）→ 傾向{bias}"


def aggregate(observations: list[Observation], config: Config) -> dict:
    weights = config.analyzers.weights
    total_weight = sum(weights.values()) or 1.0

    by_symbol: dict[str, list[Observation]] = {}
    for o in observations:
        by_symbol.setdefault(o.symbol, []).append(o)

    result: dict[str, dict] = {}
    for symbol, obs in by_symbol.items():
        score, wsum = 0.0, 0.0
        bull_w = bear_w = neutral_w = 0.0          # 各方向「權重×強度」累計
        contribs, alerts = [], []

        for o in obs:
            w = weights.get(o.source, 0.0) if getattr(o, "status", "ok") == "ok" else 0.0
            sign = _SIGN[o.direction]
            score += w * sign * o.magnitude
            wsum += w
            wm = w * o.magnitude
            if sign > 0:
                bull_w += wm
            elif sign < 0:
                bear_w += wm
            else:
                neutral_w += w                      # 中性以權重計入覆蓋
            contribs.append({
                "source": o.source,
                "direction": o.direction,
                "status": getattr(o, "status", "ok"),
                "weight": round(w, 3),
                "magnitude": round(o.magnitude, 3),
                "contribution": round(w * sign * o.magnitude, 4),
                "summary": o.summary,
            })
            # 劇烈變動提示（強訊號才提示，門檻 magnitude≥0.5）
            if w > 0 and o.direction != "neutral" and o.magnitude >= 0.5:
                alerts.append(f"{o.source}：{o.summary}")

        norm = score / wsum if wsum else 0.0        # -1 ~ +1

        # 信心度＝覆蓋率 × 方向一致度 × 表態力度
        #   覆蓋率 coverage：多少權重的訊號到位
        #   一致度 agreement：表態訊號中同向的佔比
        #   力度 conviction：有多少權重在「明確表態」(非中性)——避免一堆中性卻高信心
        coverage = wsum / total_weight
        directional = bull_w + bear_w
        agreement = (max(bull_w, bear_w) / directional) if directional else 0.0
        conviction = min(1.0, directional / (0.5 * total_weight))   # 半數權重表態即滿
        confidence = round(coverage * agreement * conviction, 3)

        # 衝突：多空兩方都有實質份量、且淨分數不大
        conflict = (
            bull_w > 0.05 and bear_w > 0.05
            and min(bull_w, bear_w) / max(bull_w, bear_w) > 0.6
            and abs(norm) < 0.15
        )
        label = _label(norm, conflict) if wsum else "資料不足"

        # 理由：點名貢獻最大的 1~2 個非中性訊號
        movers = sorted(
            (c for c in contribs if c["direction"] != "neutral" and c["weight"] > 0),
            key=lambda c: abs(c["contribution"]), reverse=True,
        )
        if movers:
            parts = [f"{m['source']}（{_DIR_ZH[m['direction']]}，權重{m['weight']}）"
                     for m in movers[:2]]
            reason = "主導訊號：" + "、".join(parts)
            if conflict:
                reason += "；但多空並存，淨方向不明確"
        else:
            reason = "目前各訊號皆中性或資料不足"

        result[symbol] = {
            "symbol": symbol,
            "score": round(norm, 3),
            "label": label,
            "confidence": confidence,
            "action": _action(label, confidence),
            "reason": reason,
            "consensus": {
                "bull": round(bull_w, 3),
                "bear": round(bear_w, 3),
                "neutral": round(neutral_w, 3),
            },
            "signals": contribs,
            "alerts": alerts,
        }
    return result
