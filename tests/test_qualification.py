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
        entered.set();assert gate.wait(3);return {'new':record(pnl=500)}
    worker.winrate_bulk.side_effect=fills
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
        assert worker.winrate_bulk.call_count==1
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
    worker.winrate_bulk.return_value={'bad':record(pnl=-1)}
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
