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

    @staticmethod
    def _summarize_traders(accounts: list[dict], whale_addrs: set) -> dict:
        """前 N 名交易者的多空人數、比例、槓桿（看『決心』）。smart=全部、whale=淨值前N。"""
        import statistics

        def grp(accs):
            longs = [a for a in accs if a["net"] > 0]
            shorts = [a for a in accs if a["net"] < 0]
            flat = [a for a in accs if a["net"] == 0]
            levs = [a["lev"] for a in accs if a["lev"] > 0]
            directional = len(longs) + len(shorts)
            return {
                "total": len(accs), "long": len(longs), "short": len(shorts),
                "flat": len(flat),
                "short_pct": round(len(shorts) / directional, 4) if directional else None,
                "long_pct": round(len(longs) / directional, 4) if directional else None,
                "lev_median": round(statistics.median(levs), 2) if levs else None,
                "lev_avg": round(statistics.mean(levs), 2) if levs else None,
                "lev_max": round(max(levs), 2) if levs else None,
            }
        whales = [a for a in accounts if a["addr"] in whale_addrs]
        return {"smart": grp(accounts), "whale": grp(whales)}

    def _coin_aggregates(self) -> dict[str, dict]:
        """從 Hyperliquid 取前 N 名合格交易者的持倉，聚合成 coin -> 多空名目。"""
        cfg = self.config.agents.smart_money
        # 90 秒內重用，足夠涵蓋一輪多標的
        if self._agg is not None and time.time() - self._agg_ts < 90:
            return self._agg

        if self._client is None:
            self._client = HyperliquidClient()

        traders = self._client.top_traders(
            window=cfg.window,
            pnl_threshold=cfg.pnl_threshold_usd,
            limit=cfg.max_traders,
        )
        states = self._client.states_bulk([addr for addr, _ in traders])  # 並發抓持倉

        # 每個帳號：淨值(accountValue)、總名目(totalNtlPos→槓桿)、淨多空、持倉
        # 鯨魚＝淨值最大的前 N 名（錢很多的人）
        accounts = []
        for addr, _pnl in traders:
            state = states.get(addr)
            if state is None:
                continue
            ms = state.get("marginSummary") or {}
            try:
                av = float(ms.get("accountValue", 0.0) or 0.0)
                ntl = float(ms.get("totalNtlPos", 0.0) or 0.0)
            except (TypeError, ValueError):
                av = ntl = 0.0
            positions = list(self._client.iter_positions(state))
            net = 0.0
            for pos in positions:
                try:
                    szi = float(pos.get("szi", 0.0))
                    net += float(pos.get("positionValue", 0.0)) * (1 if szi > 0 else -1)
                except (TypeError, ValueError):
                    continue
            accounts.append({"addr": addr, "av": av, "lev": ntl / av if av > 0 else 0.0,
                             "net": net, "positions": positions})

        whale_addrs = {a["addr"] for a in
                       sorted(accounts, key=lambda x: x["av"], reverse=True)[:cfg.whale_top_n]}

        agg: dict[str, dict] = {}
        for a in accounts:
            is_whale = a["addr"] in whale_addrs
            for pos in a["positions"]:
                coin = pos["coin"]
                try:
                    szi = float(pos.get("szi", 0.0))
                    notional = abs(float(pos.get("positionValue", 0.0)))
                except (TypeError, ValueError):
                    continue
                b = agg.setdefault(coin, {"long": 0.0, "short": 0.0, "count": 0,
                                          "whale_long": 0.0, "whale_short": 0.0, "whale_count": 0})
                side = "long" if szi > 0 else "short" if szi < 0 else None
                if side:
                    b[side] += notional
                    b["count"] += 1
                    if is_whale:
                        b["whale_" + side] += notional
                        b["whale_count"] += 1

        self._trader_summary = self._summarize_traders(accounts, whale_addrs)
        self._agg = agg
        self._agg_ts = time.time()
        self._trader_count = len(accounts)
        self._whale_count = len(whale_addrs)
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
