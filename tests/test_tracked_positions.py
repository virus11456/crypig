import time
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from crypig.clients.hyperliquid import HyperliquidClient
from crypig.config import Config
from crypig.dashboard import api
from crypig.orchestrator import Orchestrator
from crypig.storage.tracked_positions import TrackedPositions, liquidation_distribution, notable_events


ADDRESS = "0x" + "a" * 40


def position(size, mark=100000, liq=None):
    return {"size": size, "notional_usd": abs(size) * mark, "liquidation_price": liq,
            "entry_price": 99000, "leverage": 10, "unrealized_pnl_usd": -2000}


def account(ts, pos):
    return {"observed_at": ts, "positions": {"BTC": pos} if pos else {}}


@pytest.mark.parametrize(("old", "new", "kind"), [
    (None, position(-5), "open"),
    (position(-5), position(-6), "add"),
    (position(5), position(4), "reduce"),
    (position(5), None, "close"),
    (position(5), position(-1), "flip"),
    (position(5, mark=91000, liq=92000), None, "possible_liquidation"),
    (None, position(4.9), None),
    (position(5), position(5.5), None),
    (position(5), position(5, mark=200000), None),
])
def test_notable_event_quantity_threshold_and_direction(old, new, kind):
    events, matched = notable_events(
        {ADDRESS: account(10, old)}, {ADDRESS: account(20, new)},
        {"BTC": {"price": 100000, "funding_ann": 0.2}},
        {ADDRESS: {"alias": "公開帳號", "source": "公開資料"}},
    )
    assert matched == 1
    if kind is None:
        assert events == []
    else:
        event, = events
        assert event["type"] == kind
        assert event["alias"] == "公開帳號"
        assert event["label"] in event["message"] and "BTC" in event["message"]
        assert event["opposes_crowd"] == (new is not None and new["size"] < 0)
        assert event["before_at"] == 10 and event["ts"] == 20


def test_distribution_bins_edges_and_exclusions():
    accounts = {str(i): account(20, position(size, liq=liq)) for i, (size, liq) in enumerate([
        (1, 80000), (2, 82000), (-3, 120000), (4, 79999), (-5, 120001), (6, None),
    ])}
    result = liquidation_distribution("BTC", accounts, 100000)
    assert result["status"] == "ok" and result["sample_accounts"] == 6
    assert result["covered_accounts"] == 5 and result["missing_liquidation_price"] == 1
    assert result["buckets"][0]["long_usd"] == 100000
    assert result["buckets"][1]["long_usd"] == 200000
    assert result["buckets"][-1]["short_usd"] == 300000
    assert result["outside_range"]["below"]["long_usd"] == 400000
    assert result["outside_range"]["above"]["short_usd"] == 500000
    assert liquidation_distribution("BTC", {}, 100000)["status"] == "insufficient_sample"
    assert liquidation_distribution("BTC", accounts, None)["status"] == "price_unavailable"


def test_batch_retries_and_failed_reads_do_not_turn_into_trades(tmp_path):
    store = TrackedPositions(tmp_path / "tracked.db")
    quote = {"BTC": {"price": 100000, "funding_ann": 0}}
    def record(stamp, accounts):
        store.record(stamp, {"selected": 2, "accounts": accounts}, quote, {}, stamp)
    record(1000, {ADDRESS: account(1000, position(20))})
    record(2200, {})
    record(3000, {ADDRESS: account(3000, None)})
    assert store.read(limit=50)[1] == []
    record(4000, {ADDRESS: account(4000, position(9))})
    record(4000, {ADDRESS: account(4000, position(30))})
    record(3800, {})
    assert store.read(coin="ETH", limit=50)[1] == []
    snapshot, events = store.read(coin="BTC", limit=50)
    assert snapshot["coins"] == ["BTC"]
    assert [event["type"] for event in events] == ["open"]
    record(10000, {ADDRESS: account(10000, None)})
    snapshot, events = store.read(limit=50)
    assert snapshot["status"] == "ok"
    assert [event["type"] for event in events] == ["close", "open"]
    assert events[0]["before_at"] == 4000


def test_collector_keeps_optional_fields_without_discarding_account():
    client = HyperliquidClient()
    try:
        payload = {"marginSummary": {"accountValue": "100000", "totalNtlPos": "500000"},
                   "assetPositions": [{"position": {"coin": "BTC", "szi": "-5", "positionValue": "500000",
                       "liquidationPx": "110000", "entryPx": "bad", "unrealizedPnl": "-500",
                       "leverage": {"type": "isolated", "value": 10}}}]}
        client._post_info = Mock(return_value=payload)
        result = client.slim_account(ADDRESS)
        assert result["pos"] == [("BTC", -1, 500000)]
        assert result["positions"]["BTC"] == {
            "size": -5, "notional_usd": 500000, "entry_price": None,
            "liquidation_price": 110000, "leverage": 10, "unrealized_pnl_usd": -500,
        }
    finally:
        client.close()


def test_completed_collection_shares_account_batch_and_serves_both_endpoints(tmp_path, monkeypatch):
    monkeypatch.setenv("CRYPIG_SCHEDULER", "0")
    addresses = ["0x" + char * 40 for char in "abc"]
    cfg = Config(
        use_mock=False, symbols=["BTC"], snapshot_db=str(tmp_path / "snapshots.db"),
        decisions_db=str(tmp_path / "decisions.db"), posseries_db=str(tmp_path / "positions.db"),
        kg={"path": str(tmp_path / "kg.json")},
        agents={"smart_money": {"rank_by_fills": False}, "whales": {"enabled": False},
                "divergence": {"enabled": False}, "lth": {"enabled": False}},
        notable_addresses=[{"address": addresses[0].upper().replace("0X", "0x"), "alias": "公開帳號", "source": "來源"}],
    )
    orc = Orchestrator(cfg)
    monkeypatch.setattr(api, "orchestrator", lambda: orc)
    for name in ("_prepare_cycle_derivatives", "_refresh_market_data"):
        monkeypatch.setattr(orc, name, lambda: None)
    now = time.time()
    monkeypatch.setattr(orc.quotes, "read", lambda: (
        [{"symbol": "BTC", "price": 100000, "funding_ann": .2}], {"stale": False, "fetched_at": now}))
    sm = orc.agents[0]
    sm._client = Mock()
    sm._client.top_traders.return_value = [(addresses[0], 100)]
    sm._client.top_by_account_value.return_value = [(address, 1000) for address in addresses]
    sm._client.daily_closes_bulk.return_value = {}
    def positions(size, stamp):
        return {address: {**account(stamp, position(size, liq=90000)), "av": 100000, "lev": 10,
                          "net": size * 100000, "pos": [("BTC", 1, size * 100000)], "sizes": {"BTC": size}}
                for address in addresses}
    sm._client.slim_accounts_bulk.side_effect = [positions(5, now - 1200), positions(11, now)]
    with TestClient(api.app) as client:
        assert client.get("/notable-feed").json()["status"] == "waiting"
        orc.run_cycle()
        orc.run_cycle()
        assert [call.args[0] for call in sm._client.slim_accounts_bulk.call_args_list] == [addresses, addresses]
        feed = client.get("/notable-feed", params={"coin": "BTC", "limit": 1}).json()
        assert feed["status"] == "ok" and feed["coins"] == ["BTC"] and len(feed["events"]) == 1
        assert client.get("/notable-feed", params={"coin": "ETH"}).json()["events"] == []
        assert client.get("/notable-feed", params={"limit": 101}).status_code == 422
        result = client.get("/liquidation-map").json()
        assert result["scope"] == "tracked_accounts" and result["covered_accounts"] == 3
        assert result["status"] == "ok" and result["price"] == 100000
        assert client.get("/liquidation-map", params={"coin": "SOL"}).status_code == 422
    sm.close()
