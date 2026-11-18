import time
from threading import Event
from unittest.mock import Mock
from crypig.config import Config
from crypig.agents.smart_money import SmartMoneyAgent
from crypig.storage.pos_series import PosSeriesStore
import crypig.agents.smart_money as module


def record(ts=None, pnl=20):
    return {'ts':ts or time.time(),'win_rate':.6,'recent_pnl':pnl,'trades':100,'span_hours':100}


def test_positions_finish_before_qualification_and_selection_is_frozen(tmp_path,monkeypatch):
    cfg=Config(posseries_db=str(tmp_path/'pool.db'))
    cfg.agents.smart_money.max_traders=2
    cfg.agents.smart_money.whale_full_market=False
    store=PosSeriesStore(cfg.posseries_db);store.upsert_smart_pool({'old':record()});store.close()
    gate=Event();entered=Event()
    worker=Mock();worker.top_traders.return_value=[('new',100)]
    def fills(*args,**kwargs):
        entered.set();assert gate.wait(3);return {'new':{'status':'ok','stats':record(pnl=500)}}
    worker.qualification_bulk.side_effect=fills
    monkeypatch.setattr(module,'HyperliquidClient',lambda:worker)
    agent=SmartMoneyAgent(cfg);client=Mock();agent._client=client
    client.top_traders.return_value=[('fallback',99)]
    client.slim_accounts_bulk.side_effect=lambda addresses:{a:{'av':100,'lev':1,'net':10,'pos':[('BTC',1,10)]} for a in addresses}
    try:
        agent.begin_cycle()
        result=agent._coin_aggregates();assert entered.wait(1)
        assert result['BTC']['count']==2 and not gate.is_set()
        assert agent.qualification_status()['refreshing']
        assert {x['addr'] for x in agent._smart_sel}=={'old','fallback'}
        for _ in range(5):agent._schedule_qualification(cfg.agents.smart_money)
        assert worker.qualification_bulk.call_count==1
        gate.set();agent._qualification_future.result(3)
        assert {x['addr'] for x in agent._smart_sel}=={'old','fallback'}
        agent._agg_ts=0;agent._coin_aggregates()
        assert {x["addr"] for x in agent._smart_sel}=={"old","fallback"}
        agent.end_cycle();agent.begin_cycle();agent._coin_aggregates()
        assert {x['addr'] for x in agent._smart_sel}=={'old','new'}
        assert agent._trader_summary['qualification']['pnl_only']==0
        assert agent.qualification_status()['requested']==1 # no duplicate batch when fewer candidates
    finally:
        gate.set();agent._qualification_executor.shutdown(wait=True);agent._pool_store().close()


def test_failed_worker_retains_original_dates_and_expired_entries_are_not_qualified(tmp_path,monkeypatch):
    cfg=Config(posseries_db=str(tmp_path/'pool.db'));store=PosSeriesStore(cfg.posseries_db)
    stamp=time.time()-20
    store.upsert_smart_pool({'valid':record(stamp),'expired':record(time.time()-100000),'future':record(time.time()+100000)})
    worker=Mock();worker.top_traders.side_effect=RuntimeError('unavailable')
    monkeypatch.setattr(module,'HyperliquidClient',lambda:worker)
    agent=SmartMoneyAgent(cfg)
    try:
        agent._refresh_qualification(cfg.agents.smart_money)
        assert agent.qualification_status()['failed']
        current=store.load_smart_pool(28800,time.time())
        assert set(current)=={'valid'} and current['valid']['ts']==stamp
    finally:
        agent.close();store.close()


def test_completed_negative_qualification_revokes_old_entry_but_missing_retains_date(tmp_path,monkeypatch):
    cfg=Config(posseries_db=str(tmp_path/'pool.db'));store=PosSeriesStore(cfg.posseries_db)
    stamp=time.time()-100;store.upsert_smart_pool({'bad':record(stamp),'missing':record(stamp)})
    worker=Mock();worker.top_traders.return_value=[('bad',10),('missing',10)]
    worker.qualification_bulk.return_value={'bad':{'status':'ok','stats':record(pnl=-1)},'missing':{'status':'request_failed'}}
    monkeypatch.setattr(module,'HyperliquidClient',lambda:worker)
    agent=SmartMoneyAgent(cfg)
    try:
        agent._refresh_qualification(cfg.agents.smart_money)
        current=store.load_smart_pool(28800,time.time())
        assert set(current)=={'missing'} and current['missing']['ts']==stamp
        assert agent.qualification_status()['unavailable']==1
        assert agent.qualification_status()['rejected']==1
    finally:
        agent.close();store.close()


def test_fill_outcomes_separate_empty_unscored_rate_limit_and_invalid(monkeypatch):
    import httpx
    from crypig.clients.hyperliquid import HyperliquidClient
    client=HyperliquidClient()
    def fills(addr):
        if addr=='empty':return []
        if addr=='zero':return [{'closedPnl':'0','time':1000}]
        if addr=='invalid':return [{'closedPnl':'nan','time':1000}]
        if addr=='limited':
            r=httpx.Response(429,request=httpx.Request('POST','https://api.hyperliquid.xyz/info'))
            raise httpx.HTTPStatusError('limit',request=r.request,response=r)
        if addr=='failed':raise httpx.ReadTimeout('timeout')
        return [{'closedPnl':'2','time':1000}]
    monkeypatch.setattr(client,'user_fills',fills)
    try:
        r=client.qualification_bulk(['empty','zero','invalid','limited','failed','valid'],rate_per_min=0)
        assert {a:x['status'] for a,x in r.items()}=={'empty':'no_fills','zero':'no_scored_closes','invalid':'invalid_data','limited':'rate_limited','failed':'request_failed','valid':'ok'}
        assert client.winrate_bulk(['zero','valid'])=={'valid':r['valid']['stats']}
    finally:client.close()


def test_recent_fill_sample_is_chronological_and_malformed_payload_is_not_empty(monkeypatch):
    from crypig.clients.hyperliquid import HyperliquidClient
    import pytest
    r=HyperliquidClient.fills_winrate([{'closedPnl':'100','time':1000},{'closedPnl':'-1','time':3000},{'closedPnl':'2','time':2000}],2)
    assert r['recent_pnl']==1 and r['win_rate']==.5
    client=HyperliquidClient();monkeypatch.setattr(client,'_post_info',lambda _: {'error':'unavailable'})
    try:
        with pytest.raises(ValueError):client.user_fills('addr')
    finally:client.close()


def test_successful_empty_histories_are_not_classified_as_outage(tmp_path,monkeypatch):
    cfg=Config(posseries_db=str(tmp_path/'pool.db'))
    worker=Mock();worker.top_traders.return_value=[('a',10)]
    worker.qualification_bulk.return_value={'a':{'status':'no_fills'}}
    monkeypatch.setattr(module,'HyperliquidClient',lambda:worker)
    agent=SmartMoneyAgent(cfg)
    try:
        agent._refresh_qualification(cfg.agents.smart_money)
        q=agent.qualification_status();assert not q['failed'] and not q['partial_failure']
        assert q['reasons']=={'no_fills':1} and q['qualified']==0 and q['observed']==0
    finally:agent.close()


def test_qualification_subsets_have_independent_directions_and_statistic_coverage():
    verified={'net':10,'lev':1,'win_rate':.8,'pos':[('BTC',1,120),('ETH',-1,30)]}
    fallback={'net':-20,'lev':2,'win_rate':None,'pos':[('BTC',-1,500)]}
    r=SmartMoneyAgent._summarize_traders([verified,fallback],[verified,fallback])
    assert r['smart']['winrate_accounts']==1 and r['smart']['total']==2
    assert r['smart_verified']['long_pct']==1 and r['smart_pnl_only']['short_pct']==1
    assert r['smart_verified']['btc']=={'accounts':1,'long_usd':120,'short_usd':0}
    assert r['smart_pnl_only']['btc']['short_usd']==500
    assert r['smart_pnl_only']['winrate_median'] is None
    empty=SmartMoneyAgent._summarize_traders([],[])['smart_verified']
    assert empty['long_pct'] is None and empty['btc']['accounts']==0


def test_zero_net_keeps_offset_positions_separate_from_empty_and_unknown():
    common={'net':0,'lev':1,'win_rate':None}
    r=SmartMoneyAgent._summarize_traders([{**common,'pos':[]},{**common,'pos':[('BTC',1,100),('ETH',-1,100)]},common],[])['smart']
    assert r['flat']==3 and r['no_positions']==1 and r['offset_positions']==1 and r['flat_unknown']==1
    assert r['long_pct'] is None and r['btc']['accounts']==1


def test_invalid_account_payload_is_not_an_empty_success(monkeypatch):
    from crypig.clients.hyperliquid import HyperliquidClient
    import pytest
    c=HyperliquidClient()
    valid={'marginSummary':{'accountValue':'100','totalNtlPos':'0'},'assetPositions':[]}
    monkeypatch.setattr(c,'_post_info',lambda _: valid)
    try:
        assert c.slim_account('a')['pos']==[]
        for bad in [{}, {'error':'busy'}, {**valid,'assetPositions':None}, {**valid,'marginSummary':{'accountValue':'nan','totalNtlPos':'0'}}, {**valid,'assetPositions':[{'position':{'coin':'BTC','szi':'1','positionValue':'0'}}]}]:
            monkeypatch.setattr(c,'_post_info',lambda _,b=bad:b)
            with pytest.raises((ValueError,TypeError,KeyError)): c.slim_account('a')
        assert c.slim_accounts_bulk(['a'])=={}
    finally:c.close()
