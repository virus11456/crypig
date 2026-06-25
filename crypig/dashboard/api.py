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
    """全市場宏觀。讀每輪背景算好的快取（請求端不打 CoinGecko，避免被封）。"""
    orc = orchestrator()
    if orc.config.use_mock:
        return {"global": _mock_macro(orc.config.symbols)["global"]}
    if orc.macro is None:
        orc.run_cycle()
    return {"global": orc.macro}


@app.get("/positioning")
def positioning() -> dict:
    """前N名交易者多空人數/比例/槓桿（看決心）。mock 回合成。"""
    orc = orchestrator()
    if orc.config.use_mock:
        return {"smart": {"total": 100, "long": 38, "short": 22, "flat": 40,
                          "short_pct": 0.37, "long_pct": 0.63,
                          "lev_median": 3.2, "lev_avg": 3.5, "lev_max": 9.0},
                "whale": {"total": 30, "long": 11, "short": 8, "flat": 11,
                          "short_pct": 0.42, "long_pct": 0.58,
                          "lev_median": 2.8, "lev_avg": 3.0, "lev_max": 7.0}}
    if not orc.trader_summary:
        orc.run_cycle()
    return orc.trader_summary


@app.get("/whale_history")
def whale_history(symbol: str = "BTC", cohort: str = "whale", limit: int = 400) -> dict:
    """HL 巨鯨(淨值前N)對某幣的合約淨持倉時間序列——逐輪累積，看部位翻轉=進場時機。"""
    orc = orchestrator()
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
    if not series:
        # 第一輪還沒落地任何點：立即跑一輪把當下這筆寫進去（之後逐輪累積）
        try:
            if not orc.all_scores:
                orc.run_cycle()
            else:
                from datetime import datetime, timezone
                orc._record_positioning(datetime.now(timezone.utc).isoformat())
            series = orc.pos_series.history(cohort, symbol, limit=limit)
        except Exception as e:
            return {"symbol": symbol, "cohort": cohort, "error": str(e), "history": []}
    return {"symbol": symbol, "cohort": cohort, "history": series}


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
    radar = orc.radar or {}
    sa = (radar.get("market") or {}).get("smart_avg")
    if sa is not None:
        overall["sm_net_pct"] = f"{sa*100:+.0f}%"
    radar_conv = None
    try:
        rh = orc.pos_series.radar_history(limit=400)
        if len(rh) >= 4:
            k = min(5, len(rh) // 2)
            am = lambda a: (sum(abs(x["gap"] or 0) for x in a) / len(a)) if a else 0
            rA, pA = am(rh[-k:]), am(rh[-2 * k:-k])
            radar_conv = ("背離收斂中 → 群眾向聰明錢靠攏，接近反轉/進場時機" if rA < pA - 0.03
                          else "背離擴大中 → 分歧加劇，反轉時機未到" if rA > pA + 0.03
                          else "背離持平 → 僵持，等收斂訊號")
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

    orc = orchestrator()
    if not orc.all_scores and not orc.config.use_mock:
        orc.run_cycle()
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
    orc = orchestrator()
    if orc.config.use_mock:
        return {"market": {"fear_greed": 30, "fg_label": "Fear", "fg_percentile": 20,
                           "smart_avg": -0.3, "crowd_dir": "恐懼偏空", "smart_dir": "偏空",
                           "verdict": "群眾與聰明錢同向（恐懼偏空＋聰明錢偏空）→ 順勢偏空", "diverging": False},
                "coins": [{"symbol": "DEMO", "crowd": 0.6, "smart": -0.4, "whale": -0.3,
                           "funding_ann": 0.3, "type": "頂部反指標", "bias": "看空", "score": 1.0}]}
    if not orc.radar:
        orc.run_cycle()
    return orc.radar


@app.get("/radar_history")
def radar_history(limit: int = 400) -> dict:
    """市場背離時間軸：群眾 vs 聰明錢的背離量逐輪累積，趨 0=收斂=反轉接近。"""
    orc = orchestrator()
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
    if not h:
        try:
            if not orc.radar:
                orc.run_cycle()
            else:
                from datetime import datetime, timezone
                orc.pos_series.record_radar(datetime.now(timezone.utc).isoformat(),
                                            orc.radar.get("market", {}))
            h = orc.pos_series.radar_history(limit=limit)
        except Exception as e:
            return {"error": str(e), "history": []}
    return {"history": h}


@app.get("/social")
def social() -> dict:
    """社群/市場情緒：恐懼貪婪指數(免費) + LunarCrush 各幣情緒(需付費金鑰)。"""
    orc = orchestrator()
    if orc.config.use_mock:
        import math
        import time
        t = time.time() / 3600
        hist = [{"v": int(30 + 25 * math.sin(t + i / 3)), "t": 0} for i in range(30)]
        return {"fear_greed": {"value": hist[-1]["v"],
                               "label": "Fear" if hist[-1]["v"] < 45 else "Greed",
                               "history": hist},
                "lunarcrush_enabled": False, "social": {}}
    if not orc.fear_greed and not orc.social:
        orc.run_cycle()
    return {"fear_greed": orc.fear_greed,
            "lunarcrush_enabled": bool(orc.social), "social": orc.social}


@app.get("/reddit")
def reddit_buzz() -> dict:
    """Reddit 散戶討論熱度/情緒（取代推特；需 app 憑證）。"""
    orc = orchestrator()
    if orc.config.use_mock:
        return {"enabled": True, "total_posts": 200, "total_comments": 18000,
                "coins": {"BTC": {"mentions": 31, "score": 12000, "comments": 4200, "sentiment": 78.0},
                          "ETH": {"mentions": 18, "score": 5400, "comments": 2100, "sentiment": 71.0},
                          "SOL": {"mentions": 12, "score": 3300, "comments": 1500, "sentiment": 83.0},
                          "PEPE": {"mentions": 6, "score": 900, "comments": 600, "sentiment": 88.0}}}
    if not orc.reddit:
        orc.run_cycle()
    return {"enabled": bool(orc.reddit), **(orc.reddit or {})}


@app.get("/news")
def news() -> dict:
    """加密新聞分析：整體利多/利空、各幣新聞淨情緒、標題清單（含影響幣）。"""
    orc = orchestrator()
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
    if not orc.news:
        orc.run_cycle()
    return orc.news or {"total": 0, "summary": {}, "items": []}


@app.get("/defi")
def defi() -> dict:
    """DefiLlama 資金動向：DeFi 總 TVL、穩定幣總市值、各鏈 TVL（免費）。"""
    orc = orchestrator()
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
    if not orc.defi:
        orc.run_cycle()
    return orc.defi


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
    orc = orchestrator()
    if orc.config.use_mock:
        coins = _mock_hl_scan()
        return {"count": len(coins), "coins": coins}
    if not orc.hl_scan and not orc.all_scores:   # 首次：先跑一輪把掃描/市值快取算好
        orc.run_cycle()
    # 優先用背景每輪快取的掃描（扛 HL 瞬斷不讓整表變空）；真的沒有才即時打一次
    import copy
    coins = copy.deepcopy(orc.hl_scan) if orc.hl_scan else None
    if coins is None:
        try:
            coins = hl().funding_scan()
        except Exception as e:
            return {"error": str(e), "count": 0, "coins": []}
    tm = orc.market_caps                     # 讀每輪背景快取，不打 CoinGecko
    deriv = orc.deriv_agg
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
