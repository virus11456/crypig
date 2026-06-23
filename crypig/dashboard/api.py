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

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from ..orchestrator import Orchestrator
from ..backtest import backtest, OHLCVPriceHistory
from ..clients.market_data import MarketDataClient
from .page import INDEX_HTML

app = FastAPI(title="Crypig", version="0.1.0")
_orc: Orchestrator | None = None
_last: dict | None = None


def orchestrator() -> Orchestrator:
    global _orc
    if _orc is None:
        _orc = Orchestrator()
    return _orc


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


@app.post("/ask")
def ask(body: AskBody) -> dict:
    return orchestrator().ask(body.question)


@app.get("/kg/stats")
def kg_stats() -> dict:
    return orchestrator().rag.stats()
