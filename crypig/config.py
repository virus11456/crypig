"""設定載入。從 config.yaml 讀取，找不到時退回 config.example.yaml。"""
from __future__ import annotations

from pathlib import Path
from functools import lru_cache

import yaml
from pydantic import BaseModel, Field

_ROOT = Path(__file__).resolve().parent.parent


class SmartMoneyConfig(BaseModel):
    enabled: bool = True
    interval_minutes: int = 15
    pnl_threshold_usd: float = 1_000_000
    # Hyperliquid 無「一年」時間窗；allTime / month 為最接近代理
    window: str = "allTime"          # day | week | month | allTime
    max_traders: int = 100           # 取前 N 名合格交易者統計持倉


class WhalesConfig(BaseModel):
    enabled: bool = True
    interval_minutes: int = 30


class OHLCVConfig(BaseModel):
    enabled: bool = True
    interval_minutes: int = 5
    exchange: str = "okx"
    timeframe: str = "1h"


class LTHConfig(BaseModel):
    enabled: bool = True
    interval_minutes: int = 720      # 鏈上指標變化慢，半天一次即可
    threshold_days: int = 151        # 至少持有天數


class AgentsConfig(BaseModel):
    smart_money: SmartMoneyConfig = SmartMoneyConfig()
    whales: WhalesConfig = WhalesConfig()
    divergence: OHLCVConfig = OHLCVConfig()
    lth: LTHConfig = LTHConfig()


class LLMConfig(BaseModel):
    # provider: "mock" | "claude" | "openai"
    provider: str = "mock"
    model: str = "claude-opus-4-8"
    # 從環境變數讀金鑰名稱（避免把金鑰寫進設定檔）
    api_key_env: str = "ANTHROPIC_API_KEY"


class KGConfig(BaseModel):
    # backend: "networkx"(本地檔案) | "neo4j" | "rdflib"
    backend: str = "networkx"
    path: str = "kg_store.json"
    # 多跳推理時最大跳數
    max_hops: int = 3


class AnalyzersConfig(BaseModel):
    interval_minutes: int = 5
    weights: dict[str, float] = Field(
        default_factory=lambda: {
            "smart_money": 0.30,
            "whale_flow": 0.25,
            "divergence": 0.25,
            "lth_supply": 0.20,
        }
    )


class Config(BaseModel):
    use_mock: bool = True
    symbols: list[str] = Field(default_factory=lambda: ["BTC", "ETH", "SOL"])
    snapshot_db: str = "snapshots.db"
    agents: AgentsConfig = AgentsConfig()
    kg: KGConfig = KGConfig()
    llm: LLMConfig = LLMConfig()
    analyzers: AnalyzersConfig = AnalyzersConfig()


@lru_cache(maxsize=1)
def get_config() -> Config:
    for name in ("config.yaml", "config.example.yaml"):
        path = _ROOT / name
        if path.exists():
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            return Config.model_validate(data)
    return Config()
