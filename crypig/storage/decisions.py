"""決策持久化（sqlite，stdlib）。

每輪決策層輸出（每個 symbol 的綜合判斷）落地一筆，供：
  - 看板顯示最新決策
  - 歷史回測 / 畫分數與信心度走勢
signals 等巢狀結構以 JSON 字串存放。
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

_DDL = """
CREATE TABLE IF NOT EXISTS decisions (
    ts          TEXT NOT NULL,
    symbol      TEXT NOT NULL,
    score       REAL NOT NULL,
    label       TEXT NOT NULL,
    confidence  REAL NOT NULL,
    action      TEXT NOT NULL,
    reason      TEXT NOT NULL,
    consensus   TEXT NOT NULL,
    signals     TEXT NOT NULL,
    alerts      TEXT NOT NULL,
    price       REAL
);
CREATE INDEX IF NOT EXISTS idx_dec ON decisions(symbol, ts);
"""


class DecisionStore:
    def __init__(self, path: str = "decisions.db"):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        # check_same_thread=False：FastAPI 端點在 worker thread 執行，連線需跨執行緒
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_DDL)
        self._migrate()
        self._conn.commit()

    def _migrate(self) -> None:
        """舊版表（無 price 欄）就地補欄，向後相容。"""
        cols = {r["name"] for r in self._conn.execute("PRAGMA table_info(decisions)")}
        if "price" not in cols:
            self._conn.execute("ALTER TABLE decisions ADD COLUMN price REAL")

    def record_cycle(self, signals: dict[str, dict], ts: str,
                     prices: dict[str, float] | None = None) -> int:
        """落地一輪所有 symbol 的決策，回寫入筆數。prices：各幣決策當下價。"""
        prices = prices or {}
        rows = []
        for sym, d in signals.items():
            rows.append((
                ts, sym,
                float(d.get("score", 0.0)), d.get("label", ""),
                float(d.get("confidence", 0.0)), d.get("action", ""),
                d.get("reason", ""),
                json.dumps(d.get("consensus", {}), ensure_ascii=False),
                json.dumps(d.get("signals", []), ensure_ascii=False),
                json.dumps(d.get("alerts", []), ensure_ascii=False),
                prices.get(sym),
            ))
        self._conn.executemany(
            "INSERT INTO decisions(ts,symbol,score,label,confidence,action,"
            "reason,consensus,signals,alerts,price) VALUES (?,?,?,?,?,?,?,?,?,?,?)", rows)
        self._conn.commit()
        return len(rows)

    def latest(self) -> list[dict]:
        """每個 symbol 取最新一筆決策。"""
        sql = """
            SELECT d.* FROM decisions d
            JOIN (SELECT symbol, MAX(ts) AS mts FROM decisions GROUP BY symbol) m
              ON d.symbol = m.symbol AND d.ts = m.mts
            ORDER BY d.symbol
        """
        return [self._row(r) for r in self._conn.execute(sql).fetchall()]

    def history(self, symbol: str, limit: int = 50) -> list[dict]:
        """某 symbol 的決策歷史（時間升冪，便於畫走勢）。"""
        rows = self._conn.execute(
            "SELECT * FROM decisions WHERE symbol=? ORDER BY ts DESC LIMIT ?",
            (symbol, limit)).fetchall()
        return [self._row(r) for r in reversed(rows)]

    def series(self, symbol: str) -> list[dict]:
        """某 symbol 全部決策（時間升冪），回測配對用。"""
        rows = self._conn.execute(
            "SELECT * FROM decisions WHERE symbol=? ORDER BY ts ASC", (symbol,)).fetchall()
        return [self._row(r) for r in rows]

    def symbols(self) -> list[str]:
        rows = self._conn.execute(
            "SELECT DISTINCT symbol FROM decisions ORDER BY symbol").fetchall()
        return [r["symbol"] for r in rows]

    @staticmethod
    def _row(r: sqlite3.Row) -> dict:
        return {
            "ts": r["ts"], "symbol": r["symbol"], "score": r["score"],
            "label": r["label"], "confidence": r["confidence"],
            "action": r["action"], "reason": r["reason"],
            "consensus": json.loads(r["consensus"]),
            "signals": json.loads(r["signals"]),
            "alerts": json.loads(r["alerts"]),
            "price": r["price"],
        }

    def close(self) -> None:
        self._conn.close()
