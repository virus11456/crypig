"""綜合評分：把各 agent 的 Observation 加權成單一偏多/偏空分數。"""
from __future__ import annotations

from .config import Config
from .storage.models import Observation

_SIGN = {"bull": 1.0, "bear": -1.0, "neutral": 0.0}


def aggregate(observations: list[Observation], config: Config) -> dict:
    weights = config.analyzers.weights
    by_symbol: dict[str, list[Observation]] = {}
    for o in observations:
        by_symbol.setdefault(o.symbol, []).append(o)

    result: dict[str, dict] = {}
    for symbol, obs in by_symbol.items():
        score, wsum = 0.0, 0.0
        contribs = []
        for o in obs:
            w = weights.get(o.source, 0.0)
            contribution = w * _SIGN[o.direction] * o.magnitude
            score += contribution
            wsum += w
            contribs.append({
                "source": o.source,
                "direction": o.direction,
                "magnitude": round(o.magnitude, 3),
                "summary": o.summary,
            })
        norm = score / wsum if wsum else 0.0   # -1 ~ +1
        label = "偏多" if norm > 0.15 else "偏空" if norm < -0.15 else "中性"
        result[symbol] = {
            "symbol": symbol,
            "score": round(norm, 3),
            "label": label,
            "signals": contribs,
        }
    return result
