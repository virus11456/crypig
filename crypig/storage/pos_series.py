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

    def close(self) -> None:
        self._conn.close()
