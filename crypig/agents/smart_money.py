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
        self._agg_ts: float = 0.0
        self._trader_count: int = 0
        self._whale_count: int = 0
        self._trader_summary: dict = {}
        self._smart_sel: list[dict] | None = None   # 本輪取出的聰明錢(前 max_traders)
        self._smart_pool: dict | None = None         # 跨輪累積的合格帳號池(持久化)
        self._smart_offset: int = 0                  # 候選輪轉位移(每輪抓不同一段)
        self._store = None                           # PosSeriesStore(累積池持久化)

    @staticmethod
    def _summarize_traders(smart_accounts: list[dict], whale_accounts: list[dict]) -> dict:
        """多空人數、比例、槓桿、勝率（看『決心』）。smart=方向贏家、whale=全市場淨值前N。"""
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
                "short_pct": round(len(shorts) / directional, 4) if directional else None,
                "long_pct": round(len(longs) / directional, 4) if directional else None,
                "lev_median": round(statistics.median(levs), 2) if levs else None,
                "lev_avg": round(statistics.mean(levs), 2) if levs else None,
                "lev_max": round(max(levs), 2) if levs else None,
                "winrate_median": round(statistics.median(wrs) * 100, 1) if wrs else None,
            }
        return {"smart": grp(smart_accounts), "whale": grp(whale_accounts)}

    def _pool_store(self):
        if self._store is None:
            from ..storage.pos_series import PosSeriesStore
            self._store = PosSeriesStore(self.config.posseries_db)
        return self._store

    def _select_smart_money(self, cfg) -> list[dict]:
        """聰明錢＝近 N 筆平倉「勝率＋獲利」最佳者，採『跨輪累積』避免被限流。

        每輪只抓 fills_batch 個帳號的成交（節流 fills_rate_per_min），存活者(剔除做市)
        併進持久化的累積池 smart_pool；候選母體輪轉，幾輪後自然滾到 max_traders。
        池內條目超過 smart_pool_ttl_hours 汰舊（靠輪轉回頭重新驗證刷新），故會持續更新。
        """
        def fallback() -> list[dict]:
            traders = self._client.top_traders(
                window=cfg.window, pnl_threshold=cfg.pnl_threshold_usd, limit=cfg.max_traders)
            return [{"addr": a, "win_rate": None, "recent_pnl": p, "trades": None}
                    for a, p in traders]

        if not getattr(cfg, "rank_by_fills", True):
            return fallback()

        now = time.time()
        ttl = getattr(cfg, "smart_pool_ttl_hours", 8) * 3600
        store = self._pool_store()
        if self._smart_pool is None:               # 首次：從磁碟載入累積池(跨重啟保留)
            self._smart_pool = store.load_smart_pool(ttl, now)

        # 候選母體輪轉：每輪抓不同一段 fills_batch
        cands = [a for a, _ in self._client.top_traders(
            window=cfg.candidate_window, pnl_threshold=0.0, limit=cfg.candidate_pool)]
        if cands:
            batch = getattr(cfg, "fills_batch", 80)
            off = self._smart_offset % len(cands)
            window = cands[off:off + batch]
            if len(window) < batch:                # 繞回頭
                window += cands[:batch - len(window)]
            self._smart_offset = (off + batch) % len(cands)
            wr_by = self._client.winrate_bulk(
                window, cfg.fills_lookback, workers=3,
                rate_per_min=getattr(cfg, "fills_rate_per_min", 50))
            min_span = getattr(cfg, "fills_min_span_hours", 24)
            fresh = {}
            for addr, wr in wr_by.items():
                if (wr and wr["trades"] >= cfg.fills_min_trades and wr["recent_pnl"] > 0
                        and wr.get("span_hours", 0) >= min_span):   # 剔除做市/高頻
                    self._smart_pool[addr] = {**wr, "ts": now}
                    fresh[addr] = self._smart_pool[addr]
            if fresh:
                store.upsert_smart_pool(fresh)

        # 汰除過舊（記憶體＋磁碟），保持新鮮
        self._smart_pool = {a: v for a, v in self._smart_pool.items() if now - v["ts"] < ttl}
        store.prune_smart_pool(ttl, now)

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
        self._smart_sel = result
        logger.info("聰明錢累積池 %d 人(已驗證)→面板 %d(其餘 PnL 榜暫補)",
                    len(items), len(result))
        return self._smart_sel

    def _coin_aggregates(self) -> dict[str, dict]:
        """從 Hyperliquid 取聰明錢(近期勝率/獲利最佳)的持倉，聚合成 coin -> 多空名目。"""
        cfg = self.config.agents.smart_money
        # 90 秒內重用，足夠涵蓋一輪多標的
        if self._agg is not None and time.time() - self._agg_ts < 90:
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
            f"聰明錢（{raw['trader_count']} 位 {raw['window']} 獲利>"
            f"{raw['threshold_usd']/1e6:.0f}M 交易者）對 {symbol} {stance}，"
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
