"""大戶持倉時間序列（sqlite，stdlib）。

每輪把「某族群(鯨魚/聰明錢)對某幣的合約淨持倉」落地一筆，逐輪累積成時間軸——
看大戶部位隨時間怎麼變（淨多空翻轉、加碼/減碼），是真正的進場時機線索。

Hyperliquid 無持倉歷史，只能我們自己每輪記一筆往前累積。
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

_DDL = """
CREATE TABLE IF NOT EXISTS pos_series (
    ts         TEXT NOT NULL,      -- ISO 時間
    cohort     TEXT NOT NULL,      -- whale | smart
    symbol     TEXT NOT NULL,
    long_usd   REAL NOT NULL,
    short_usd  REAL NOT NULL,
    net        REAL,               -- (long-short)/(long+short)，-1..+1
    count      INTEGER,            -- 該族群在此幣有持倉的帳號數
    PRIMARY KEY (ts, cohort, symbol)
);
CREATE INDEX IF NOT EXISTS idx_pos ON pos_series(cohort, symbol, ts);
CREATE TABLE IF NOT EXISTS radar_hist (
    ts        TEXT PRIMARY KEY,   -- ISO 時間
    gap       REAL,               -- 群眾 - 聰明錢 背離量(趨 0=收斂=反轉接近)
    crowd_m   REAL,               -- 群眾方向(恐懼貪婪標準化)
    smart_avg REAL,               -- 聰明錢整體淨多空
    n_div     INTEGER,            -- 背離幣數
    n_top     INTEGER,            -- 頂部反指標幣數
    n_bottom  INTEGER,            -- 底部機會幣數
    diverging INTEGER             -- 市場層級是否背離
);
CREATE TABLE IF NOT EXISTS smart_pool (
    addr        TEXT PRIMARY KEY,  -- 聰明錢帳號(跨輪累積，避免一次抓太多被限流)
    win_rate    REAL,              -- 近 N 筆平倉勝率
    recent_pnl  REAL,              -- 近 N 筆獲利
    span_hours  REAL,              -- 近 N 筆橫跨時數(剔除做市)
    trades      INTEGER,
    ts          REAL               -- 最後驗證時間(epoch)，供 TTL 汰舊
);
"""


class PosSeriesStore:
    def __init__(self, path: str = "posseries.db"):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_DDL)
        self._conn.commit()

    def record(self, ts: str, cohort: str, symbol: str,
               long_usd: float, short_usd: float, count: int) -> None:
        tot = long_usd + short_usd
        net = (long_usd - short_usd) / tot if tot > 0 else None
        self._conn.execute(
            "INSERT OR REPLACE INTO pos_series(ts,cohort,symbol,long_usd,short_usd,net,count)"
            " VALUES (?,?,?,?,?,?,?)",
            (ts, cohort, symbol, long_usd, short_usd, net, count))
        self._conn.commit()

    def history(self, cohort: str, symbol: str, limit: int = 400) -> list[dict]:
        """某族群某幣的持倉時間序列（時間升冪，畫線用）。"""
        rows = self._conn.execute(
            "SELECT * FROM pos_series WHERE cohort=? AND symbol=? ORDER BY ts DESC LIMIT ?",
            (cohort, symbol, limit)).fetchall()
        return [{
            "ts": r["ts"], "long_usd": r["long_usd"], "short_usd": r["short_usd"],
            "net_usd": r["long_usd"] - r["short_usd"], "net": r["net"], "count": r["count"],
        } for r in reversed(rows)]

    def record_crowd(self, ts: str, symbol: str, net: float, count: int | None = None) -> None:
        """逐幣散戶方向（由資金費率正規化的 crowd，-1..+1）落地，供逐幣背離驗證。

        散戶端沒有多空名目金額，net 直接存正規化的擁擠方向（cohort='crowd'）。
        """
        self._conn.execute(
            "INSERT OR REPLACE INTO pos_series(ts,cohort,symbol,long_usd,short_usd,net,count)"
            " VALUES (?,?,?,?,?,?,?)",
            (ts, "crowd", symbol, 0.0, 0.0, net, count))
        self._conn.commit()

    def symbols(self, cohort: str, min_rows: int = 1) -> list[str]:
        """某族群有持倉時間序列的幣（依資料筆數多到少）——逐幣驗證用。"""
        rows = self._conn.execute(
            "SELECT symbol, COUNT(*) n FROM pos_series WHERE cohort=? "
            "GROUP BY symbol HAVING n>=? ORDER BY n DESC", (cohort, min_rows)).fetchall()
        return [r["symbol"] for r in rows]

    def record_radar(self, ts: str, market: dict) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO radar_hist(ts,gap,crowd_m,smart_avg,n_div,n_top,n_bottom,diverging)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (ts, market.get("gap"), market.get("crowd_m"), market.get("smart_avg"),
             int(market.get("n_div") or 0), int(market.get("n_top") or 0),
             int(market.get("n_bottom") or 0), 1 if market.get("diverging") else 0))
        self._conn.commit()

    def radar_history(self, limit: int = 400) -> list[dict]:
        """市場背離時間序列（時間升冪）。"""
        rows = self._conn.execute(
            "SELECT * FROM radar_hist ORDER BY ts DESC LIMIT ?", (limit,)).fetchall()
        return [{"ts": r["ts"], "gap": r["gap"], "crowd_m": r["crowd_m"],
                 "smart_avg": r["smart_avg"], "n_div": r["n_div"], "n_top": r["n_top"],
                 "n_bottom": r["n_bottom"], "diverging": bool(r["diverging"])}
                for r in reversed(rows)]

    # ---- 聰明錢累積池（跨輪累加、TTL 汰舊，避免一次抓太多被限流）----
    def load_smart_pool(self, ttl_sec: float, now: float) -> dict[str, dict]:
        rows = self._conn.execute(
            "SELECT * FROM smart_pool WHERE ? - ts < ?", (now, ttl_sec)).fetchall()
        return {r["addr"]: {"win_rate": r["win_rate"], "recent_pnl": r["recent_pnl"],
                            "span_hours": r["span_hours"], "trades": r["trades"], "ts": r["ts"]}
                for r in rows}

    def upsert_smart_pool(self, entries: dict[str, dict]) -> None:
        self._conn.executemany(
            "INSERT OR REPLACE INTO smart_pool(addr,win_rate,recent_pnl,span_hours,trades,ts)"
            " VALUES (?,?,?,?,?,?)",
            [(a, v.get("win_rate"), v.get("recent_pnl"), v.get("span_hours"),
              v.get("trades"), v.get("ts")) for a, v in entries.items()])
        self._conn.commit()

    def prune_smart_pool(self, ttl_sec: float, now: float) -> None:
        self._conn.execute("DELETE FROM smart_pool WHERE ? - ts >= ?", (now, ttl_sec))
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()
