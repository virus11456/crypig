import time
from threading import Event
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest
from fastapi.testclient import TestClient
from crypig.dashboard import api
from crypig.dashboard.cache import SnapshotCache
from crypig.clients.hyperliquid import HyperliquidClient
from crypig.clients.defillama import DefiLlamaClient


def wait_until(check):
    deadline = time.monotonic() + 2
    while not check():
        assert time.monotonic() < deadline
        time.sleep(.005)


def test_nonblocking_single_refresh_retains_stale_data_and_backs_off():
    cache = SnapshotCache(retry_seconds=60)
    gate = Event()
    loader = Mock(side_effect=lambda: (gate.wait(2), {"history": [1]})[1])
    try:
        start = time.monotonic()
        for _ in range(20):
            data, meta = cache.read("one", loader, 600)
            assert data is None and meta["refreshing"]
        assert time.monotonic() - start < .3
        gate.set()
        wait_until(lambda: not cache.read("one", loader, 600)[1]["refreshing"])
        assert loader.call_count == 1
        bad = Mock(side_effect=ValueError("upstream unavailable"))
        data, meta = cache.read("one", bad, 0)
        assert data == {"history": [1]} and meta["stale"]
        wait_until(lambda: not cache.read("one", bad, 0)[1]["refreshing"])
        for _ in range(10):
            data, meta = cache.read("one", bad, 0)
            assert data == {"history": [1]} and meta["refresh_failed"]
        assert bad.call_count == 1
    finally:
        gate.set()
        cache.close()


@pytest.fixture
def client(monkeypatch):
    fake = SimpleNamespace(config=SimpleNamespace(use_mock=False), last_result=None,
        macro=None, trader_summary={}, radar={}, all_scores={}, hl_scan=[],
        social={}, fear_greed={}, reddit={}, news={}, defi={}, market_caps={}, deriv_agg={},
        decisions=SimpleNamespace(latest=lambda: []),
        pos_series=SimpleNamespace(history=lambda *a, **kw: [], radar_history=lambda **kw: []),
        run_cycle=Mock(side_effect=AssertionError("GET triggered collection")),
        cycle_status=lambda: {"refreshing": False})
    fake.quotes = SimpleNamespace(read=lambda: (__import__('copy').deepcopy(fake.hl_scan), {}))
    monkeypatch.setattr(api, '_orc', fake)
    # Deliberately do not start scheduler or make any upstream calls.
    return TestClient(api.app), fake


def test_cold_dashboard_reads_never_run_cycle_or_write_history(client, monkeypatch):
    c, fake = client
    monkeypatch.setattr(api, 'hl', Mock(side_effect=AssertionError('Direct upstream call')))
    for route in ['/signal','/decisions','/macro','/positioning','/scores','/hl_market',
                  '/radar','/social','/reddit','/news','/defi']:
        r = c.get(route)
        assert r.status_code == 503, (route, r.text)
        assert r.headers['retry-after'] == '30'
    for route in ['/whale_history','/radar_history']:
        assert c.get(route).json()['history'] == []
    fake.run_cycle.assert_not_called()


def test_limits_reject_unbounded_database_queries(client):
    c, _ = client
    for route in ['/whale_history?limit=-1','/whale_history?limit=999999',
                  '/whale_history?cohort=unknown','/radar_history?limit=0',
                  '/decisions/history?limit=-1']:
        assert c.get(route).status_code == 422


def test_oi_provenance_and_zero_values(client):
    c, fake = client
    fake.hl_scan = [{'symbol':'BTC','open_interest_usd':100}, {'symbol':'ETH','open_interest_usd':0}]
    fake.market_caps = {'BTC':{'market_cap':1000,'volume_24h':20}, 'ETH':{'market_cap':200,'volume_24h':0}}
    fake.deriv_agg = {'BTC':{'open_interest_usd':400}}
    rows = c.get('/hl_market').json()['coins']
    assert rows[0]['hl_open_interest_usd'] == 100
    assert rows[0]['open_interest_source'] == 'coingecko_aggregated'
    assert rows[0]['oi_cap'] == .4
    assert rows[1]['open_interest_source'] == 'hyperliquid'
    assert rows[1]['oi_cap'] == 0
    assert rows[1]['vol_cap'] == 0
    assert fake.hl_scan[0]['open_interest_usd'] == 100


def test_html_is_compressed(client):
    c, _ = client
    r = c.get('/', headers={'Accept-Encoding':'gzip'})
    assert r.headers['content-encoding'] == 'gzip'
    assert 'apiJSON' in r.text


def test_daily_candles_are_closed_sorted_deduplicated_and_reused(monkeypatch):
    client = HyperliquidClient()
    day_ms = 86400000
    now = 60 * day_ms + 1000
    monkeypatch.setattr('crypig.clients.hyperliquid.time.time', lambda: now / 1000)
    data = [{'t':i*day_ms,'c':str(i+1),'v':'5'} for i in range(16,61)]
    data = list(reversed(data)) + [data[0]]
    calls = []
    client._client.close()
    client._client = httpx.Client(transport=httpx.MockTransport(lambda request: (calls.append(request),httpx.Response(200,json=data))[1]))
    try:
        a = client.daily_closes_bulk(['BTC'],workers=1)
        b = client.daily_closes_bulk(['BTC'],workers=1)
        assert a == b
        assert a['BTC'][0][-1] == 60  # day 60 candle is still open
        assert a['BTC'][0] == sorted(a['BTC'][0])
        assert len(calls) == 1
        now += day_ms
        client.daily_closes_bulk(['BTC'],workers=1)
        assert len(calls) == 2
    finally:
        client.close()


def test_daily_candle_failure_is_not_cached(monkeypatch):
    client = HyperliquidClient()
    client._client.close()
    client._client = httpx.Client(transport=httpx.MockTransport(lambda r:httpx.Response(429,json={})))
    assert client.daily_closes_bulk(['BTC'],workers=1) == {}
    assert client._daily_cache == {}
    client.close()


def test_stablecoins_reject_bad_response_and_keep_unrounded_sorted_history():
    client = DefiLlamaClient()
    client._client.close()
    data = [{'date':'200','totalCirculatingUSD':{'peggedUSD':10.25}},
            {'date':'100','totalCirculatingUSD':{'peggedUSD':9.15}},
            {'date':'300','totalCirculatingUSD':{'peggedUSD':'NaN'}}]
    client._client = httpx.Client(transport=httpx.MockTransport(lambda r:httpx.Response(200,json=data)))
    assert client.stablecoin_history() == [{'t':100,'v':9.15},{'t':200,'v':10.25}]
    client._client.close()
    client._client = httpx.Client(transport=httpx.MockTransport(lambda r:httpx.Response(429,json={})))
    with pytest.raises(httpx.HTTPStatusError):
        client.stablecoin_history(ttl=0)
    client.close()


def test_onchain_does_not_treat_missing_band_as_zero(client, monkeypatch):
    _, _ = client
    monkeypatch.setattr(api, '_btcdata', SimpleNamespace(fetch_history=lambda *a, **k:[
        {'theDate':'2026-09-02','whaleBtc':10,'humpbackBtc':20},
        {'theDate':'2026-09-01','whaleBtc':10},
        {'theDate':'2026-09-03','whaleBtc':'NaN','humpbackBtc':20}]))
    assert api._load_onchain_whale()['history'] == [
        {'date':'2026-09-02','btc':30,'whale':10,'humpback':20,'price':None}]


def test_quote_store_retains_valid_snapshot_and_reloads_after_restart(tmp_path):
    from crypig.storage.quotes import QuoteStore
    row = dict(symbol='BTC', price=100, open_interest_usd=0, funding_ann=0, premium=0)
    loader = Mock(return_value=[row])
    path = tmp_path / 'quotes.json'
    store = QuoteStore(path, loader)
    assert store.refresh()
    coins, meta = store.read()
    coins[0]['price'] = 999
    assert store.read()[0][0]['price'] == 100
    loader.return_value = [{**row, 'price': float('nan')}]
    assert not store.refresh()
    assert store.read()[0][0]['price'] == 100
    assert store.read()[1]['refresh_failed']
    restored = QuoteStore(path, loader)
    assert restored.read()[0][0]['price'] == 100
    assert restored.read()[1]['fetched_at'] == meta['fetched_at']
    path.write_text('{"coins":["broken"],"fetched_at":1}')
    assert QuoteStore(path).read()[0] == []


def test_quote_refresh_is_nonblocking_and_preserves_timestamp_on_failure(tmp_path):
    from crypig.storage.quotes import QuoteStore
    store = QuoteStore(tmp_path / 'quotes.json', Mock(side_effect=RuntimeError('offline')))
    store._refresh_lock.acquire()
    try:
        assert store.refresh() is False
        assert store.read()[1]['refreshing']
    finally:
        store._refresh_lock.release()
    assert not store.refresh()
    assert store.read()[1]['fetched_at'] is None
    assert store.read()[1]['stale']


def test_market_ids_reject_namesakes_and_ambiguous_symbols():
    from crypig.clients.market_data import MarketDataClient
    def row(symbol, cid, cap=100, volume=0):
        return dict(symbol=symbol, id=cid, market_cap=cap, total_volume=volume)
    result = MarketDataClient.normalize_markets([
        row('btc','fake-bitcoin',10000), row('btc','bitcoin'),
        row('eth','fake-ethereum'), row('abc','abc-one'), row('abc','abc-two'),
        row('xyz','xyz',volume=None), row('bad','bad',cap=float('nan'))])
    assert result['BTC']['asset_id'] == 'bitcoin'
    assert result['BTC']['match_method'] == 'asset_id'
    assert result['BTC']['volume_24h'] == 0
    assert 'ETH' not in result and 'ABC' not in result and 'BAD' not in result
    assert result['XYZ']['volume_24h'] is None
    assert result['XYZ']['match_method'] == 'symbol_candidate'


def test_market_http_error_preserves_cache_and_original_timestamp():
    from crypig.clients.market_data import MarketDataClient
    c = MarketDataClient()
    try:
        c._top_cache = {'BTC': {'market_cap':100}}
        c._top_ts = 12
        response = Mock()
        response.raise_for_status.side_effect = ValueError('rate limited')
        c._client.get = Mock(return_value=response)
        assert c.top_markets(ttl=0) == {'BTC': {'market_cap':100}}
        assert c._top_ts == 12
    finally:
        c._client.close()


def test_delisted_contexts_are_excluded_without_shifting_symbol_alignment():
    from crypig.clients.hyperliquid import HyperliquidClient
    c = HyperliquidClient()
    response = Mock()
    response.json.return_value = [{'universe':[{'name':'OLD','isDelisted':True},{'name':'BTC'}]},
        [{'markPx':'123'}, {'markPx':'50000','funding':'0','openInterest':'2','premium':'0'}]]
    try:
        c._client.post = Mock(return_value=response)
        rows = c.funding_scan()
        assert len(rows) == 1 and rows[0]['symbol'] == 'BTC'
        assert rows[0]['price'] == 50000 and rows[0]['open_interest_usd'] == 100000
        c._mc_ttl = 0
        response.json.return_value[1].pop()
        with pytest.raises(ValueError, match='Incomplete'):
            c.market_contexts()
    finally:
        c.close()
