"""協調中台：跑所有 agent → 餵知識圖譜 → 算綜合評分。"""
from __future__ import annotations

from pathlib import Path
import logging
import copy
import threading
import time
from datetime import datetime, timezone

from .config import Config, get_config
from .agents import SmartMoneyAgent, WhaleAgent, DivergenceAgent, LTHAgent
from .clients.market_data import MarketDataClient
from .aggregate import aggregate
from .kg import SelfLearningRAG
from .storage.models import Observation
from .storage.decisions import DecisionStore
from .storage.pos_series import PosSeriesStore
from .storage.quotes import QuoteStore
from .storage.analysis import AnalysisStore, FIELDS

logger = logging.getLogger(__name__)


class Orchestrator:
    def __init__(self, config: Config | None = None):
        self.config = config or get_config()
        self.rag = SelfLearningRAG(self.config)
        self.decisions = DecisionStore(self.config.decisions_db)
        self.pos_series = PosSeriesStore(self.config.posseries_db)
        self.quotes = QuoteStore(Path(self.config.decisions_db).parent / "market_quotes.json")
        self.all_scores: dict[str, dict] = {}   # 全市場各幣輕量決策(聰明錢+資金費率)
        self.radar: dict = {}                   # 分歧雷達：群眾(情緒/費率) vs 大戶(聰明錢/鯨魚)
        self._prev_pos: dict[str, dict] = {}    # 上一輪各幣 聰明錢/鯨魚 淨多空(算20分鐘變化)
        self.trader_summary: dict = {}          # 前N名交易者多空人數/比例/槓桿(看決心)
        self.last_result: dict | None = None
        self._cycle_started_at = None
        self._cycle_finished_at = None
        self._cycle_duration = None
        self._cycle_failed = False
        self._cycle_steps = {}
        self._cycle_lock = threading.Lock()     # 避免並發跑輪(請求端各自觸發會互相覆蓋+打爆 HL)
        # 以下 CoinGecko 資料只在每輪(背景)抓一次並快取，請求端只讀不打 API（避免被封）
        self.macro: dict | None = None          # 全市場宏觀
        self.market_caps: dict[str, dict] = {}  # SYMBOL -> {market_cap, volume_24h}
        self.deriv_agg: dict[str, dict] = {}    # SYMBOL -> 跨所聚合 OI/funding
        self.social: dict[str, dict] = {}       # SYMBOL -> LunarCrush 社群情緒(需付費金鑰)
        self.fear_greed: dict = {}              # 全市場恐懼貪婪指數(免費 alternative.me)
        self.defi: dict = {}                    # DefiLlama 資金動向(TVL/穩定幣/各鏈，免費)
        self.reddit: dict = {}                  # Reddit 散戶討論熱度/情緒(公開 RSS，免憑證)
        self.hl_scan: list = []                 # HL 全市場資金費率掃描(背景每輪快取，扛瞬斷)
        self.news: dict = {}                    # 加密新聞分析(利多/利空＋影響幣，免費 RSS)
        self._md: MarketDataClient | None = None
        self._lc = None
        self._dl = None
        self._rd = None
        self._nc = None
        self.valuation_times = {}
        self.snapshot_decisions = []
        self._analysis_store = AnalysisStore(Path(self.config.decisions_db).parent / "analysis_snapshot.json", self.config)
        self._published = None
        self._analysis_restored = False
        self._analysis_persist_failed = False
        self._empty_state = {key: copy.deepcopy(getattr(self, key)) for key in FIELDS}
        saved = self._analysis_store.load()
        if saved:
            self._published = saved
            self._cycle_finished_at = saved["completed_at"]
            self._analysis_restored = True
            for key, value in saved["state"].items():
                setattr(self, key, copy.deepcopy(value))
        self.agents = []
        a = self.config.agents
        if a.smart_money.enabled:
            self.agents.append(SmartMoneyAgent(self.config))
        if a.whales.enabled:
            self.agents.append(WhaleAgent(self.config))
        if a.divergence.enabled:
            self.agents.append(DivergenceAgent(self.config))
        if a.lth.enabled:
            self.agents.append(LTHAgent(self.config))

    def run_cycle(self) -> dict:
        # 非重入：已有一輪在跑就直接回（請求端不再各自啟動並發輪→不互相覆蓋、不打爆 HL）
        if not self._cycle_lock.acquire(blocking=False):
            logger.info("已有一輪在跑，略過本次觸發")
            return {"skipped": True}
        started = time.monotonic()
        self._cycle_steps = {}
        self._cycle_started_at = datetime.now(timezone.utc).isoformat()
        try:
            for agent in self.agents:
                if isinstance(agent, SmartMoneyAgent):
                    agent.begin_cycle()
            result = self._run_cycle_locked()
            self.last_result = result
            self._cycle_finished_at = datetime.now(timezone.utc).isoformat()
            self.snapshot_decisions = self.decisions.latest()
            state = {key: copy.deepcopy(getattr(self, key)) for key in FIELDS}
            # Publish one pointer only after every computation has completed.
            saved = self._analysis_store.validate({"version": 1, "config": self._analysis_store.signature,
                         "completed_at": self._cycle_finished_at, "state": state})
            self._published = saved
            self._analysis_restored = False
            try:
                self._analysis_store.save(state, saved["completed_at"])
                self._analysis_persist_failed = False
            except (OSError, ValueError, TypeError):
                self._analysis_persist_failed = True
                logger.exception("Analysis snapshot persistence failed")
            self._cycle_failed = False
            return result
        except Exception:
            self._cycle_failed = True
            # A failed partial attempt must not become the next comparison baseline.
            for key, value in (self._published["state"] if self._published else self._empty_state).items():
                setattr(self, key, copy.deepcopy(value))
            raise
        finally:
            for agent in self.agents:
                if isinstance(agent, SmartMoneyAgent):
                    agent.end_cycle()
            self._cycle_duration = round(time.monotonic() - started, 3)
            self._cycle_lock.release()

    def dashboard_state(self):
        """Pin a completed generation for an entire API response, never the working state."""
        view = copy.copy(self)
        published = self._published
        for key, value in (published["state"] if published else self._empty_state).items():
            setattr(view, key, value)
        view.cycle_status = self.cycle_status
        return view

    def cycle_status(self) -> dict:
        published = self._published
        completed = published["completed_at"] if published else None
        age = max(0, time.time()-datetime.fromisoformat(completed).timestamp()) if completed else None
        return {"quotes": self.quotes.read()[1],
                "refreshing": self._cycle_lock.locked(),
                "started_at": self._cycle_started_at,
                "last_success_at": completed,
                "analysis": {"completed_at": completed, "age_seconds": round(age, 1) if age is not None else None,
                             "stale": age is None or age > 2400,
                             "restored": self._analysis_restored,
                             "persist_failed": self._analysis_persist_failed},
                "duration_seconds": self._cycle_duration,
                "steps": dict(self._cycle_steps),
                "qualification": next((a.qualification_status() for a in self.agents
                                       if hasattr(a,"qualification_status")), None),
                "last_cycle_failed": self._cycle_failed,
                "note": "Cycle completion is not the upstream observation timestamp."}

    def _timed(self, name, fn, *args, **kwargs):
        """Wall-clock timing only: returning may include cached/partial upstream data."""
        started = time.monotonic()
        self._cycle_steps[name] = {"state": "running", "duration_seconds": None}
        state = "returned"
        try:
            return fn(*args, **kwargs)
        except Exception:
            state = "raised"
            raise
        finally:
            duration = round(time.monotonic() - started, 3)
            self._cycle_steps[name] = {"state": state, "duration_seconds": duration}
            logger.info("collection_step %s %s %.3fs", name, state, duration)

    def _run_cycle_locked(self) -> dict:
        observations: list[Observation] = []
        for agent in self.agents:
            obs = self._timed("agent." + agent.name, agent.run)
            logger.info("agent %s 產出 %d 筆觀察", agent.name, len(obs))
            observations.extend(obs)

        added = self.rag.ingest_many(observations)
        signals = aggregate(observations, self.config)
        prices = self._prices(observations)
        ts = datetime.now(timezone.utc).isoformat()
        saved = self.decisions.record_cycle(signals, ts, prices)
        self.all_scores = self._timed("scores", self._compute_all_scores)      # 全市場各幣輕量決策
        self._timed("position_history", self._record_positioning, ts)                       # 大戶持倉逐輪落地成時間軸
        self._refresh_market_data()                       # 背景抓一次 CoinGecko 並快取
        self.radar = self._divergence_radar()             # 群眾 vs 大戶 分歧雷達
        try:                                               # 背離逐輪落地成時間軸(看何時收斂=進場時機)
            self.pos_series.record_radar(ts, self.radar.get("market", {}))
        except Exception as e:
            logger.warning("雷達時間序列寫入失敗：%s", e)
        logger.info("知識圖譜新增 %d 條關係；決策落地 %d 筆；全市場評分 %d 幣；圖譜現況 %s",
                    added, saved, len(self.all_scores), self.rag.stats())
        return {"signals": signals, "kg": self.rag.stats(), "ingested": added,
                "decisions_saved": saved, "scored_coins": len(self.all_scores), "ts": ts}

    def _compute_all_scores(self) -> dict[str, dict]:
        """用每輪已抓回的整批資料（聰明錢全幣持倉 + 全幣資金費率擁擠）幫**所有幣**
        算 score/label/信心。不額外打 per-coin API。mock 模式略過。
        """
        if self.config.use_mock:
            return {}
        sm = next((a for a in self.agents if a.name == "smart_money"), None)
        if sm is None:
            return {}
        try:
            aggs = sm._coin_aggregates()                  # coin -> {long,short,count}（已快取）
        except Exception:
            logger.exception("全市場評分：聰明錢聚合失敗")
            return {}
        self.trader_summary = sm._trader_summary       # 多空人數/槓桿摘要
        cfg = self.config.agents.smart_money
        from .clients.hyperliquid import HyperliquidClient
        hlc = sm._client or HyperliquidClient()
        funding: dict[str, float] = {}
        try:
            scan = hlc.funding_scan()
            if scan:
                self.hl_scan = scan                    # 快取整份掃描，請求端 /hl_market 讀它(扛 HL 瞬斷)
            funding = {r["symbol"]: r["funding_ann"] for r in scan}
        except Exception:
            funding = {}

        coins = set(aggs) | set(funding)
        div = self._divergence_scan(hlc, sorted(coins))   # {coin: (direction,mag,note)}

        out: dict[str, dict] = {}
        new_pos: dict[str, dict] = {}
        for coin in coins:
            obs: list[Observation] = []
            agg = aggs.get(coin)
            if agg and agg["long"] + agg["short"] > 0:    # 聰明錢持倉訊號
                obs.append(sm.analyze(coin, {
                    "threshold_usd": cfg.pnl_threshold_usd, "window": cfg.window,
                    "trader_count": sm._trader_count, "position_count": agg["count"],
                    "long_notional_usd": agg["long"], "short_notional_usd": agg["short"]}))
            fa = funding.get(coin)
            if fa is not None:                            # 資金費率擁擠（反向）訊號
                if fa > 0.25:
                    fdir, fmag = "bear", min(abs(fa) + 0.2, 1.0)
                elif fa < -0.05:
                    fdir, fmag = "bull", min(abs(fa) + 0.2, 1.0)
                else:
                    fdir, fmag = "neutral", 0.1
                obs.append(Observation(
                    source="whale_flow", symbol=coin, signal_type="funding",
                    direction=fdir, magnitude=fmag,
                    summary=f"{coin} 資金費率年化 {fa*100:+.1f}%"))
            ddir, dmag, dnote = div.get(coin, (None, 0.0, ""))
            if ddir in ("bull", "bear"):                         # 日線量價背離訊號
                obs.append(Observation(
                    source="divergence", symbol=coin, signal_type="divergence",
                    direction=ddir, magnitude=dmag, summary=dnote))
            # 聰明錢 / 鯨魚 淨多空 + 與上一輪(約20分鐘)的變化
            sm_net = whale_net = None
            if agg:
                tot = agg["long"] + agg["short"]
                if tot > 0:
                    sm_net = (agg["long"] - agg["short"]) / tot
                wtot = agg.get("whale_long", 0) + agg.get("whale_short", 0)
                if wtot > 0:
                    whale_net = (agg["whale_long"] - agg["whale_short"]) / wtot
            prev = self._prev_pos.get(coin, {})
            entry = {}
            if sm_net is not None:
                entry["sm_net"] = round(sm_net, 4)
                if "sm_net" in prev:
                    entry["sm_delta"] = round(sm_net - prev["sm_net"], 4)
            if whale_net is not None:
                entry["whale_net"] = round(whale_net, 4)
                entry["whale_count"] = agg.get("whale_count", 0)
                if "whale_net" in prev:
                    entry["whale_delta"] = round(whale_net - prev["whale_net"], 4)
            new_pos[coin] = {k: entry[k] for k in ("sm_net", "whale_net") if k in entry}

            if obs:
                r = aggregate(obs, self.config).get(coin)
                if r:
                    entry.update({"score": r["score"], "label": r["label"],
                                  "confidence": r["confidence"], "divergence": ddir})
            if fa is not None:
                entry["funding_ann"] = round(fa, 4)
            if entry:
                out[coin] = entry
        self._prev_pos = new_pos
        return out

    def _record_positioning(self, ts: str) -> None:
        """把鯨魚(淨值前N)/聰明錢對主要幣的合約多空名目落地一筆，逐輪累積成時間軸。

        Hyperliquid 無持倉歷史，靠我們每輪記一筆往前長。鯨魚=淨值前N(錢很多的人)，
        記其 BTC 等主要幣的合約淨持倉，看大戶部位隨時間翻轉/加減碼=進場時機。
        """
        sm = next((a for a in self.agents if isinstance(a, SmartMoneyAgent)), None)
        if sm is None:
            return
        try:
            agg = sm._coin_aggregates()            # 本輪已算，走 90s 快取不重打
        except Exception as e:
            logger.warning("持倉時間序列：取聚合失敗 %s", e)
            return
        # 逐幣驗證需要更多幣的歷史：固定主要幣 + 本輪聰明錢名目最大的前 40 幣
        # （冷門幣訊號雜訊大故只取活躍前段；sqlite 寫入便宜，可長期累積）
        core = set(self.config.symbols) | {"BTC", "ETH", "SOL", "HYPE"}
        ranked = sorted(agg.items(),
                        key=lambda kv: (kv[1].get("long", 0.0) + kv[1].get("short", 0.0)),
                        reverse=True)
        targets = core | {sym for sym, _ in ranked[:40]}
        # 散戶端逐幣方向：資金費率→crowd(與雷達一致 clamp(fa/0.5)±1)，供逐幣背離驗證
        funding = {r["symbol"]: r.get("funding_ann") for r in (self.hl_scan or [])}
        for sym in targets:
            b = agg.get(sym)
            if not b:
                continue
            try:
                self.pos_series.record(ts, "whale", sym,
                                       b.get("whale_long", 0.0), b.get("whale_short", 0.0),
                                       int(b.get("whale_count", 0)))
                self.pos_series.record(ts, "smart", sym,
                                       b.get("long", 0.0), b.get("short", 0.0),
                                       int(b.get("count", 0)))
                fa = funding.get(sym)
                if fa is not None:
                    self.pos_series.record_crowd(ts, sym, max(-1.0, min(1.0, fa / 0.5)))
            except Exception as e:
                logger.warning("持倉時間序列：寫入 %s 失敗 %s", sym, e)

    def _divergence_radar(self) -> dict:
        """分歧雷達：群眾 vs 大戶反向 = alpha。

        群眾(各幣)：資金費率→市場擁擠方向(正費率=群眾做多/擁擠多單)。
        大戶(各幣)：聰明錢淨多空 sm_net。
        市場層級：恐懼貪婪(群眾) vs 聰明錢整體淨多空。
        反向且都有份量才算背離；依強度排序，列出 alpha 候選。
        """
        coins = []
        for sym, sc in (self.all_scores or {}).items():
            sm = sc.get("sm_net")
            fa = sc.get("funding_ann")
            if sm is None or fa is None:
                continue
            crowd = max(-1.0, min(1.0, fa / 0.5))         # 群眾(費率)多空
            if crowd > 0.1 and sm < -0.1:                 # 群眾做多 vs 聰明錢做空
                typ, bias, score = "頂部反指標", "看空", min(crowd, 1) + min(-sm, 1)
            elif crowd < -0.1 and sm > 0.1:               # 群眾做空 vs 聰明錢做多
                typ, bias, score = "底部機會", "看多", min(-crowd, 1) + min(sm, 1)
            else:
                continue
            coins.append({"symbol": sym, "crowd": round(crowd, 3), "smart": round(sm, 3),
                          "whale": sc.get("whale_net"), "funding_ann": fa,
                          "type": typ, "bias": bias, "score": round(score, 3)})
        coins.sort(key=lambda c: c["score"], reverse=True)

        # 市場層級：恐懼貪婪(群眾) vs 聰明錢整體
        sms = [s["sm_net"] for s in (self.all_scores or {}).values() if s.get("sm_net") is not None]
        smart_avg = sum(sms) / len(sms) if sms else None
        fg = self.fear_greed or {}
        from .clients.fear_greed import available
        fgv = fg.get("value") if available(fg) else None
        crowd_m = (fgv - 50) / 50 if fgv is not None else None   # 貪婪=+1群眾多 / 恐懼=-1群眾空
        gap = crowd_m - smart_avg if crowd_m is not None and smart_avg is not None else None                                # 群眾 vs 聰明錢 背離量(收斂趨 0=反轉接近)
        n_top = sum(1 for c in coins if c["type"] == "頂部反指標")
        n_bottom = sum(1 for c in coins if c["type"] == "底部機會")
        market = {"fear_greed": fgv, "fg_label": fg.get("label"),
                  "fg_percentile": fg.get("percentile"),
                  "smart_avg": round(smart_avg, 3) if smart_avg is not None else None, "crowd_m": round(crowd_m, 3) if crowd_m is not None else None,
                  "gap": round(gap, 3) if gap is not None else None, "n_div": len(coins), "n_top": n_top, "n_bottom": n_bottom,
                  "crowd_dir": "資料不足或更新異常" if crowd_m is None else "貪婪偏多" if crowd_m > 0.1 else "恐懼偏空" if crowd_m < -0.1 else "中性",
                  "smart_dir": "資料不足" if smart_avg is None else "偏多" if smart_avg > 0.05 else "偏空" if smart_avg < -0.05 else "中性"}
        if crowd_m is None or smart_avg is None:
            market["verdict"] = "資料不足或更新異常，暫不判定市場背離"
            market["diverging"] = None
        elif crowd_m > 0.1 and smart_avg < -0.05:
            market["verdict"] = "🔺 群眾貪婪、聰明錢做空 → 頂部反指標，偏空"
            market["diverging"] = True
        elif crowd_m < -0.1 and smart_avg > 0.05:
            market["verdict"] = "🔻 群眾恐懼、聰明錢做多 → 底部機會，偏多"
            market["diverging"] = True
        else:
            market["verdict"] = "未達市場背離門檻；情緒與合約部位不代表現貨買賣"
            market["diverging"] = False
        from .radar_presentation import describe_radar
        return describe_radar({"market": market, "coins": coins[:20]})

    def _refresh_market_data(self) -> None:
        """每輪(背景)抓一次 CoinGecko：全市場宏觀、各幣市值、跨所聚合 OI。
        全部快取在本物件，請求端只讀，CoinGecko 從『每次刷新都打』降到 20 分鐘 3 支。
        失敗時沿用上次快取（不清空）。"""
        if self.config.use_mock:
            return
        if self._md is None:
            self._md = MarketDataClient()
        for name, fn in (("deriv", lambda: self._md.aggregate_derivatives(ttl=0)),
                         ("macro", self._md.global_macro),
                         ("caps", self._md.top_markets)):
            try:
                val = self._timed("market." + name, fn)
                if name == "deriv" and val:
                    self.deriv_agg = val
                    self.valuation_times["aggregate_oi"] = self._md._deriv_ts
                elif name == "macro" and val:
                    self.macro = val
                elif name == "caps" and val:
                    self.market_caps = val
                    self.valuation_times["market_caps"] = self._md._top_ts
            except Exception:
                logger.warning("CoinGecko %s 抓取失敗，沿用上次快取", name)
        from .clients.fear_greed import snapshot as sentiment_snapshot
        self.fear_greed = self._timed("sentiment", sentiment_snapshot, self.fear_greed)
        # DefiLlama 資金動向（免費）
        try:
            if self._dl is None:
                from .clients.defillama import DefiLlamaClient
                self._dl = DefiLlamaClient()
            snap = self._timed("defillama", self._dl.snapshot, previous=self.defi)
            if snap:
                self.defi = snap
        except Exception:
            logger.warning("DefiLlama 抓取失敗")
        # Reddit 散戶討論熱度（公開 RSS，免 app 憑證）
        try:
            if self._rd is None:
                from .clients.reddit import RedditClient
                self._rd = RedditClient()
            buzz = self._timed("reddit", self._rd.crypto_buzz)
            if buzz:
                self.reddit = buzz
        except Exception:
            logger.warning("Reddit 討論熱度抓取失敗")
        # 加密新聞分析（免費 RSS，利多/利空＋影響幣）
        try:
            if self._nc is None:
                from .clients.news import NewsClient
                self._nc = NewsClient()
            nz = self._timed("news", self._nc.analyze)
            if nz and nz.get("total"):
                self.news = nz
        except Exception:
            logger.warning("新聞分析抓取失敗")
        # LunarCrush 社群情緒（需付費金鑰；有才抓）
        try:
            if self._lc is None:
                from .clients.lunarcrush import LunarCrushClient
                self._lc = LunarCrushClient()
            if self._lc.enabled:
                soc = self._timed("lunarcrush", self._lc.fetch_coins_sentiment)
                if soc:
                    self.social = soc
        except Exception:
            logger.warning("LunarCrush 社群情緒抓取失敗")

    def _divergence_scan(self, hlc, coins: list[str]) -> dict[str, tuple]:
        """並發抓日線、算每幣量價背離（direction, magnitude, note）。失敗回空。"""
        try:
            from .agents.divergence import classify_divergence
            bulk = hlc.daily_closes_bulk(coins)
            out: dict[str, tuple] = {}
            for coin, (closes, vols) in bulk.items():
                if len(closes) >= 31:
                    out[coin] = classify_divergence(closes, vols)
            return out
        except Exception:
            logger.exception("全市場背離掃描失敗")
            return {}

    @staticmethod
    def _prices(observations: list[Observation]) -> dict[str, float]:
        """取各幣決策當下價（divergence 觀察帶 price=OHLCV 收盤；real=OKX、mock=合成）。"""
        prices: dict[str, float] = {}
        for o in observations:
            if not isinstance(o.raw, dict):
                continue
            p = o.raw.get("price")
            if p is None and o.raw.get("closes"):
                p = o.raw["closes"][-1]
            if p is not None:
                prices[o.symbol] = float(p)
        return prices

    def ask(self, question: str) -> dict:
        return self.rag.ask(question)
