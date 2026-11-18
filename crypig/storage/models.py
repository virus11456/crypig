"""核心資料結構：Agent 產出的觀察（Observation）。

每個 Agent 把它的發現正規化成 Observation，再交給知識圖譜記憶層。
Observation 同時帶有：
  - 給「綜合評分」用的數值欄位（direction / magnitude）
  - 給「知識圖譜」用的結構欄位（entities / relations）
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# (主詞, 關係, 受詞) 三元組
Triple = tuple[str, str, str]


@dataclass
class Observation:
    source: str                       # 產出此觀察的 agent，例如 "smart_money"
    symbol: str                       # 標的，例如 "BTC"
    signal_type: str                  # 訊號種類，例如 "positioning" / "netflow" / "divergence"
    direction: str = "neutral"        # "bull" | "bear" | "neutral"
    magnitude: float = 0.0            # 0~1，訊號強度
    status: str = "ok"                # "ok" | "no_data"(無資料/不適用) | "warming"(蒐集中/待跨日)
    summary: str = ""                 # 人類可讀摘要（也餵給 RAG 做檢索）
    entities: list[tuple[str, str]] = field(default_factory=list)   # (type, name)
    relations: list[Triple] = field(default_factory=list)          # KG 三元組
    raw: dict[str, Any] = field(default_factory=dict)              # 原始資料
    ts: str = field(default_factory=_now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
