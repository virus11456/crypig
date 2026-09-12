"""聰明錢 Agent：近一年實現獲利超過門檻者的多空持倉。

真實資料源：Hyperliquid 公開 API
  1) leaderboard 篩出 pnl > 門檻 的交易者（取前 N 名）
  2) 逐一取其 clearinghouseState，統計各標的多/空名目價值
  3) 算淨多空比，產出 Observation
mock 版用合成資料，介面與正式版一致。

註：Hyperliquid 沒有「一年」時間窗，window 預設 allTime（最接近代理）。
"""
from __future__ import annotations

import logging
import random
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Lock

from .base import Agent
from ..clients.hyperliquid import HyperliquidClient
from ..storage.models import Observation

logger = logging.getLogger(__name__)


class SmartMoneyAgent(Agent):
    name = "smart_money"

    def __init__(self, config):
        super().__init__(config)
        self._client: HyperliquidClient | None = None
        # 每輪只統計一次，多個標的共用（避免重複打 API）
        self._agg: dict[str, dict] | None = None
        self._cycle_pinned = False
        self._agg_ts: float = 0.0
        self._trader_count: int = 0
        self._whale_count: int = 0
        self._trader_summary: dict = {}
        self._smart_sel: list[dict] | None = None   # 本輪取出的聰明錢(前 max_traders)
        self._smart_pool: dict | None = None         # 跨輪累積的合格帳號池(持久化)
        self._smart_offset: int = 0                  # 候選輪轉位移(每輪抓不同一段)
        self._qualification_lock = Lock()
        self._qualification_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="qualification")
        self._qualification_future = None
        self._qualification_state = {"refreshing": False, "last_attempt_at": None,
                                     "completed_at": None, "failed": False}
        self._selection_meta = {}
        self._store = None                           # PosSeriesStore(累積池持久化)

    @staticmethod
    def _summarize_traders(smart_accounts: list[dict], whale_accounts: list[dict]) -> dict:
        """Account direction and sample statistics; qualification subsets are independent."""
        import statistics

        def grp(accs):
            longs = [a for a in accs if a["net"] > 0]
            shorts = [a for a in accs if a["net"] < 0]
            flat = [a for a in accs if a["net"] == 0]
            levs = [a["lev"] for a in accs if a["lev"] > 0]
            wrs = [a["win_rate"] for a in accs if a.get("win_rate") is not None]
            directional = len(longs) + len(shorts)
            return {
                "total": len(accs), "long": len(longs), "short": len(shorts),
                "flat": len(flat),
                "no_positions": sum(a.get("pos") == [] for a in flat),
                "offset_positions": sum(bool(a.get("pos")) for a in flat),
                "flat_unknown": sum("pos" not in a or a["pos"] is None for a in flat),
                "short_pct": round(len(shorts) / directional, 4) if directional else None,
                "long_pct": round(len(longs) / directional, 4) if directional else None,
                "lev_median": round(statistics.median(levs), 2) if levs else None,
                "lev_avg": round(statistics.mean(levs), 2) if levs else None,
                "lev_max": round(max(levs), 2) if levs else None,
                "winrate_median": round(statistics.median(wrs) * 100, 1) if wrs else None,
                "winrate_accounts": len(wrs),
                "btc": {"accounts": sum(any(p[0] == "BTC" for p in a.get("pos", [])) for a in accs),
                        "long_usd": sum(p[2] for a in accs for p in a.get("pos", []) if p[0] == "BTC" and p[1] > 0),
                        "short_usd": sum(p[2] for a in accs for p in a.get("pos", []) if p[0] == "BTC" and p[1] < 0)},
            }
        return {"smart": grp(smart_accounts), "whale": grp(whale_accounts),
                "smart_verified": grp([a for a in smart_accounts if a.get("win_rate") is not None]),
                "smart_pnl_only": grp([a for a in smart_accounts if a.get("win_rate") is None])}

    def _pool_store(self):
        if self._store is None:
            from ..storage.pos_series import PosSeriesStore
            self._store = PosSeriesStore(self.config.posseries_db)
        return self._store

    def begin_cycle(self):
        self._agg = None
        self._cycle_pinned = True

    def end_cycle(self):
        self._cycle_pinned = False

    def qualification_status(self):
        with self._qualification_lock:
            return dict(self._qualification_state)

    def close(self):
        self._qualification_executor.shutdown(wait=False, cancel_futures=True)

    def _schedule_qualification(self, cfg):
        """One bounded worker; position collection never waits for fills."""
        if not getattr(cfg, "rank_by_fills", True):
            return
        with self._qualification_lock:
            now = time.time()
            state = self._qualification_state
            if state["refreshing"] or now-(state["last_attempt_at"] or 0) < 90:
                return
            self._qualification_state = {**state, "refreshing":True, "last_attempt_at":now}
            self._qualification_future = self._qualification_executor.submit(self._refresh_qualification, cfg)

    def _refresh_qualification(self, cfg):
        from ..storage.pos_series import PosSeriesStore
        started = time.monotonic()
        client = store = None
        try:
            # Separate connections prevent cache races and shared SQLite transactions.
            client = HyperliquidClient()
            store = PosSeriesStore(self.config.posseries_db)
            cands = list(dict.fromkeys(a for a,_ in client.top_traders(
                window=cfg.candidate_window, pnl_threshold=0.0, limit=cfg.candidate_pool)))
            if not cands:
                raise ValueError("No qualification candidates")
            batch = min(getattr(cfg,"fills_batch",80), len(cands))
            off = self._smart_offset % len(cands)
            window = [cands[(off+i)%len(cands)] for i in range(batch)]
            self._smart_offset = (off+batch)%len(cands)
            outcomes = client.qualification_bulk(window, cfg.fills_lookback, workers=3,
                                          rate_per_min=getattr(cfg,"fills_rate_per_min",50))
            from collections import Counter
            reasons = Counter(outcomes.get(a,{"status":"request_failed"})["status"] for a in window)
            results = {a:r["stats"] for a,r in outcomes.items() if a in window and r["status"]=="ok"}
            now = time.time()
            fresh, rejected = {}, []
            criteria = Counter()
            for addr,wr in results.items():
                if addr not in window or not wr:
                    continue
                if (wr["trades"] >= cfg.fills_min_trades and wr["recent_pnl"] > 0
                        and wr.get("span_hours",0) >= getattr(cfg,"fills_min_span_hours",24)):
                    fresh[addr] = {**wr,"ts":now}
                else:
                    rejected.append(addr)
                    reason = "too_few_trades" if wr["trades"]<cfg.fills_min_trades else "nonpositive_pnl" if wr["recent_pnl"]<=0 else "short_span"
                    criteria[reason] += 1
            store.publish_smart_pool(fresh, rejected, cfg.smart_pool_ttl_hours*3600, now)
            with self._qualification_lock:
                self._qualification_state = {**self._qualification_state,
                    "refreshing":False, "completed_at":now,
                    "failed":sum(reasons[k] for k in ("request_failed","rate_limited","invalid_data"))==len(window),
                    "partial_failure":any(reasons[k] for k in ("request_failed","rate_limited","invalid_data")),
                    "reasons":dict(reasons), "criteria":dict(criteria),
                    "duration_seconds":round(time.monotonic()-started,3),
                    "requested":len(window), "observed":len(results),
                    "qualified":len(fresh), "rejected":len(rejected),
                    "unavailable":len(window)-len(results)}
        except Exception:
            logger.exception("Background account qualification failed; valid prior entries retain original dates")
            with self._qualification_lock:
                self._qualification_state = {**self._qualification_state,
                    "refreshing":False, "failed":True,
                    "duration_seconds":round(time.monotonic()-started,3)}
        finally:
            if client is not None:
                client.close()
            if store is not None:
                store.close()

    def _select_smart_money(self, cfg) -> list[dict]:
        """Select from unexpired verified entries; disclose PnL-only fallback accounts."""
        def fallback() -> list[dict]:
            traders = self._client.top_traders(
                window=cfg.window, pnl_threshold=cfg.pnl_threshold_usd, limit=cfg.max_traders)
            return [{"addr": a, "win_rate": None, "recent_pnl": p, "trades": None}
                    for a, p in traders]

        if not getattr(cfg, "rank_by_fills", True):
            result = fallback()
            self._selection_meta = {"selected_at":time.time(), "selected":len(result),
                "qualified":0, "pnl_only":len(result), "oldest_verified_at":None,
                "newest_verified_at":None, "valid_for_hours":None}
            return result

        now = time.time()
        ttl = getattr(cfg, "smart_pool_ttl_hours", 8) * 3600
        # Freeze this selection before starting the worker. New qualifications apply next cycle.
        self._smart_pool = self._pool_store().load_smart_pool(ttl, now)
        self._schedule_qualification(cfg)

        # 累積池(已驗證的方向贏家)排序取前 max_traders
        items = list(self._smart_pool.items())
        result: list[dict] = []
        if items:
            wrs = [v["win_rate"] for _, v in items]
            pls = [v["recent_pnl"] for _, v in items]
            wmin, wmax = min(wrs), max(wrs)
            pmin, pmax = min(pls), max(pls)
            nrm = lambda v, lo, hi: (v - lo) / (hi - lo) if hi > lo else 0.5
            scored = [{"addr": a, **v,
                       "score": round(0.5 * nrm(v["win_rate"], wmin, wmax)
                                      + 0.5 * nrm(v["recent_pnl"], pmin, pmax), 4)}
                      for a, v in items]
            scored.sort(key=lambda s: s["score"], reverse=True)
            result = scored[:cfg.max_traders]
        # 暖機期池未滿→用 allTime PnL 榜補足到 max_traders（win_rate 暫無，隨累積被驗證帳號取代）
        # ——讓面板從一開始就是滿的、不會 100→5 暴跌，已驗證佔比隨時間升高。
        if len(result) < cfg.max_traders:
            have = {s["addr"] for s in result}
            for a, p in self._client.top_traders(
                    window=cfg.window, pnl_threshold=cfg.pnl_threshold_usd,
                    limit=cfg.max_traders * 2):
                if a not in have:
                    result.append({"addr": a, "win_rate": None, "recent_pnl": p, "trades": None})
                    have.add(a)
                    if len(result) >= cfg.max_traders:
                        break
        stamps = [x["ts"] for x in result if x.get("ts") is not None]
        self._selection_meta = {"selected_at":now, "selected":len(result),
            "qualified":len(stamps), "pnl_only":len(result)-len(stamps),
            "oldest_verified_at":min(stamps) if stamps else None,
            "newest_verified_at":max(stamps) if stamps else None,
            "valid_for_hours":ttl/3600}
        self._smart_sel = result
        logger.info("聰明錢累積池 %d 人(已驗證)→面板 %d(其餘 PnL 榜暫補)",
                    len(items), len(result))
        return self._smart_sel

    def _coin_aggregates(self) -> dict[str, dict]:
        """從 Hyperliquid 取聰明錢(近期勝率/獲利最佳)的持倉，聚合成 coin -> 多空名目。"""
        cfg = self.config.agents.smart_money
        # 90 秒內重用，足夠涵蓋一輪多標的
        if self._agg is not None and (self._cycle_pinned or time.time() - self._agg_ts < 90):
            return self._agg

        if self._client is None:
            self._client = HyperliquidClient()

        sel = self._select_smart_money(cfg)
        wr_map = {s["addr"]: s for s in sel}
        smart_addrs = [s["addr"] for s in sel]
        # 鯨魚＝全市場淨值前 N（獨立於聰明錢，過濾 HLP/做市金庫等超大非個人帳號）
        whale_pairs = []
        if getattr(cfg, "whale_full_market", True):
            whale_pairs = self._client.top_by_account_value(
                limit=cfg.whale_top_n, av_cap=getattr(cfg, "whale_av_cap_usd", None))
        whale_addrs_mkt = [a for a, _ in whale_pairs]

        # 聯集一次抓持倉——精簡串流，不保留原始 state JSON（大戶 state 很大會 OOM）
        slim = self._client.slim_accounts_bulk(list(dict.fromkeys(smart_addrs + whale_addrs_mkt)))

        def mk(addr: str) -> dict | None:
            a = slim.get(addr)
            if a is None:
                return None
            wr = wr_map.get(addr) or {}
            return {"addr": addr, "av": a["av"], "lev": a["lev"], "net": a["net"],
                    "pos": a["pos"], "win_rate": wr.get("win_rate"),
                    "recent_pnl": wr.get("recent_pnl")}

        smart_accounts = [a for a in (mk(x) for x in smart_addrs) if a]
        if whale_addrs_mkt:
            whale_accounts = [a for a in (mk(x) for x in whale_addrs_mkt) if a]
        else:                              # 舊版：聰明錢內淨值前 N
            whale_accounts = sorted(smart_accounts, key=lambda x: x["av"],
                                    reverse=True)[:cfg.whale_top_n]
        whale_set = {a["addr"] for a in whale_accounts}

        def blank() -> dict:
            return {"long": 0.0, "short": 0.0, "count": 0,
                    "whale_long": 0.0, "whale_short": 0.0, "whale_count": 0}

        agg: dict[str, dict] = {}
        for a in smart_accounts:           # 聰明錢多空（方向贏家）
            for coin, side, nv in a["pos"]:
                b = agg.setdefault(coin, blank())
                b["long" if side > 0 else "short"] += nv
                b["count"] += 1
        for a in whale_accounts:           # 鯨魚多空（全市場淨值前N，獨立統計）
            for coin, side, nv in a["pos"]:
                b = agg.setdefault(coin, blank())
                b["whale_long" if side > 0 else "whale_short"] += nv
                b["whale_count"] += 1

        self._trader_summary = self._summarize_traders(smart_accounts, whale_accounts)
        self._trader_summary["qualification"] = {**self._selection_meta,
            "positions_received":len(smart_accounts),
            "positions_qualified":sum(a.get("win_rate") is not None for a in smart_accounts),
            "positions_pnl_only":sum(a.get("win_rate") is None for a in smart_accounts)}
        self._trader_summary["overlap"] = len(set(smart_addrs) & whale_set)  # 兩群重疊人數
        self._agg = agg
        self._agg_ts = time.time()
        self._trader_count = len(smart_accounts)
        self._whale_count = len(whale_accounts)
        return agg

    def fetch(self, symbol: str) -> dict:
        cfg = self.config.agents.smart_money
        if not self.config.use_mock:
            agg = self._coin_aggregates().get(symbol, {"long": 0.0, "short": 0.0, "count": 0})
            return {
                "threshold_usd": cfg.pnl_threshold_usd,
                "window": cfg.window,
                "trader_count": self._trader_count,
                "position_count": agg["count"],
                "long_notional_usd": agg["long"],
                "short_notional_usd": agg["short"],
            }

        rng = random.Random(f"{symbol}-sm")
        return {
            "threshold_usd": cfg.pnl_threshold_usd,
            "window": cfg.window,
            "trader_count": rng.randint(20, 120),
            "position_count": rng.randint(10, 80),
            "long_notional_usd": rng.uniform(1, 10) * 1e6,
            "short_notional_usd": rng.uniform(1, 10) * 1e6,
        }

    def analyze(self, symbol: str, raw: dict) -> Observation:
        longs = raw["long_notional_usd"]
        shorts = raw["short_notional_usd"]
        total = longs + shorts or 1.0
        net = (longs - shorts) / total            # -1(全空) ~ +1(全多)
        direction = "bull" if net > 0.1 else "bear" if net < -0.1 else "neutral"
        stance = "偏多" if direction == "bull" else "偏空" if direction == "bear" else "中性"

        summary = (
            f"聰明錢規則追蹤樣本（{raw['trader_count']} 個 Hyperliquid 合約帳號）對 {symbol} {stance}，"
            f"淨多空比 {net:+.0%}（多 ${longs/1e6:.1f}M / 空 ${shorts/1e6:.1f}M）。"
        )
        return Observation(
            source=self.name,
            symbol=symbol,
            signal_type="positioning",
            direction=direction,
            magnitude=min(abs(net), 1.0),
            summary=summary,
            entities=[("cohort", "smart_money"), ("asset", symbol)],
            relations=[("smart_money", f"is_{direction}_on", symbol)],
            raw=raw,
        )
