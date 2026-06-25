"""設定載入。從 config.yaml 讀取，找不到時退回 config.example.yaml。"""
from __future__ import annotations

import os
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
    whale_top_n: int = 30            # 鯨魚＝全市場淨值前 N 名（錢很多的人，與獲利無關）
    whale_full_market: bool = True   # True=全市場淨值前N(獨立於聰明錢)；False=舊版(聰明錢內淨值前N)
    whale_av_cap_usd: float = 1_500_000_000  # 排除淨值超此的非個人帳號(HLP/做市金庫等)
    # 聰明錢＝近 N 筆平倉「勝率＋獲利」最佳者（需打 userFills 算，故用候選池+長快取）
    rank_by_fills: bool = True       # True=近期勝率/獲利選聰明錢；False=退回 allTime PnL 榜
    candidate_window: str = "month"  # 候選池用的時間窗（近期活躍賺錢者）
    candidate_pool: int = 150        # 候選池大小（只對這些人抓 fills；多數 PnL 榜是做市商）
    fills_lookback: int = 100        # 近 N 筆平倉算勝率/獲利
    fills_min_trades: int = 30       # 至少 N 筆平倉才納入（避免少量全勝假象）
    fills_min_span_hours: float = 24 # 近 N 筆需跨 ≥此時數（剔除幾小時內刷單的做市/高頻）
    fills_refresh_min: int = 360     # fills 重算間隔（分鐘）；持倉仍每輪更新


class WhalesConfig(BaseModel):
    enabled: bool = True
    interval_minutes: int = 30
    # 真實鯨魚錢包持倉：bitcoin-data wallet-bands（BTC 鏈上，免費源每小時限 10 次）
    onchain_symbol: str = "BTC"
    # 哪些級距算「鯨魚」：預設 ≥100 BTC 的大戶（駝背鯨+巨鯨）。
    # 可選欄位：whaleBtc(10-100)、humpbackBtc(100-1K)、megaWhaleBtc(≥1K)
    whale_bands: list[str] = Field(default_factory=lambda: ["humpbackBtc", "megaWhaleBtc"])
    chg_threshold: float = 0.003     # 鯨魚持倉變化超過此比例才算累積/分配


class OHLCVConfig(BaseModel):
    enabled: bool = True
    interval_minutes: int = 5
    exchange: str = "okx"
    timeframe: str = "1h"


class LTHConfig(BaseModel):
    enabled: bool = True
    interval_minutes: int = 720      # 鏈上指標變化慢，半天一次即可（免費源每小時限 10 次）
    threshold_days: int = 151        # 至少持有天數（業界標準指標約 155 天，相近）
    source: str = "bitcoin-data"     # 免費 BTC 鏈上源（已驗證可用）
    # 真正的長期持有者供給(BTC)：持有≥155天（業界標準，與要求的151天相近）
    metric_slug: str = "long-term-hodler-supply-btc"
    value_key: str = "longTermHodlerSupplyBtc"
    onchain_symbol: str = "BTC"      # 鏈上 LTH 為 BTC 指標


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
    decisions_db: str = "decisions.db"   # 決策層每輪輸出持久化
    posseries_db: str = "posseries.db"   # 大戶持倉時間序列(鯨魚/聰明錢逐輪累積)
    backtest_horizon_hours: float = 24.0  # 回測持有期（小時）
    agents: AgentsConfig = AgentsConfig()
    kg: KGConfig = KGConfig()
    llm: LLMConfig = LLMConfig()
    analyzers: AnalyzersConfig = AnalyzersConfig()


def _apply_env(cfg: Config) -> Config:
    """部署用環境變數覆寫（Railway 等）：
      USE_MOCK=false        切真實資料源
      CRYPIG_DATA_DIR=/data 把 sqlite/知識圖譜落到掛載的 volume 以持久化
    """
    if (v := os.getenv("USE_MOCK")) is not None:
        cfg.use_mock = v.lower() not in ("0", "false", "no", "")
    data_dir = os.getenv("CRYPIG_DATA_DIR")
    if data_dir:
        d = Path(data_dir)
        d.mkdir(parents=True, exist_ok=True)
        cfg.snapshot_db = str(d / Path(cfg.snapshot_db).name)
        cfg.decisions_db = str(d / Path(cfg.decisions_db).name)
        cfg.posseries_db = str(d / Path(cfg.posseries_db).name)
        cfg.kg.path = str(d / Path(cfg.kg.path).name)
    return cfg


@lru_cache(maxsize=1)
def get_config() -> Config:
    for name in ("config.yaml", "config.example.yaml"):
        path = _ROOT / name
        if path.exists():
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            return _apply_env(Config.model_validate(data))
    return _apply_env(Config())
