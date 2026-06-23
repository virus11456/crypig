"""FastAPI 對外介面。

  POST /cycle          手動觸發一輪採集+分析（回綜合評分）
  GET  /signal         回最近一輪綜合偏多/偏空評分
  POST /ask            關聯性問答（走知識圖譜遞迴檢索+多跳）
  GET  /kg/stats       知識圖譜現況
"""
from __future__ import annotations

from fastapi import FastAPI
from pydantic import BaseModel

from ..orchestrator import Orchestrator

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


@app.post("/ask")
def ask(body: AskBody) -> dict:
    return orchestrator().ask(body.question)


@app.get("/kg/stats")
def kg_stats() -> dict:
    return orchestrator().rag.stats()
