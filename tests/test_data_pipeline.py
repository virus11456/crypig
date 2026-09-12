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
        snapshot_decisions=[], decisions=SimpleNamespace(latest=lambda: []),
        pos_series=SimpleNamespace(history=lambda *a, **kw: [], radar_history=lambda **kw: []),
        run_cycle=Mock(side_effect=AssertionError("GET triggered collection")),
        cycle_status=lambda: {"refreshing": False})
    fake.dashboard_state = lambda: fake
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
    fake.hl_scan = [{'symbol':'BTC','price':100,'open_interest_usd':100}, {'symbol':'ETH','price':20,'open_interest_usd':0}]
    fake.market_caps = {'BTC':{'market_cap':1000,'volume_24h':20,'reference_price':100}, 'ETH':{'market_cap':200,'volume_24h':0,'reference_price':20}}
    fake.deriv_agg = {'BTC':{'open_interest_usd':400,'reference_price':100}}
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
    from crypig.clients.btc_cohorts import normalize, build_cohorts
    a = normalize([{'d':'2026-09-02','v':10}, {'d':'2026-09-01'},
                   {'d':'2026-09-03','v':'NaN'}], 'v')
    data = build_cohorts([a, {'2026-09-01':20, '2026-09-02':20}])
    assert data['history'] == [{'date':'2026-09-02','btc':30,'whale':10,'humpback':20}]
    assert data['changes_btc']['1'] is None


def test_cohort_changes_use_exact_calendar_dates():
    from crypig.clients.btc_cohorts import build_cohorts
    a = {'2026-08-12':100, '2026-09-04':110, '2026-09-10':120, '2026-09-11':115}
    b = {'2026-08-12':200, '2026-09-04':210, '2026-09-10':220, '2026-09-11':225}
    d = build_cohorts([a,b])
    assert d['changes_btc'] == {'1':0, '7':20, '30':40}
    assert d['cohorts'][0]['changes_btc']['1'] == -5
    assert d['cohorts'][1]['changes_btc']['1'] == 5


def test_unverified_wallet_series_cannot_vote(client):
    from crypig.agents.whale import WhaleAgent
    a = object.__new__(WhaleAgent)
    assert a._fetch_whale_wallets('BTC', None)['whale_btc'] is None


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


def test_valuation_age_with_warm_market_data(client):
    c, fake = client
    fake.hl_scan = [{'symbol':'BTC','open_interest_usd':100}]
    fake._md = SimpleNamespace(_top_ts=time.time()-2500, _deriv_ts=time.time()-10)
    response = c.get('/hl_market')
    assert response.status_code == 200
    meta = response.json()['meta']['valuations']
    assert meta['market_caps']['stale']
    assert not meta['aggregate_oi']['stale']
    assert meta['market_caps']['age_seconds'] >= 2500


def test_derivatives_filter_invalid_and_duplicate_contracts():
    from crypig.clients.market_data import MarketDataClient
    now=200000
    def row(symbol='BTCUSDT', **extra):
        return dict(dict(market='Exchange',symbol=symbol,index_id='BTC',contract_type='perpetual',
                         open_interest=100,last_traded_at=now-10,expired_at=None,price='50000',funding_rate=0),**extra)
    rows=[row(),row(open_interest=120,last_traded_at=now-1),row('NEG',open_interest=-1),
          row('NAN',open_interest=float('nan')),row('OLD',last_traded_at=now-86401),
          row('EXP',expired_at=now-1),row('FUT',contract_type='futures'),row('ZERO',open_interest=0)]
    result=MarketDataClient.normalize_derivatives(rows,now)['BTC']
    assert result['contracts']==2 and result['open_interest_usd']==120
    assert result['unit']=='USD' and result['reference_price']==50000
    with pytest.raises(ValueError):MarketDataClient.normalize_derivatives([row(open_interest=-1)],now)


def test_price_mismatch_rejects_caps_and_falls_back_to_hl(client):
    c,fake=client
    fake.hl_scan=[{'symbol':'BTC','price':100,'open_interest_usd':10}]
    fake.market_caps={'BTC':{'market_cap':1000,'volume_24h':20,'reference_price':1}}
    fake.deriv_agg={'BTC':{'open_interest_usd':999,'reference_price':1}}
    row=c.get('/hl_market').json()['coins'][0]
    assert row['market_cap'] is None and row['oi_cap'] is None
    assert row['open_interest_usd']==10 and row['open_interest_source']=='hyperliquid'


def test_macro_does_not_divide_mixed_underlying_oi_by_crypto_cap():
    from crypig.clients.market_data import MarketDataClient
    c=MarketDataClient()
    try:
        c._client.get=Mock(return_value=Mock(json=lambda:{'data':{'total_market_cap':{'usd':100},'total_volume':{'usd':20}}}))
        c.aggregate_derivatives=Mock(return_value={'STOCK':{'open_interest_usd':50}})
        result=c.global_macro()
        assert result['open_interest']==50 and result['oi_cap'] is None
        assert '非加密' in result['oi_coverage']
    finally:c.close()


def test_new_oi_coverage_does_not_compare_against_legacy_totals():
    from crypig.agents.whale import WhaleAgent
    agent=object.__new__(WhaleAgent)
    agent._client=SimpleNamespace(aggregate_derivatives=lambda:{'ETH':{'open_interest_usd':100,'contracts':2,'funding_rate_med':0}})
    agent._hl=SimpleNamespace(funding_scan=lambda:[{'symbol':'ETH','funding_ann':0}])
    agent._store=Mock()
    agent._store.latest.return_value=None
    raw=agent._fetch_market('ETH')
    agent._store.latest.assert_called_once_with(agent.name,'ETH','open_interest_usd_perpetual_v1')
    assert raw['prev_open_interest_usd'] is None
    agent._analyze_market('ETH',raw)
    assert agent._store.record.call_args.args[2]=='open_interest_usd_perpetual_v1'


def test_missing_observations_do_not_inflate_coverage_or_trigger_alerts():
    from crypig.aggregate import aggregate
    from crypig.storage.models import Observation
    cfg=SimpleNamespace(analyzers=SimpleNamespace(weights={'good':1,'missing':1}))
    good=Observation(source='good',symbol='BTC',signal_type='x',direction='bull',magnitude=1)
    missing=Observation(source='missing',symbol='BTC',signal_type='x',direction='bear',magnitude=1,status='no_data')
    x=aggregate([good,missing],cfg)['BTC']
    assert x['confidence']==0.5 and x['score']==1
    assert x['signals'][1]['weight']==0
    empty=aggregate([missing],cfg)['BTC']
    assert empty['label']=='資料不足' and empty['confidence']==0
    assert empty['action']=='資料不足，等待有效訊號'


def test_whale_missing_oi_is_not_saved_as_zero_and_raw_rates_are_not_annualized():
    from crypig.agents.whale import WhaleAgent
    agent=object.__new__(WhaleAgent);agent._store=Mock()
    x=agent._analyze_market('ETH',{'open_interest_usd':None,'funding_ann':.5})
    assert x.status=='no_data';agent._store.record.assert_not_called()
    x=agent._analyze_market('ETH',{'open_interest_usd':100,'funding_rate_avg':99,'prev_open_interest_usd':50})
    assert x.status=='no_data' and x.direction=='neutral' and x.magnitude==0
    x=agent._analyze_market('ETH',{'open_interest_usd':0,'funding_ann':0,'prev_open_interest_usd':100})
    assert x.status=='ok' and x.direction=='neutral'


def test_whale_uses_explicit_hyperliquid_annual_funding():
    from crypig.agents.whale import WhaleAgent
    agent=object.__new__(WhaleAgent)
    agent._client=SimpleNamespace(aggregate_derivatives=lambda:{'ETH':{'open_interest_usd':100,'funding_rate_med':999}})
    agent._hl=SimpleNamespace(funding_scan=lambda:[{'symbol':'ETH','funding_ann':-.1}])
    agent._store=Mock();agent._store.latest.return_value=None
    raw=agent._fetch_market('ETH')
    assert raw['funding_ann']==-.1 and raw['funding_source']=='hyperliquid_hourly'
    assert agent._analyze_market('ETH',raw).direction=='bull'


def test_persisted_history_restores_without_upstream_and_preserves_age_on_error(tmp_path):
    cache=SnapshotCache(directory=tmp_path)
    loader=Mock(return_value={'history':[{'date':'2026-09-12','value':1}]})
    try:
        cache.read('history',loader,3600)
        wait_until(lambda: not cache.read('history',loader,3600)[1]['refreshing'])
        original=cache.read('history',loader,3600)
    finally:cache.close()
    restored=SnapshotCache(directory=tmp_path)
    failed=Mock(side_effect=ValueError('offline'))
    try:
        data,meta=restored.read('history',failed,3600)
        assert data==original[0] and meta['updated_at']==original[1]['updated_at']
        failed.assert_not_called()
        data,meta=restored.read('history',failed,0)
        assert data==original[0] and meta['stale']
        wait_until(lambda: not restored.read('history',failed,0)[1]['refreshing'])
        assert restored.read('history',failed,0)[1]['updated_at']==original[1]['updated_at']
    finally:restored.close()


def test_manual_collection_cannot_be_triggered_anonymously(client, monkeypatch):
    c, fake=client
    monkeypatch.delenv('CRYPIG_ADMIN_TOKEN',raising=False)
    assert c.post('/cycle').status_code==404
    monkeypatch.setenv('CRYPIG_ADMIN_TOKEN','test-only-token')
    assert c.post('/cycle').status_code==401
    fake.run_cycle.assert_not_called()
    fake.run_cycle.side_effect=None;fake.run_cycle.return_value={'ok':True}
    assert c.post('/cycle',headers={'Authorization':'Bearer test-only-token'}).json()=={'ok':True}


def analysis_orchestrator(tmp_path):
    from crypig.config import Config
    from crypig.orchestrator import Orchestrator
    cfg = Config(use_mock=False, decisions_db=str(tmp_path/'decisions.db'),
                 snapshot_db=str(tmp_path/'snapshots.db'), posseries_db=str(tmp_path/'positions.db'),
                 kg={'path': str(tmp_path/'kg.json')},
                 agents={k: {'enabled': False} for k in ['smart_money','whales','divergence','lth']})
    return Orchestrator(cfg)


def complete_test_analysis(orc, value):
    from datetime import datetime, timezone
    orc.all_scores = {'BTC': {'score': value}}
    orc.radar = {'market': {'gap': value}}
    orc.macro = {'market_cap': value}
    orc.trader_summary = {'smart': {'count': value}}
    return {'ts': datetime.now(timezone.utc).isoformat(), 'signals': {'BTC': {'score': value}}}


def test_completed_analysis_restores_without_upstream_and_keeps_time(tmp_path, monkeypatch):
    orc = analysis_orchestrator(tmp_path)
    monkeypatch.setattr(orc, '_run_cycle_locked', lambda: complete_test_analysis(orc, 1))
    orc.run_cycle()
    restored = analysis_orchestrator(tmp_path)
    assert restored.cycle_status()['last_success_at'] == orc.cycle_status()['last_success_at']
    assert restored.cycle_status()['analysis']['restored']
    monkeypatch.setattr(restored, 'run_cycle', Mock(side_effect=AssertionError('Unexpected collection')))
    monkeypatch.setattr(api, '_orc', restored)
    c = TestClient(api.app)
    for route in ['/signal','/scores','/macro','/radar','/positioning']:
        assert c.get(route).status_code == 200
    assert c.get('/scores').json()['scores']['BTC']['score'] == 1


def test_analysis_readers_keep_completed_generation_during_failed_cycle(tmp_path, monkeypatch):
    orc = analysis_orchestrator(tmp_path)
    monkeypatch.setattr(orc, '_run_cycle_locked', lambda: complete_test_analysis(orc, 1))
    orc.run_cycle()
    previous = orc.dashboard_state()
    def fail():
        complete_test_analysis(orc, 2)
        assert orc.dashboard_state().all_scores['BTC']['score'] == 1
        assert orc.cycle_status()['refreshing']
        raise RuntimeError('Interrupted source')
    monkeypatch.setattr(orc, '_run_cycle_locked', fail)
    with pytest.raises(RuntimeError): orc.run_cycle()
    assert orc.dashboard_state().radar['market']['gap'] == 1
    assert orc.cycle_status()['last_cycle_failed']
    monkeypatch.setattr(orc, '_run_cycle_locked', lambda: complete_test_analysis(orc, 3))
    orc.run_cycle()
    assert previous.all_scores['BTC']['score'] == 1
    assert orc.dashboard_state().all_scores['BTC']['score'] == 3
    assert not orc.cycle_status()['last_cycle_failed']


def test_analysis_disk_failure_keeps_previous_disk_and_publishes_valid_memory(tmp_path, monkeypatch):
    from pathlib import Path
    orc = analysis_orchestrator(tmp_path)
    monkeypatch.setattr(orc, '_run_cycle_locked', lambda: complete_test_analysis(orc, 1))
    orc.run_cycle()
    monkeypatch.setattr(Path, 'replace', Mock(side_effect=OSError('Disk full')))
    monkeypatch.setattr(orc, '_run_cycle_locked', lambda: complete_test_analysis(orc, 2))
    orc.run_cycle()
    assert orc.dashboard_state().all_scores['BTC']['score'] == 2
    assert orc.cycle_status()['analysis']['persist_failed']
    assert analysis_orchestrator(tmp_path).dashboard_state().all_scores['BTC']['score'] == 1


def test_analysis_rejects_corrupt_incompatible_and_future_cache(tmp_path, monkeypatch):
    import json
    from datetime import datetime, timezone, timedelta
    orc = analysis_orchestrator(tmp_path)
    monkeypatch.setattr(orc, '_run_cycle_locked', lambda: complete_test_analysis(orc, 1))
    orc.run_cycle()
    p = orc._analysis_store.path
    valid = json.loads(p.read_text())
    for key, value in [('version', 99), ('config', 'other'), ('completed_at', (datetime.now(timezone.utc)+timedelta(days=1)).isoformat()), ('state', {})]:
        p.write_text(json.dumps({**valid, key: value}))
        assert analysis_orchestrator(tmp_path).dashboard_state().last_result is None
    p.write_text('{truncated')
    assert analysis_orchestrator(tmp_path).dashboard_state().last_result is None
    valid['completed_at'] = (datetime.now(timezone.utc)-timedelta(hours=2)).isoformat()
    p.write_text(json.dumps(valid))
    assert analysis_orchestrator(tmp_path).cycle_status()['analysis']['stale']


def test_defi_changes_use_calendar_days_and_reject_invalid_observations():
    rows = [{'date':86400*i,'tvl':i*10} for i in (1,2,4,9)]
    result = DefiLlamaClient.daily_summary(list(reversed(rows))+[{'date':86400*10,'tvl':float('nan')}],lambda r:r['tvl'])
    assert result['value'] == 90
    assert result['chg_7d'] == 3.5
    assert result['chg_30d'] is None
    missing = DefiLlamaClient.daily_summary([rows[0],rows[-1]],lambda r:r['tvl'])
    assert missing['chg_7d'] is None
    with pytest.raises(ValueError):
        DefiLlamaClient.daily_summary([rows[0],{**rows[0],'tvl':99}],lambda r:r['tvl'])


def test_defi_partial_failure_keeps_each_component_and_original_time():
    previous={'tvl':{'value':100},'chains':[{'name':'Old','tvl':20}],
              'stablecoin':{'value':300},'sources':{k:{'fetched_at':10,'observed_at':86400} for k in ['tvl','chains','stablecoin']}}
    def handler(request):
        if request.url.path=='/v2/chains':
            return httpx.Response(200,json=[{'name':'New','tvl':25}])
        return httpx.Response(503,json={'error':'temporarily unavailable'})
    client=DefiLlamaClient();client._client.close();client._client=httpx.Client(transport=httpx.MockTransport(handler))
    try:
        result=client.snapshot(ttl=0,previous=previous)
        assert result['tvl']['value']==100 and result['stablecoin']['value']==300
        assert result['chains'][0]['name']=='New'
        assert result['sources']['tvl']['refresh_failed']
        assert result['sources']['tvl']['fetched_at']==10
        assert result['sources']['chains']['fetched_at']>10
        assert not result['sources']['chains']['refresh_failed']
        assert previous['chains'][0]['name']=='Old'
    finally: client.close()


def test_defi_source_regression_does_not_replace_newer_data():
    previous={'tvl':{'value':100},'sources':{'tvl':{'fetched_at':10,'observed_at':86400*4}}}
    client=DefiLlamaClient();client._client.close()
    client._client=httpx.Client(transport=httpx.MockTransport(lambda r:httpx.Response(200,json=[{'date':86400,'tvl':5}])))
    try:
        result=client.snapshot(previous=previous)
        assert result['tvl']['value']==100
        assert result['sources']['tvl']['fetched_at']==10
        assert result['sources']['tvl']['refresh_failed']
    finally: client.close()
