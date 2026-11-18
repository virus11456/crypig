"""Matched position changes and liquidation levels from completed account reads."""
from __future__ import annotations

from contextlib import closing
from decimal import Decimal
import json
from pathlib import Path
import re
import sqlite3
import time

from .account_positions import action

MAP_COINS = ("BTC", "ETH", "HYPE")
MIN_MAP_ACCOUNTS = 3
TOP_ACCOUNTS = 10
RETENTION_SECONDS = 90 * 86400
STALE_SECONDS = 2400
ADDRESS = re.compile(r"0x[0-9a-f]{40}")

LABELS = {
    "open": "開倉", "add": "加倉", "reduce": "減倉",
    "close": "平倉", "flip": "翻向", "possible_liquidation": "疑似清算",
}


def _money(value: float) -> str:
    if abs(value) >= 10000:
        return f"${value / 10000:,.1f} 萬"
    return f"${value:,.0f}"


def _short_address(address: str) -> str:
    return f"{address[:8]}…{address[-4:]}"


def _position_event(address, coin, before, after, quote, identity, previous_at, observed_at):
    old_size = before["size"] if before else 0
    new_size = after["size"] if after else 0
    change = action(old_size, new_size)
    if change == "unchanged":
        return None
    kind, direction = change.split("_")
    latest = after or before
    implied_price = latest["notional_usd"] / abs(latest["size"])
    price = implied_price if after else quote.get("price") or implied_price
    delta = abs(new_size - old_size) * price
    if delta < 500000 and (not old_size or abs(new_size - old_size) < abs(old_size) * 0.2):
        return None

    if kind == "close" and (level := before.get("liquidation_price")):
        previous_price = before["notional_usd"] / abs(old_size)
        if (old_size > 0 and previous_price <= level) or (old_size < 0 and previous_price >= level):
            kind = "possible_liquidation"

    funding = quote.get("funding_ann")
    crowd = "unknown" if funding is None else "long" if funding > 0.05 else "short" if funding < -0.05 else "neutral"
    position_side = "long" if new_size > 0 else "short" if new_size < 0 else None
    side = "多" if direction == "long" else "空"
    sentence = f"{LABELS[kind]} {coin} {side}倉，估計變動名目 {_money(delta)}"
    if after:
        sentence += f"，目前名目 {_money(after['notional_usd'])}"
        if after.get("leverage") is not None:
            sentence += f"（{after['leverage']:g} 倍）"
        if after.get("entry_price") is not None:
            sentence += f"，均價 ${after['entry_price']:,.4f}".rstrip("0").rstrip(".")
        pnl = after.get("unrealized_pnl_usd")
        if pnl:
            sentence += f"，目前浮{'盈' if pnl > 0 else '虧'} {_money(abs(pnl))}"
    return {
        "address": address, "coin": coin, "type": kind, "label": LABELS[kind], "side": direction,
        "before": before, "after": after, "before_at": previous_at, "ts": observed_at,
        "price": price, "change_notional_usd": delta, "message": sentence + "。",
        "crowd": crowd, "opposes_crowd": position_side is not None and crowd in ("long", "short") and crowd != position_side,
        "alias": identity.get("alias") or _short_address(address),
        "source": identity.get("source"), "x_url": identity.get("x_url"),
    }


def notable_events(previous, current, quotes, identities):
    # Compare only successful reads in consecutive batches. Rank by either batch
    # so an account that fully closes a large position can still appear.
    matched = {address for address in current.keys() & previous.keys()
               if current[address]["observed_at"] > previous[address]["observed_at"]}
    def gross(account):
        return sum(position["notional_usd"] for position in account["positions"].values())
    ranked = sorted(matched - identities.keys(),
                    key=lambda address: (-max(gross(previous[address]), gross(current[address])), address))
    tracked = matched & identities.keys() | set(ranked[:TOP_ACCOUNTS])
    events = []
    for address in sorted(tracked):
        before, after = previous[address], current[address]
        old, new = before["positions"], after["positions"]
        for coin in sorted(old.keys() | new.keys()):
            event = _position_event(address, coin, old.get(coin), new.get(coin),
                                    quotes.get(coin, {}), identities.get(address, {}),
                                    before["observed_at"], after["observed_at"])
            if event:
                events.append(event)
    return events, len(tracked)


def liquidation_distribution(coin, accounts, price):
    rows = [account["positions"][coin] for account in accounts.values() if coin in account["positions"]]
    valid = [row for row in rows if row.get("liquidation_price")]
    result = {
        "coin": coin, "price": price, "sample_accounts": len(rows), "covered_accounts": len(valid),
        "missing_liquidation_price": len(rows) - len(valid), "minimum_accounts": MIN_MAP_ACCOUNTS,
        "buckets": [], "outside_range": None,
    }
    if price is None or price <= 0:
        return {**result, "status": "price_unavailable", "price": None}
    if len(valid) < MIN_MAP_ACCOUNTS:
        return {**result, "status": "insufficient_sample"}
    buckets = [{"from_pct": start, "to_pct": start + 2, "long_usd": 0., "short_usd": 0.}
               for start in range(-20, 20, 2)]
    outside = {side: {"long_usd": 0., "short_usd": 0.} for side in ("below", "above")}
    reference = Decimal(str(price))
    for row in valid:
        pct = (Decimal(str(row["liquidation_price"])) - reference) * 100 / reference
        if pct < -20 or pct > 20:
            bucket = outside["below" if pct < -20 else "above"]
        else:
            index = min(int((pct + 20) // 2), len(buckets) - 1)
            bucket = buckets[index]
        bucket["long_usd" if row["size"] > 0 else "short_usd"] += row["notional_usd"]
    return {**result, "status": "ok", "buckets": buckets, "outside_range": outside}


def account_batch(capture, quotes, identities, previous, ts, quote_at):
    accounts = {address: {"positions": state["positions"], "observed_at": state["observed_at"]}
                for address, state in capture["accounts"].items()
                if ADDRESS.fullmatch(address) and "positions" in state and "observed_at" in state}
    events, matched = notable_events(previous, accounts, quotes, identities)
    snapshot = {
        "as_of": ts, "selected_accounts": capture["selected"], "received_accounts": len(accounts),
        "matched_accounts": matched, "quote_at": quote_at,
        "status": "waiting" if not previous else "ok" if matched else "no_overlap",
        "maps": {coin: liquidation_distribution(coin, accounts, quotes.get(coin, {}).get("price"))
                 for coin in MAP_COINS},
    }
    return accounts, events, snapshot


class TrackedPositions:
    def __init__(self, path):
        self.path = Path(path)

    def record(self, ts, capture, quotes, identities, quote_at):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path, timeout=10)) as db, db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("""CREATE TABLE IF NOT EXISTS tracked_batch (
                       id INTEGER PRIMARY KEY CHECK (id = 1), ts REAL NOT NULL,
                       accounts TEXT NOT NULL, snapshot TEXT NOT NULL)""")
            db.execute("""CREATE TABLE IF NOT EXISTS notable_events (
                       batch_at REAL, observed_at REAL, address TEXT, coin TEXT, payload TEXT NOT NULL,
                       PRIMARY KEY(batch_at, address, coin))""")
            db.execute("CREATE INDEX IF NOT EXISTS notable_coin_time ON notable_events(coin, observed_at DESC)")
            db.execute("CREATE INDEX IF NOT EXISTS notable_time ON notable_events(observed_at DESC)")
            last = db.execute("SELECT ts, accounts FROM tracked_batch").fetchone()
            if last and ts <= last[0]:
                return
            previous = json.loads(last[1]) if last else {}
            accounts, events, snapshot = account_batch(capture, quotes, identities, previous, ts, quote_at)
            db.execute("INSERT OR REPLACE INTO tracked_batch VALUES (1, ?, ?, ?)",
                       (ts, json.dumps(accounts, allow_nan=False), json.dumps(snapshot, allow_nan=False)))
            db.executemany("INSERT INTO notable_events VALUES (?, ?, ?, ?, ?)",
                           ((ts, row["ts"], row["address"], row["coin"], json.dumps(row, allow_nan=False))
                            for row in events))
            db.execute("DELETE FROM notable_events WHERE observed_at < ?", (ts - RETENTION_SECONDS,))

    def read(self, *, coin=None, limit=0):
        if not self.path.is_file():
            return {}, []
        with closing(sqlite3.connect(self.path, timeout=10)) as db:
            db.execute("BEGIN")
            row = db.execute("SELECT snapshot FROM tracked_batch").fetchone()
            if not row:
                return {}, []
            snapshot = json.loads(row[0])
            events = []
            if limit:
                snapshot["coins"] = [row[0] for row in db.execute(
                    "SELECT DISTINCT coin FROM notable_events ORDER BY coin")]
                if coin:
                    rows = db.execute("""SELECT payload FROM notable_events WHERE coin = ?
                                      ORDER BY observed_at DESC, address, coin LIMIT ?""", (coin, limit))
                else:
                    rows = db.execute("""SELECT payload FROM notable_events
                                      ORDER BY observed_at DESC, address, coin LIMIT ?""", (limit,))
                events = [json.loads(row[0]) for row in rows]
            return snapshot, events


def mock_tracked_positions():
    now = time.time()
    prices = {"BTC": 67500, "ETH": 3400, "HYPE": 36}
    accounts = {}
    for index in range(1, 7):
        address = f"0x{index:040x}"
        positions = {}
        for coin, price in prices.items():
            side = -1 if index % 2 else 1
            notional = index * 420000
            positions[coin] = {
                "size": side * notional / price, "notional_usd": notional,
                "entry_price": price * .99, "liquidation_price": price * (1 - side * (index + 1) * .025),
                "leverage": index + 2, "unrealized_pnl_usd": side * notional * .01,
            }
        accounts[address] = {"positions": positions, "observed_at": now - index * 30}
    previous = {}
    for index, (address, account) in enumerate(accounts.items()):
        coin = MAP_COINS[index % len(MAP_COINS)]
        position = account["positions"][coin]
        factor = .6 if index == 0 else 1.4
        old = {**position, "size": position["size"] * factor,
               "notional_usd": position["notional_usd"] * factor}
        previous[address] = {"observed_at": account["observed_at"] - 1200,
                             "positions": {**account["positions"], coin: old}}
    identities = {address: {"alias": f"示範帳號 {index}"} for index, address in enumerate(accounts, 1)}
    quotes = {coin: {"price": price, "funding_ann": .2} for coin, price in prices.items()}
    _, events, snapshot = account_batch({"selected": len(accounts), "accounts": accounts},
                                        quotes, identities, previous, now, now)
    return snapshot, sorted(events, key=lambda row: -row["ts"])
