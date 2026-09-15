"""時序快照儲存（sqlite，stdlib，零外部相依）。

讓 agent 把每輪觀測值落地，下一輪即可計算「變化量」(例如持倉量變化、
長期持有者供給變化)。正式環境可換 TimescaleDB，介面不變。
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

_DDL = """
CREATE TABLE IF NOT EXISTS snapshots (
    ts      TEXT NOT NULL,
    source  TEXT NOT NULL,
    symbol  TEXT NOT NULL,
    metric  TEXT NOT NULL,
    value   REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_snap ON snapshots(source, symbol, metric, ts);
"""


class SnapshotStore:
    def __init__(self, path: str = "snapshots.db"):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        # check_same_thread=False：FastAPI 端點在 worker thread 執行，連線需跨執行緒
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.executescript(_DDL)
        self._conn.commit()

    def record(self, source: str, symbol: str, metric: str, value: float, ts: str) -> None:
        self._conn.execute(
            "INSERT INTO snapshots(ts, source, symbol, metric, value) VALUES (?,?,?,?,?)",
            (ts, source, symbol, metric, value),
        )
        self._conn.commit()

    def latest(self, source: str, symbol: str, metric: str,
               before_ts: str | None = None) -> tuple[str, float] | None:
        """取最近一筆（可指定在某時間點之前），用來和當前值比較算變化。"""
        sql = ("SELECT ts, value FROM snapshots "
               "WHERE source=? AND symbol=? AND metric=?")
        params: list = [source, symbol, metric]
        if before_ts is not None:
            sql += " AND ts < ?"
            params.append(before_ts)
        sql += " ORDER BY ts DESC LIMIT 1"
        row = self._conn.execute(sql, params).fetchone()
        return (row[0], row[1]) if row else None

    def close(self) -> None:
        self._conn.close()
