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

from pathlib import Path
from ..radar_presentation import describe_radar, convergence_note
import logging
import math
import secrets
import time
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query, Header
from fastapi.middleware.gzip import GZipMiddleware
from threading import Lock
from .cache import SnapshotCache
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel

from ..orchestrator import Orchestrator
from ..backtest import backtest, OHLCVPriceHistory
from ..clients.market_data import MarketDataClient
from .page import INDEX_HTML

logger = logging.getLogger(__name__)
_orc: Orchestrator | None = None
_last: dict | None = None
_sched = None
_orc_lock = Lock()
_history_cache = SnapshotCache(directory=Path(os.environ["CRYPIG_DATA_DIR"]) / "history_cache"
                               if os.getenv("CRYPIG_DATA_DIR") else None)


def orchestrator() -> Orchestrator:
    global _orc
    if _orc is None:
        with _orc_lock:
            if _orc is None:
                _orc = Orchestrator()
    return _orc


def dashboard_state():
    return orchestrator().dashboard_state()


def _safe_cycle() -> None:
    try:
        orchestrator().run_cycle()
    except Exception:                       # 單輪失敗（如真實 API 限流）不可拖垮排程
        logger.exception("背景排程跑一輪失敗")


def _safe_quotes() -> None:
    orc = orchestrator()
    if not orc.config.use_mock:
        orc.quotes.refresh()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """部署時的背景排程：每隔 CRYPIG_INTERVAL_MIN 分鐘自動跑一輪，
    讓看板與回測持續累積資料。設 CRYPIG_SCHEDULER=0 可關閉。"""
    global _sched
    if os.getenv("CRYPIG_SCHEDULER", "1").lower() not in ("0", "false", "no", ""):
        from apscheduler.schedulers.background import BackgroundScheduler
        from datetime import datetime, timedelta
        interval = float(os.getenv("CRYPIG_INTERVAL_MIN", "15"))
        warmup_delay = float(os.getenv("CRYPIG_WARMUP_DELAY", "30"))
        # 部署關鍵：lifespan 立刻 yield→app 秒綁 PORT、先閒置 warmup_delay 秒讓
        # Railway 首次就緒探測通過(SUCCESS)；之後首輪暖機才跑——此時暖機卡 GIL 約
        # 70s 已被 Railway 容忍(同 ef0c266 的週期輪)。同步暖機(接受連線前)或無延遲
        # 背景暖機都會讓首次探測逾時→SIGTERM→FAILED，故必須「先閒置再暖機」。
        _sched = BackgroundScheduler(daemon=True)
        _sched.add_job(_safe_cycle, id="warmup",
                       next_run_time=datetime.now() + timedelta(seconds=warmup_delay))
        _sched.add_job(_safe_cycle, "interval", minutes=interval, id="cycle")
        _sched.add_job(_safe_quotes, "interval", seconds=60, id="quotes",
                       next_run_time=datetime.now() + timedelta(seconds=5),
                       max_instances=1, coalesce=True)
        _sched.start()
        logger.info("背景排程啟動，每 %s 分鐘跑一輪（首輪延遲 %ss 暖機）", interval, warmup_delay)
    yield
    _history_cache.close()
    if _orc is not None:
        for agent in _orc.agents:
            if hasattr(agent, "qualification_status"):
                agent.close()
    if _sched:
        _sched.shutdown(wait=False)


app = FastAPI(title="Crypig", version="0.1.0", lifespan=lifespan)
app.add_middleware(GZipMiddleware, minimum_size=1000)


def require_snapshot(value):
    if value is None or value == {} or value == []:
        raise HTTPException(503, "資料尚未就緒，背景更新中", headers={"Retry-After": "30"})
    return value


@app.get("/data_status")
def data_status() -> dict:
    return orchestrator().cycle_status()


# PWA 靜態資源（圖示）—— 直接讀檔回傳，不依賴 StaticFiles/aiofiles，部署最穩
from pathlib import Path as _Path
from fastapi.responses import JSONResponse, Response
_STATIC = _Path(__file__).parent / "static"


@app.get("/static/{name}")
def static_asset(name: str) -> Response:
    f = _STATIC / name
    if not f.is_file() or "/" in name or ".." in name:
        return Response(status_code=404)
    media = "image/png" if name.endswith(".png") else "application/octet-stream"
    return Response(f.read_bytes(), media_type=media,
                    headers={"Cache-Control": "public, max-age=604800"})

_MANIFEST = {
    "name": "Crypig 量化交易分析中台",
    "short_name": "Crypig",
    "description": "個人加密量化分析中台：市場看板＋策略/Obsidian",
    "start_url": "/", "scope": "/", "display": "standalone",
    "orientation": "any", "background_color": "#0d1117", "theme_color": "#0d1117",
    "icons": [
        {"src": "/static/icon-192.png", "sizes": "192x192", "type": "image/png",
         "purpose": "any maskable"},
        {"src": "/static/icon-512.png", "sizes": "512x512", "type": "image/png",
         "purpose": "any maskable"},
    ],
}

_SW_JS = """
const C='crypig-v1';
const SHELL=['/','/static/icon-192.png','/static/icon-512.png','/manifest.webmanifest'];
self.addEventListener('install',e=>{e.waitUntil(caches.open(C).then(c=>c.addAll(SHELL)).then(()=>self.skipWaiting()));});
self.addEventListener('activate',e=>{e.waitUntil(caches.keys().then(ks=>Promise.all(ks.filter(k=>k!==C).map(k=>caches.delete(k)))).then(()=>self.clients.claim()));});
self.addEventListener('fetch',e=>{
  const req=e.request; if(req.method!=='GET') return;
  const url=new URL(req.url);
  if(req.mode==='navigate'){
    e.respondWith(fetch(req).then(r=>{const cp=r.clone();caches.open(C).then(c=>c.put('/',cp));return r;}).catch(()=>caches.match('/')));
    return;
  }
  if(url.pathname.startsWith('/static/')||url.pathname==='/manifest.webmanifest'){
    e.respondWith(caches.match(req).then(r=>r||fetch(req)));
  }
  // 其餘(API 即時資料)走網路、不快取
});
"""


@app.get("/manifest.webmanifest")
def manifest() -> JSONResponse:
    return JSONResponse(_MANIFEST, media_type="application/manifest+json")


@app.get("/sw.js")
def service_worker() -> Response:
    return Response(_SW_JS, media_type="application/javascript",
                    headers={"Cache-Control": "no-cache"})


class AskBody(BaseModel):
    question: str


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    # no-cache：瀏覽器每次重新驗證 HTML，部署即時生效、免手動清快取
    # (SW 導覽已 network-first；這層擋的是瀏覽器自身的 HTTP 啟發式快取)
    return HTMLResponse(INDEX_HTML, headers={"Cache-Control": "no-cache, must-revalidate"})


@app.post("/cycle")
def run_cycle(authorization: str | None = Header(default=None)) -> dict:
    token = os.getenv("CRYPIG_ADMIN_TOKEN")
    if not token:
        raise HTTPException(status_code=404, detail="Manual collection is disabled")
    if not authorization or not secrets.compare_digest(authorization.encode(), ("Bearer " + token).encode()):
        raise HTTPException(status_code=401, detail="Unauthorized")
    global _last
    _last = orchestrator().run_cycle()
    return _last


@app.get("/signal")
def signal() -> dict:
    return require_snapshot(dashboard_state().last_result).get("signals", {})


@app.get("/decisions")
def decisions() -> dict:
    """只讀已落地的最新決策；首次暖機回 503，不在請求內採集。"""
    orc = dashboard_state()
    rows = orc.snapshot_decisions
    return {"decisions": require_snapshot(rows)}


@app.get("/decisions/history")
def decisions_history(symbol: str = "BTC", limit: int = Query(50, ge=1, le=2000)) -> dict:
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
    orc = dashboard_state()
    h = orc.config.backtest_horizon_hours if horizon_hours is None else horizon_hours
    src = price_source or ("decisions" if orc.config.use_mock else "ohlcv")
    price_fn = None
    if src == "ohlcv":
        dv = orc.config.agents.divergence
        price_fn = OHLCVPriceHistory(
            MarketDataClient(exchange=dv.exchange), timeframe=dv.timeframe)
    return backtest(orc.decisions, horizon_hours=h, price_fn=price_fn)


_validate_cache: dict = {"ts": 0.0, "data": None}


@app.get("/validate")
def validate_signals() -> dict:
    """訊號→前瞻報酬驗證：散戶恐懼貪婪 / 大戶vs散戶雷達背離 能否預判 BTC 價格。

    恐懼貪婪有長歷史→立刻有結論；雷達 gap 隨每輪累積→樣本變多才漸有統計力。
    結果快取 30 分鐘（OKX K 線不必每次重抓）。
    """
    import time
    from ..validate import (fear_greed_study, radar_study, positioning_study,
                            momentum_study, divergence_study, consensus_study)
    orc = dashboard_state()
    cached = _validate_cache["data"]
    # 只把「F&G 已有資料」的結果當有效快取——避免暖機未抓到 F&G 時把空結果快取 30 分
    if (cached and time.time() - _validate_cache["ts"] < 1800
            and (cached.get("fear_greed") or {}).get("samples", 0) > 0):
        return cached
    md = market()
    try:
        daily = md.fetch_candles_history("BTC", "1d", 1100)   # 分頁抓回 ~3 年
    except Exception:
        daily = []
    try:
        hourly = md.fetch_candles("BTC", "1h", 300)
    except Exception:
        hourly = []
    fg_hist = (orc.fear_greed or {}).get("history") or []
    try:
        radar_hist = orc.pos_series.radar_history(limit=2000)
    except Exception:
        radar_hist = []

    # 逐幣大戶持倉驗證：取有歷史的幣(資料多→少)，上限 20 幣以控 OKX 請求數
    smart_hist: dict = {}
    whale_hist: dict = {}
    crowd_hist: dict = {}
    price_by_coin: dict = {}
    try:
        coins = orc.pos_series.symbols("smart", min_rows=3)[:20]
        for c in coins:
            try:
                price_by_coin[c] = md.fetch_candles(c, "1h", 300)
            except Exception:
                continue
            smart_hist[c] = orc.pos_series.history("smart", c, limit=2000)
            whale_hist[c] = orc.pos_series.history("whale", c, limit=2000)
            crowd_hist[c] = orc.pos_series.history("crowd", c, limit=2000)
    except Exception:
        pass

    out = {
        "fear_greed": fear_greed_study(fg_hist, daily),
        "radar": radar_study(radar_hist, hourly),
        "divergence": divergence_study(smart_hist, crowd_hist, price_by_coin),
        "consensus": consensus_study(crowd_hist, price_by_coin),
        "pos_smart": positioning_study(smart_hist, price_by_coin, cohort="smart"),
        "pos_whale": positioning_study(whale_hist, price_by_coin, cohort="whale"),
        "mom_smart": momentum_study(smart_hist, price_by_coin, cohort="smart"),
        "mom_whale": momentum_study(whale_hist, price_by_coin, cohort="whale"),
        "price_window": {"daily_bars": len(daily), "hourly_bars": len(hourly),
                         "per_coin": len(price_by_coin)},
    }
    _validate_cache.update(ts=time.time(), data=out)
    return out


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
    """全市場宏觀。讀每輪背景算好的快取（請求端不打 CoinGecko，避免被封）。"""
    orc = dashboard_state()
    if orc.config.use_mock:
        return {"global": _mock_macro(orc.config.symbols)["global"]}
    return {"global": require_snapshot(orc.macro)}


@app.get("/positioning")
def positioning() -> dict:
    """前N名交易者多空人數/比例/槓桿（看決心）。mock 回合成。"""
    orc = dashboard_state()
    if orc.config.use_mock:
        return {"overlap": 0,
                "smart": {"total": 48, "long": 18, "short": 12, "flat": 18,
                          "short_pct": 0.40, "long_pct": 0.60, "winrate_median": 76.0,
                          "lev_median": 3.2, "lev_avg": 3.5, "lev_max": 9.0},
                "whale": {"total": 100, "long": 22, "short": 18, "flat": 60,
                          "short_pct": 0.45, "long_pct": 0.55, "winrate_median": None,
                          "lev_median": 2.8, "lev_avg": 3.0, "lev_max": 7.0}}
    require_snapshot(orc.trader_summary)
    return {**orc.trader_summary, "qualification_check": orchestrator().cycle_status().get("qualification")}


@app.get("/whale_history")
def whale_history(symbol: str = "BTC", cohort: str = Query("whale", pattern="^(whale|smart)$"), limit: int = Query(400, ge=1, le=5000)) -> dict:
    """HL 巨鯨(淨值前N)對某幣的合約淨持倉時間序列——逐輪累積，看部位翻轉=進場時機。"""
    orc = dashboard_state()
    if orc.config.use_mock:
        import math
        from datetime import datetime, timedelta, timezone
        base = datetime.now(timezone.utc) - timedelta(minutes=20 * 40)
        out = []
        for i in range(40):
            lo = 6e6 + 1.5e6 * math.sin(i / 6)
            sh = 4e6 + 1e6 * math.cos(i / 5)
            out.append({"ts": (base + timedelta(minutes=20 * i)).isoformat(),
                        "long_usd": lo, "short_usd": sh,
                        "net_usd": lo - sh, "net": (lo - sh) / (lo + sh), "count": 12})
        return {"symbol": symbol, "cohort": cohort, "history": out}
    series = orc.pos_series.history(cohort, symbol, limit=limit)
    return {"symbol": symbol, "cohort": cohort, "history": series}


_btcdata = None
_defi_hist = None


def _load_stablecoins() -> dict:
    """穩定幣總供應完整歷史（DefiLlama，2017 至今日頻）——場邊乾火藥/資金進出的宏觀訊號。

    增發＝新錢進場（結構性偏多）、縮減＝贖回撤離（偏空）。client 自帶 6 小時快取。
    """
    global _defi_hist
    if orchestrator().config.use_mock:
        import math
        from datetime import datetime, timedelta
        base = datetime(2020, 1, 1)
        out = [{"t": int((base + timedelta(days=i)).timestamp()),
                "v": round(5e9 + i * 1.5e8 + 2e10 * math.sin(i / 200))} for i in range(0, 2200, 2)]
        return {"history": out}
    try:
        if _defi_hist is None:
            from ..clients.defillama import DefiLlamaClient
            _defi_hist = DefiLlamaClient()
        hist = _defi_hist.stablecoin_history(ttl=0)
    except Exception as e:
        return {"history": [], "error": str(e)}
    return {"history": hist}


def _load_onchain_whale() -> dict:
    """BTC-denominated address cohorts; separate from LTH and derivatives."""
    global _btcdata
    from ..clients.btc_cohorts import fetch_cohorts, build_cohorts
    if orchestrator().config.use_mock:
        from datetime import date, timedelta
        days = [(date.today()-timedelta(days=31-i)).isoformat() for i in range(32)]
        data = build_cohorts([{d:4200000-i*100 for i,d in enumerate(days)},
                              {d:3000000+i*150 for i,d in enumerate(days)}])
        data['note'] = '示範資料，非真實鏈上資料。'
        return data
    if _btcdata is None:
        from ..clients.bitcoin_data import BitcoinDataClient
        _btcdata = BitcoinDataClient()
    return fetch_cohorts(_btcdata)


def history_response(key, loader):
    if orchestrator().config.use_mock:
        return loader()
    data, meta = _history_cache.read(key, loader, ttl=21600)
    return {**require_snapshot(data), "meta": meta}


@app.get("/stablecoins")
def stablecoins() -> dict:
    return history_response("stablecoins", _load_stablecoins)


def _load_lth_history() -> dict:
    from ..clients.lth_history import build_lth, SLUG
    if orchestrator().config.use_mock:
        from datetime import date, timedelta
        data = build_lth([{"d":(date.today()-timedelta(days=31-i)).isoformat(),
                           "longTermHodlerSupplyBtc":16000000+i*100} for i in range(32)])
        data["note"] = "示範資料，非真實鏈上資料。" + data["note"]
        return data
    from ..clients.bitcoin_data import BitcoinDataClient
    client = BitcoinDataClient()
    try:
        return build_lth(client.fetch_history(SLUG, ttl=0))
    finally:
        client.close()


@app.get("/lth_history")
def lth_history() -> dict:
    return history_response("lth_daily_supply_v1", _load_lth_history)


@app.get("/onchain_whale")
def onchain_whale() -> dict:
    return history_response("onchain_btc_cohorts_v1", _load_onchain_whale)


def _build_vault_data(orc) -> dict:
    """彙整匯出 Obsidian 所需資料：重點幣、大玩家決心、鯨魚鏈上變化。"""
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    try:
        hlmap = {r["symbol"]: r for r in hl().funding_scan()}
    except Exception:
        hlmap = {}
    caps, deriv = orc.market_caps, orc.deriv_agg
    coins = []
    for sym, sc in (orc.all_scores or {}).items():
        h = hlmap.get(sym, {})
        cap = (caps.get(sym) or {}).get("market_cap")
        oi = (deriv.get(sym) or {}).get("open_interest_usd") or h.get("open_interest_usd")
        coins.append({"symbol": sym, **sc, "funding_ann": h.get("funding_ann"),
                      "oi_cap": (oi / cap) if (oi and cap) else None, "_oi": oi or 0})
    coins.sort(key=lambda c: c["_oi"], reverse=True)
    coins = coins[:40]

    overall = {}
    try:
        wh = orc.pos_series.history("whale", "BTC", limit=400)
        if len(wh) >= 2:
            first, last = wh[0]["net_usd"], wh[-1]["net_usd"]
            flip = "翻多" if first < 0 <= last else "翻空" if first >= 0 > last else None
            bias = "淨多" if last >= 0 else "淨空"
            note = f"BTC 巨鯨合約{bias} ${abs(last)/1e6:.1f}M（近 {len(wh)} 輪"
            note += f"，{flip}）" if flip else "）"
            overall["whale_chain"] = note
    except Exception:
        pass

    # 分歧雷達結論＋收斂判讀（寫進 Journal）
    radar = describe_radar(orc.radar)
    sa = (radar.get("market") or {}).get("smart_avg")
    if sa is not None:
        overall["sm_net_pct"] = f"{sa*100:+.0f}%"
    radar_conv = None
    try:
        rh = orc.pos_series.radar_history(limit=400)
        radar_conv = convergence_note(rh)
    except Exception:
        pass

    ts = orc.all_scores and now.isoformat(timespec="minutes") or now.isoformat(timespec="minutes")
    summ = orc.trader_summary or {}
    return {"coins": coins, "ts": ts, "date": now.strftime("%Y-%m-%d"),
            "smart_summary": summ.get("smart"), "whale_summary": summ.get("whale"),
            "overall": overall, "radar": radar, "radar_conv": radar_conv}


@app.get("/vault.zip")
def vault_zip():
    """把目前的知識庫打包成 Obsidian vault（.zip）下載：Coins/Journal/KOL。"""
    import io
    import tempfile
    import zipfile
    from pathlib import Path
    from ..obsidian import export_vault

    orc = dashboard_state()
    if not orc.config.use_mock:
        require_snapshot(orc.all_scores)
    data = _build_vault_data(orc)
    tmp = tempfile.mkdtemp()
    export_vault(data, tmp + "/CrypigVault")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for p in Path(tmp).rglob("*.md"):
            z.write(p, p.relative_to(tmp))
    buf.seek(0)
    return StreamingResponse(
        buf, media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=crypig-vault.zip"})


@app.get("/radar")
def radar() -> dict:
    """分歧雷達：群眾(情緒/費率) vs 大戶(聰明錢/鯨魚) 反向 = alpha。"""
    orc = dashboard_state()
    if orc.config.use_mock:
        return describe_radar({"market": {"crowd_m": -0.4, "fear_greed": 30, "fg_label": "Fear", "fg_percentile": 20,
                           "smart_avg": -0.3, "crowd_dir": "恐懼偏空", "smart_dir": "偏空",
                           "verdict": "群眾與聰明錢同向（恐懼偏空＋聰明錢偏空）→ 順勢偏空", "diverging": False},
                "coins": [{"symbol": "DEMO", "crowd": 0.6, "smart": -0.4, "whale": -0.3,
                           "funding_ann": 0.3, "type": "頂部反指標", "bias": "看空", "score": 1.0}]})
    require_snapshot(orc.radar)
    return describe_radar(orc.radar)


@app.get("/radar_history")
def radar_history(limit: int = Query(400, ge=1, le=5000)) -> dict:
    """市場背離時間軸：群眾 vs 聰明錢的背離量逐輪累積，趨 0=收斂=反轉接近。"""
    orc = dashboard_state()
    if orc.config.use_mock:
        import math
        from datetime import datetime, timedelta, timezone
        base = datetime.now(timezone.utc) - timedelta(minutes=20 * 40)
        h = []
        for i in range(40):
            gap = 0.6 * math.cos(i / 14) * (1 - i / 60)        # 背離漸收斂
            h.append({"ts": (base + timedelta(minutes=20 * i)).isoformat(),
                      "gap": round(gap, 3), "crowd_m": round(gap / 2, 3),
                      "smart_avg": round(-gap / 2, 3), "n_div": 20 - i // 3,
                      "n_top": max(0, 12 - i // 4), "n_bottom": i // 5,
                      "diverging": abs(gap) > 0.2})
        return {"history": h}
    h = orc.pos_series.radar_history(limit=limit)
    return {"history": h}


@app.get("/social")
def social() -> dict:
    """社群/市場情緒：恐懼貪婪指數(免費) + LunarCrush 各幣情緒(需付費金鑰)。"""
    orc = dashboard_state()
    if orc.config.use_mock:
        import math
        import time
        t = time.time() / 3600
        hist = [{"v": int(30 + 25 * math.sin(t + i / 3)), "t": 0} for i in range(30)]
        return {"fear_greed": {"value": hist[-1]["v"],
                               "label": "Fear" if hist[-1]["v"] < 45 else "Greed",
                               "history": hist},
                "lunarcrush_enabled": False, "social": {}}
    require_snapshot((orc.fear_greed if orc.fear_greed.get("value") is not None else None) or orc.social)
    return {"fear_greed": orc.fear_greed,
            "lunarcrush_enabled": bool(orc.social), "social": orc.social}


@app.get("/reddit")
def reddit_buzz() -> dict:
    """Reddit 散戶討論熱度/情緒（公開 RSS，免 app 憑證）。"""
    orc = dashboard_state()
    if orc.config.use_mock:
        return {"enabled": True, "total_posts": 200, "subs": 4, "source": "reddit_rss",
                "coins": {"BTC": {"mentions": 31, "bull": 9, "bear": 4, "net": 5, "sentiment": 69.0},
                          "ETH": {"mentions": 18, "bull": 5, "bear": 3, "net": 2, "sentiment": 62.0},
                          "SOL": {"mentions": 12, "bull": 6, "bear": 2, "net": 4, "sentiment": 75.0},
                          "PEPE": {"mentions": 6, "bull": 3, "bear": 1, "net": 2, "sentiment": 80.0}}}
    require_snapshot(orc.reddit)
    return {"enabled": bool(orc.reddit), **(orc.reddit or {})}


@app.get("/news")
def news() -> dict:
    """加密新聞分析：整體利多/利空、各幣新聞淨情緒、標題清單（含影響幣）。"""
    orc = dashboard_state()
    if orc.config.use_mock:
        return {"total": 5, "summary": {
            "bull": 2, "bear": 1, "neutral": 2, "net": 1, "bias": "中性", "sources": 6,
            "top_coins": [{"symbol": "BTC", "mentions": 3, "net": 1, "bull": 2, "bear": 1},
                          {"symbol": "ETH", "mentions": 2, "net": -1, "bull": 0, "bear": 1}]},
            "items": [
                {"title": "Bitcoin ETF sees record inflows as institutions accumulate",
                 "link": "#", "source": "Cointelegraph", "ts": None, "sentiment": "bull", "net": 2, "coins": ["BTC"]},
                {"title": "SEC lawsuit pressures altcoins amid market fear",
                 "link": "#", "source": "Decrypt", "ts": None, "sentiment": "bear", "net": -2, "coins": ["ETH"]}]}
    require_snapshot(orc.news)
    return orc.news or {"total": 0, "summary": {}, "items": []}


@app.get("/defi")
def defi() -> dict:
    """DefiLlama 資金動向：DeFi 總 TVL、穩定幣總市值、各鏈 TVL（免費）。"""
    orc = dashboard_state()
    if orc.config.use_mock:
        import math
        import time
        t = time.time() / 3600
        hist = [{"v": 70e9 + 8e9 * math.sin(t + i / 5)} for i in range(60)]
        return {"tvl": {"value": hist[-1]["v"], "chg_7d": -0.05, "chg_30d": -0.12, "history": hist},
                "stablecoin": {"value": 314e9, "chg_30d": -0.02,
                               "history": [{"v": 314e9 + 4e9 * math.sin(t + i / 6)} for i in range(60)]},
                "chains": [{"name": "Ethereum", "tvl": 37e9}, {"name": "Solana", "tvl": 4.7e9},
                           {"name": "BSC", "tvl": 5e9}, {"name": "Base", "tvl": 4.1e9}]}
    require_snapshot(any(orc.defi.get(key) for key in ("tvl", "chains", "stablecoin")) or None)
    return orc.defi


@app.get("/scores")
def scores() -> dict:
    """全市場各幣輕量決策（聰明錢持倉 + 資金費率擁擠）。只讀背景快取。"""
    orc = dashboard_state()
    if not orc.config.use_mock:
        require_snapshot(orc.all_scores)
    return {"scores": orc.all_scores}


@app.get("/hl_market")
def hl_market() -> dict:
    """Hyperliquid 全市場（全部永續幣）資金費率掃描 + 跨平台補市值/OI-Cap/Vol-Cap。

    跨平台整合：HL（標記價、資金費率、溢價、OI 後備）＋ CoinGecko（市值、量、
    跨所聚合 OI）。OI 優先用跨所聚合、否則 HL；市值優先採明確 ID，未指定 ID 的代號配對保留候選標記。
    """
    orc = dashboard_state()
    if orc.config.use_mock:
        coins = _mock_hl_scan()
        return {"count": len(coins), "coins": coins}
    snapshot, quote_meta = orc.quotes.read()
    coins = require_snapshot(snapshot)
    tm = orc.market_caps                     # 讀每輪背景快取，不打 CoinGecko
    deriv = orc.deriv_agg
    for c in coins:
        s = c["symbol"]
        info = tm.get(s)
        def price_matches(reference):
            price = c.get("price")
            return all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and v > 0
                       for v in (reference, price)) and abs(reference / price - 1) <= 0.2
        cap_matches = info is not None and price_matches(info.get("reference_price"))
        c["valuation_check"] = "price_consistent_candidate" if cap_matches else "missing_or_price_mismatch"
        if not cap_matches:
            info = None
        cap = info["market_cap"] if info else None
        vol = info["volume_24h"] if info else None
        c["market_cap"] = cap
        c["volume_24h"] = vol
        c["vol_cap"] = (vol / cap) if (cap and vol is not None) else None
        agg = deriv.get(s)
        if agg and not price_matches(agg.get("reference_price")):
            agg = None
        c["oi_contracts"] = agg.get("contracts") if agg else None
        c["oi_coverage"] = agg.get("coverage") if agg else "hyperliquid_only"
        oi = agg["open_interest_usd"] if (agg and agg.get("open_interest_usd")) else c["open_interest_usd"]
        c["hl_open_interest_usd"] = c["open_interest_usd"]
        c["open_interest_source"] = "coingecko_aggregated" if agg and agg.get("open_interest_usd") else "hyperliquid"
        c["market_cap_source"] = "coingecko" if info else None
        c["market_cap_match"] = info.get("match_method", "symbol_candidate") if info else None
        c["market_cap_asset_id"] = info.get("asset_id") if info else None
        c["market_cap_updated_at"] = info.get("source_updated_at") if info else None
        c["open_interest_usd"] = oi
        c["oi_cap"] = (oi / cap) if (cap and oi is not None) else None
    valuations = {}
    for name in ("market_caps", "aggregate_oi"):
        fetched = orc.valuation_times.get(name) or None
        age = max(0, time.time() - fetched) if fetched else None
        valuations[name] = {"fetched_at": fetched, "age_seconds": age,
                            "stale": age is None or age > 2400}
    return {"count": len(coins), "coins": coins, "meta": {**orc.cycle_status(), "quotes": quote_meta, "valuations": valuations}}


@app.post("/ask")
def ask(body: AskBody) -> dict:
    return orchestrator().ask(body.question)


@app.get("/kg/stats")
def kg_stats() -> dict:
    return orchestrator().rag.stats()
