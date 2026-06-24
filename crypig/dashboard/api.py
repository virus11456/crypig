"""FastAPI 對外介面 + 可視化看板。

  GET  /                看板頁（HTML，顯示各幣決策卡片＋分數走勢）
  POST /cycle           手動觸發一輪採集+分析（回綜合評分，並落地決策）
  GET  /signal          回最近一輪綜合評分
  GET  /decisions       各幣最新決策（讀持久化表）
  GET  /decisions/history?symbol=BTC&limit=50   某幣決策歷史（畫走勢用）
  GET  /backtest?horizon_hours=24   回測：方向命中率 + 損益曲線
  POST /ask             關聯性問答（知識圖譜遞迴檢索+多跳）
  GET  /kg/stats        知識圖譜現況
"""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from ..orchestrator import Orchestrator
from ..backtest import backtest, OHLCVPriceHistory
from ..clients.market_data import MarketDataClient
from .page import INDEX_HTML

logger = logging.getLogger(__name__)
_orc: Orchestrator | None = None
_last: dict | None = None
_sched = None


def orchestrator() -> Orchestrator:
    global _orc
    if _orc is None:
        _orc = Orchestrator()
    return _orc


def _safe_cycle() -> None:
    try:
        orchestrator().run_cycle()
    except Exception:                       # 單輪失敗（如真實 API 限流）不可拖垮排程
        logger.exception("背景排程跑一輪失敗")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """部署時的背景排程：每隔 CRYPIG_INTERVAL_MIN 分鐘自動跑一輪，
    讓看板與回測持續累積資料。設 CRYPIG_SCHEDULER=0 可關閉。"""
    global _sched
    if os.getenv("CRYPIG_SCHEDULER", "1").lower() not in ("0", "false", "no", ""):
        from apscheduler.schedulers.background import BackgroundScheduler
        interval = float(os.getenv("CRYPIG_INTERVAL_MIN", "15"))
        _safe_cycle()                        # 啟動先跑一次，畫面立刻有資料
        _sched = BackgroundScheduler(daemon=True)
        _sched.add_job(_safe_cycle, "interval", minutes=interval)
        _sched.start()
        logger.info("背景排程啟動，每 %s 分鐘跑一輪", interval)
    yield
    if _sched:
        _sched.shutdown(wait=False)


app = FastAPI(title="Crypig", version="0.1.0", lifespan=lifespan)


class AskBody(BaseModel):
    question: str


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return INDEX_HTML


@app.post("/cycle")
def run_cycle() -> dict:
    global _last
    _last = orchestrator().run_cycle()
    return _last


@app.get("/signal")
def signal() -> dict:
    global _last
    if _last is None:
        _last = orchestrator().run_cycle()
    return _last["signals"]


@app.get("/decisions")
def decisions() -> dict:
    """各幣最新決策。表為空（尚未跑過）時先跑一輪。"""
    orc = orchestrator()
    rows = orc.decisions.latest()
    if not rows:
        orc.run_cycle()
        rows = orc.decisions.latest()
    return {"decisions": rows}


@app.get("/decisions/history")
def decisions_history(symbol: str = "BTC", limit: int = 50) -> dict:
    return {"symbol": symbol,
            "history": orchestrator().decisions.history(symbol, limit)}


@app.get("/backtest")
def backtest_report(horizon_hours: float | None = None,
                    price_source: str | None = None) -> dict:
    """回測：方向命中率 + 損益曲線。

    price_source：
      decisions  用決策表落地價（需系統跑滿一個 horizon 才有出場價）
      ohlcv      用交易所真實 K 線歷史依決策時間對齊（免等，可立刻回測）
    預設：mock 模式用 decisions、真實模式用 ohlcv；可用查詢參數覆寫。
    """
    orc = orchestrator()
    h = orc.config.backtest_horizon_hours if horizon_hours is None else horizon_hours
    src = price_source or ("decisions" if orc.config.use_mock else "ohlcv")
    price_fn = None
    if src == "ohlcv":
        dv = orc.config.agents.divergence
        price_fn = OHLCVPriceHistory(
            MarketDataClient(exchange=dv.exchange), timeframe=dv.timeframe)
    return backtest(orc.decisions, horizon_hours=h, price_fn=price_fn)


_market: MarketDataClient | None = None
_hl = None


def market() -> MarketDataClient:
    global _market
    if _market is None:
        _market = MarketDataClient()
    return _market


def hl():
    global _hl
    if _hl is None:
        from ..clients.hyperliquid import HyperliquidClient
        _hl = HyperliquidClient()
    return _hl


def _mock_hl_scan() -> list[dict]:
    import math
    import time
    t = time.time() / 3600
    from ..clients.hyperliquid import funding_flag
    # (symbol, price, 基準費率, 市值)
    seed = [("BTC", 64000, 0.08, 1.26e12), ("ETH", 3400, 0.30, 4.0e11),
            ("SOL", 150, 0.62, 7.0e10), ("DOGE", 0.16, -0.12, 2.3e10),
            ("HYPE", 28, 1.4, 9.0e9), ("PEPE", 1e-5, -0.6, 4.0e9),
            ("WIF", 2.3, 0.9, 2.3e9), ("LINK", 18, 0.04, 1.1e10),
            ("AVAX", 38, -0.2, 1.5e10), ("APT", 9, 0.5, 5.0e9),
            ("ARB", 1.1, -0.08, 3.0e9), ("TIA", 6.5, 0.18, 1.2e9)]
    out = []
    for i, (s, px, fr, cap) in enumerate(seed):
        ann = fr * (1 + 0.3 * math.sin(t + i))
        oi = 5e8 / (i + 1)
        vol = cap * 0.05 * (1 + 0.2 * math.sin(t + i))
        out.append({"symbol": s, "price": px, "funding_ann": ann,
                    "open_interest_usd": oi, "premium": ann / 50,
                    "funding_flag": funding_flag(ann),
                    "market_cap": cap, "volume_24h": vol,
                    "oi_cap": oi / cap, "vol_cap": vol / cap})
    out.sort(key=lambda r: abs(r["funding_ann"]), reverse=True)
    return out


def _mock_macro(syms: list[str]) -> dict:
    import math
    import time
    t = time.time() / 3600
    cap = 2.2e12 * (1 + 0.02 * math.sin(t))
    vol = 7.0e10 * (1 + 0.10 * math.sin(t * 1.3))
    oi = 1.5e11 * (1 + 0.05 * math.cos(t))
    g = {"market_cap": cap, "volume_24h": vol, "open_interest": oi,
         "oi_cap": oi / cap, "vol_cap": vol / cap,
         "btc_dominance": 54.0 + 2 * math.sin(t)}
    # (市值, 量, OI, 基準年化資金費率) — SOL 給個過熱、ETH 偏擁擠示意
    base = {"BTC": (1.30e12, 3.0e10, 3.1e10, 0.08),
            "ETH": (4.0e11, 1.5e10, 1.2e10, 0.30),
            "SOL": (7.0e10, 4.0e9, 6.0e9, 0.62)}

    def flag(a):
        return "hot" if a > 0.50 else "warm" if a > 0.25 else "squeeze" if a < -0.05 else "normal"
    per: dict[str, dict] = {}
    for s in syms:
        c, v, o, fr = base.get(s, (5.0e10, 2.0e9, 1.0e9, 0.05))
        c *= 1 + 0.02 * math.sin(t); v *= 1 + 0.10 * math.sin(t * 1.7)
        o *= 1 + 0.05 * math.cos(t * 1.2); fr *= 1 + 0.3 * math.sin(t * 2.1)
        per[s] = {"market_cap": c, "volume_24h": v, "open_interest": o,
                  "oi_cap": o / c, "vol_cap": v / c,
                  "funding_ann": fr, "funding_flag": flag(fr)}
    return {"global": g, "per_symbol": per}


@app.get("/macro")
def macro() -> dict:
    """全市場宏觀 + 各幣 OI/Cap、Vol/Cap + HL 場內資金費率對照。mock 回合成值。"""
    orc = orchestrator()
    syms = orc.config.symbols
    if orc.config.use_mock:
        out = _mock_macro(syms)
        hlmap = {r["symbol"]: r for r in _mock_hl_scan()}
    else:
        m = market()
        try:
            out = {"global": m.global_macro(), "per_symbol": m.coin_macro(syms)}
        except Exception as e:
            out = {"error": str(e), "global": None, "per_symbol": {}}
        try:
            hlmap = {r["symbol"]: r for r in hl().funding_scan()}
        except Exception:
            hlmap = {}
    for s, v in (out.get("per_symbol") or {}).items():   # 併入 HL 場內資金費率對照
        h = hlmap.get(s)
        if h:
            v["hl_funding_ann"] = h["funding_ann"]
            v["hl_funding_flag"] = h["funding_flag"]
    return out


@app.get("/scores")
def scores() -> dict:
    """全市場各幣輕量決策（聰明錢持倉 + 資金費率擁擠）。表為空時先跑一輪。"""
    orc = orchestrator()
    if not orc.all_scores and not orc.config.use_mock:
        orc.run_cycle()
    return {"scores": orc.all_scores}


@app.get("/hl_market")
def hl_market() -> dict:
    """Hyperliquid 全市場（全部永續幣）資金費率掃描 + 跨平台補市值/OI-Cap/Vol-Cap。

    跨平台整合：HL（標記價、資金費率、溢價、OI 後備）＋ CoinGecko（市值、量、
    跨所聚合 OI）。OI 優先用跨所聚合、否則 HL；市值對得上的幣才有(同名取最大市值)。
    """
    if orchestrator().config.use_mock:
        coins = _mock_hl_scan()
        return {"count": len(coins), "coins": coins}
    try:
        coins = hl().funding_scan()
    except Exception as e:
        return {"error": str(e), "count": 0, "coins": []}
    m = market()
    try:
        tm = m.top_markets()
    except Exception:
        tm = {}
    try:
        deriv = m.aggregate_derivatives()
    except Exception:
        deriv = {}
    for c in coins:
        s = c["symbol"]
        info = tm.get(s)
        cap = info["market_cap"] if info else None
        vol = info["volume_24h"] if info else None
        c["market_cap"] = cap
        c["volume_24h"] = vol
        c["vol_cap"] = (vol / cap) if (cap and vol) else None
        agg = deriv.get(s)
        oi = agg["open_interest_usd"] if (agg and agg.get("open_interest_usd")) else c["open_interest_usd"]
        c["open_interest_usd"] = oi
        c["oi_cap"] = (oi / cap) if (cap and oi) else None
    return {"count": len(coins), "coins": coins}


@app.post("/ask")
def ask(body: AskBody) -> dict:
    return orchestrator().ask(body.question)


@app.get("/kg/stats")
def kg_stats() -> dict:
    return orchestrator().rag.stats()
