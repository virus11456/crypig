import json
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Event
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest
from fastapi import HTTPException

from crypig.agents.lth import LTHAgent
from crypig.clients.lth_history import SLUG, build_lth
from crypig.config import Config
from crypig.dashboard import api
from crypig.storage.lth_supply import KEY, LTHSupply

NOW = datetime(2026, 9, 14, 10, tzinfo=timezone.utc).timestamp()


def wait_for(check):
    deadline = time.monotonic() + 2
    while not check():
        assert time.monotonic() < deadline
        time.sleep(.005)


@pytest.fixture
def source(tmp_path, monkeypatch):
    clock = [NOW]
    monkeypatch.setattr(time, 'time', lambda: clock[0])
    class ClockDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.fromtimestamp(clock[0], tz)
    monkeypatch.setattr('crypig.clients.lth_history.datetime', ClockDateTime)
    payload = [[{'d': '2026-09-12', 'longTermHodlerSupplyBtc': 100},
                {'d': '2026-09-13', 'longTermHodlerSupplyBtc': 101}]]
    code = [200]
    calls = []
    gate = Event(); gate.set()
    def get(request):
        calls.append(request.url.path)
        gate.wait(2)
        return httpx.Response(code[0], json=payload[0])
    clients = []
    def client():
        from crypig.clients.bitcoin_data import BitcoinDataClient
        c = BitcoinDataClient(); c._client.close()
        c._client = httpx.Client(transport=httpx.MockTransport(get))
        clients.append(c)
        return c
    monkeypatch.setattr('crypig.storage.lth_supply.BitcoinDataClient', client)
    store = LTHSupply(tmp_path/'history_cache')
    agent = LTHAgent(Config(use_mock=False, snapshot_db=str(tmp_path/'agent.db')), history=store)
    monkeypatch.setattr(api, '_orc', SimpleNamespace(config=SimpleNamespace(use_mock=False), lth_supply=store))
    yield store, agent, clock, payload, code, calls, gate
    gate.set(); store.close()
    for c in clients: c.close()


def settled(store):
    wait_for(lambda: not store.read()[1]['refreshing'])
    return store.read()


def test_agent_and_api_share_one_nonblocking_http_fetch(source):
    store, agent, clock, payload, code, calls, gate = source
    gate.clear()
    raw = agent.fetch('BTC')
    assert raw['lth_supply'] is None
    with pytest.raises(HTTPException) as error:
        api.lth_history()
    assert error.value.status_code == 503
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: agent.fetch('BTC'), range(20)))
    assert all(r['lth_supply'] is None for r in results)
    gate.set()
    data, meta = settled(store)
    assert calls == ['/v1/' + SLUG]  # Never /last, including agent reads.
    assert agent.fetch('BTC')['lth_supply'] == api.lth_history()['balance_btc'] == 101
    assert meta['source_date'] == '2026-09-13' and meta['source_age_days'] == 1
    fetched = meta['updated_at']
    clock[0] += 1200
    for _ in range(10):
        agent.fetch('BTC'); api.lth_history()
    assert len(calls) == 1
    assert store.read()[1]['updated_at'] == fetched
    data['history'][-1]['btc'] = 999
    assert agent.fetch('BTC')['lth_supply'] == 101


def test_expiry_failure_backoff_and_recovery_preserve_original_date_and_time(source):
    store, agent, clock, payload, code, calls, gate = source
    data, meta = settled(store)
    fetched = meta['updated_at']
    code[0] = 429; clock[0] += 21601
    data, meta = settled(store)
    assert meta['refresh_failed'] and meta['stale']
    assert meta['updated_at'] == fetched and data['as_of'] == '2026-09-13'
    raw = agent.fetch('BTC'); obs = agent.analyze('BTC', raw)
    assert raw['lth_supply'] == 101 and obs.status == 'informational'
    assert '更新失敗' in obs.summary and obs.magnitude == 0
    for _ in range(10): api.lth_history(); agent.fetch('BTC')
    assert len(calls) == 2
    clock[0] += 3601; code[0] = 200
    payload[0].append({'d':'2026-09-14','longTermHodlerSupplyBtc':102})
    data, meta = settled(store)
    assert len(calls) == 3 and not meta['refresh_failed']
    assert data['balance_btc'] == 102 and meta['updated_at'] > fetched


def test_utc_rollover_refreshes_before_six_hours(source):
    store, agent, clock, payload, code, calls, gate = source
    clock[0] = datetime(2026,9,14,23,50,tzinfo=timezone.utc).timestamp()
    settled(store)
    clock[0] += 1200
    settled(store)
    assert len(calls) == 2


def test_restores_deployed_cache_and_rejects_inconsistent_snapshot(source):
    store, agent, clock, payload, code, calls, gate = source
    data, meta = settled(store)
    again = LTHSupply(store._cache.directory)
    try:
        assert again.read()[0] == data
        assert again.read()[1]['updated_at'] == meta['updated_at']
        assert len(calls) == 1
    finally: again.close()
    path = store._cache._path(KEY)
    saved = json.loads(path.read_text()); saved['data']['balance_btc'] = 999
    path.write_text(json.dumps(saved))
    bad = LTHSupply(store._cache.directory)
    try:
        assert bad.read()[0] is None
        assert settled(bad)[0]['balance_btc'] == 101
    finally: bad.close()


def test_source_regression_and_conflicts_retain_last_good_snapshot(source):
    store, agent, clock, payload, code, calls, gate = source
    data, meta = settled(store)
    original = payload[0]
    for bad in [original[:1], original + [{'d':'2026-09-13','longTermHodlerSupplyBtc':9}], []]:
        payload[0] = bad; clock[0] += 21601
        result, current = settled(store)
        assert current['refresh_failed'] and current['updated_at'] == meta['updated_at']
        assert result == data


def test_future_days_and_missing_calendar_dates_are_not_fabricated(source):
    store, agent, clock, payload, code, calls, gate = source
    payload[0] = [{'d':'2026-09-11','longTermHodlerSupplyBtc':100},
                  {'d':'2026-09-13','longTermHodlerSupplyBtc':0},
                  {'d':'2099-01-01','longTermHodlerSupplyBtc':200}]
    data, meta = settled(store)
    assert data['balance_btc'] == 0 and data['changes_btc']['1'] is None
    assert len(data['history']) == 2
    assert agent.fetch('BTC')['lth_supply'] == 0


def test_orchestrator_injects_shared_service_and_mock_never_reads_it(tmp_path):
    from crypig.orchestrator import Orchestrator
    cfg = Config(use_mock=True, decisions_db=str(tmp_path/'decisions.db'),
                 snapshot_db=str(tmp_path/'snapshots.db'), posseries_db=str(tmp_path/'positions.db'),
                 kg={'path':str(tmp_path/'kg.json')},
                 agents={k:{'enabled':False} for k in ['smart_money','whales','divergence']})
    orc = Orchestrator(cfg)
    try:
        agent = next(a for a in orc.agents if isinstance(a,LTHAgent))
        assert agent._history is orc.lth_supply
        orc.lth_supply.read = Mock(side_effect=AssertionError('Mock made a real source read'))
        assert agent.fetch('BTC')['lth_supply'] is not None
        orc.lth_supply.read.assert_not_called()
    finally: orc.lth_supply.close()
