import time
from types import SimpleNamespace as NS
from unittest.mock import Mock
import httpx
import pytest
from crypig.clients.hyperliquid import HyperliquidClient
from crypig.storage.quotes import QuoteStore
from crypig.orchestrator import Orchestrator
from crypig.agents.whale import WhaleAgent

@pytest.fixture
def shared(tmp_path,monkeypatch):
    clock=[time.time()]; calls=[]; status=[200]; funding=[0.0]
    monkeypatch.setattr('crypig.storage.quotes.time.time',lambda:clock[0])
    def handler(r):
        calls.append(r)
        return httpx.Response(status[0],json=[{'universe':[{'name':'ETH'}]},[{'funding':str(funding[0]),'openInterest':'10','markPx':'100','premium':'0'}]])
    client=HyperliquidClient();client._client.close();client._client=httpx.Client(transport=httpx.MockTransport(handler));client._mc_ttl=0
    store=QuoteStore(tmp_path/'quotes.json',loader=client.funding_scan)
    whale=object.__new__(WhaleAgent);whale._cycle_derivatives={'ETH':{'open_interest_usd':1000}};whale._store=Mock(latest=lambda *a:None);whale._hl=Mock(funding_scan=Mock(side_effect=AssertionError('duplicate')))
    sm=NS(name='smart_money',_coin_aggregates=lambda:{},_trader_summary={},_client=whale._hl)
    orc=object.__new__(Orchestrator);orc.config=NS(use_mock=False,agents=NS(smart_money=None));orc.quotes=store;orc.agents=[sm,whale];orc.valuation_times={};orc._prev_pos={};orc.hl_scan=[{'symbol':'OLD'}];orc._divergence_scan=lambda *a:{}
    monkeypatch.setattr('crypig.orchestrator.aggregate',lambda *a:{})
    yield orc,whale,store,clock,calls,status,funding
    client.close()

def test_one_scheduler_request_shared_by_consumers_and_pinned(shared):
    o,w,s,t,c,st,f=shared
    assert s.refresh();o._prepare_cycle_quotes();ts=o.valuation_times['hyperliquid_funding']
    assert w._fetch_market('ETH')['funding_ann']==0
    assert o._compute_all_scores()['ETH']['funding_ann']==0
    assert len(c)==1
    f[0]=.001;t[0]+=60;assert s.refresh()
    assert s.read()[0][0]['funding_ann']>0
    assert w._fetch_market('ETH')['funding_ann']==0
    assert o._compute_all_scores()['ETH']['funding_ann']==0
    assert o.valuation_times['hyperliquid_funding']==ts and len(c)==2
    with pytest.raises(TypeError):o._cycle_quotes['ETH']['funding_ann']=1
    o._prepare_cycle_quotes();assert w._fetch_market('ETH')['funding_ann']>0

def test_cold_and_expired_never_fallback_or_reuse_previous_scan(shared):
    o,w,s,t,c,st,f=shared
    o._prepare_cycle_quotes();assert w._fetch_market('ETH')['funding_ann'] is None
    assert o._compute_all_scores()=={} and o.hl_scan==[] and c==[]
    assert s.refresh();t[0]+=181;st[0]=429;assert not s.refresh()
    o._prepare_cycle_quotes()
    assert o.valuation_times['hyperliquid_funding'] is None
    assert w._fetch_market('ETH')['funding_ann'] is None and o._compute_all_scores()=={}
    assert len(c)==2 and s.read()[1]['refresh_failed']

def test_failed_refresh_preserves_fresh_snapshot_time(shared):
    o,w,s,t,c,st,f=shared
    assert s.refresh();ts=s.read()[1]['fetched_at'];t[0]+=60;st[0]=500;assert not s.refresh()
    o._prepare_cycle_quotes();assert w._fetch_market('ETH')['funding_ann']==0
    assert o.valuation_times['hyperliquid_funding']==ts and s.read()[1]['refresh_failed']
    st[0]=200;f[0]=.001;assert s.refresh();o._prepare_cycle_quotes()
    assert w._fetch_market('ETH')['funding_ann']>0 and not s.read()[1]['refresh_failed']

def test_mock_does_not_read_real_quotes_and_cleanup(shared):
    o,w,s,t,c,st,f=shared;o.config.use_mock=True;s.read=Mock(side_effect=AssertionError('real store'))
    o._prepare_cycle_quotes();assert not o._cycle_quotes and c==[]
    w.end_cycle();assert w._cycle_quotes is None and w._cycle_derivatives is None
