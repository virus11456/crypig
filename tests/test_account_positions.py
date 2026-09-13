from crypig.storage.account_positions import AccountPositions, action
import pytest


def groups(rows):
    return {'smart_verified':rows,'smart_pnl_only':{},'whale':{}}


def point(btc, ts=1000):
    return {'btc':btc,'observed_at':ts}


def test_same_accounts_exclude_failures_and_roster_changes(tmp_path):
    s=AccountPositions(tmp_path/'a.db')
    s.record(1000,groups({'a':point(2),'b':point(-4),'c':point(3),'exit':point(50),'empty':point(0)}))
    r=s.record(2200,groups({'a':point(3),'b':point(-2),'c':None,'new':point(100),'empty':point(0)}))['smart_verified']['previous']
    assert r['matched']==3 and r['entered']==1 and r['exited']==1 and r['unobserved']==1
    assert r['long_change_btc']==1 and r['short_change_btc']==-2
    assert r['net_change_btc']==3 and r['changed']==2 and r['counts']['unchanged']==1
    assert {x['address']:x['action'] for x in r['rows']}=={'a':'add_long','b':'reduce_short'}
    assert r['failed']==1 and r['received']==4
    assert AccountPositions(tmp_path/'a.db').compare('smart_verified')['net_change_btc']==3


@pytest.mark.parametrize('before,after,expected',[(0,1,'open_long'),(0,-1,'open_short'),(1,0,'close_long'),(-1,0,'close_short'),(-1,2,'flip_long'),(2,-1,'flip_short'),(1,2,'add_long'),(2,1,'reduce_long'),(-1,-2,'add_short'),(-2,-1,'reduce_short'),(3,3,'unchanged')])
def test_quantity_actions(before,after,expected):
    assert action(before,after)==expected


def test_missing_period_does_not_substitute_shorter_history(tmp_path):
    s=AccountPositions(tmp_path/'a.db')
    assert s.record(1000,groups({'a':point(2)}))['smart_verified']['previous']['status']=='waiting'
    r=s.record(2200,groups({'a':point(2)}))['smart_verified']
    assert r['24h']['status']=='waiting' and r['7d']['status']=='waiting'
    r=s.record(87400,groups({'a':point(4)}))['smart_verified']['24h']
    assert r['baseline_at']==1000 and r['long_change_btc']==2
    assert s.compare('smart_verified','24h',2200)['status']=='waiting'


def test_group_migration_is_not_position_change_and_missing_history_is_null(tmp_path):
    s=AccountPositions(tmp_path/'a.db')
    s.record(1000,groups({'a':point(1)}))
    g=groups({});g['smart_pnl_only']={'a':point(1)};s.record(2200,g)
    r=s.compare('smart_verified');assert r['matched']==0 and r['exited']==1
    h=s.history('a','smart_verified',2200)
    assert h[-1]['btc'] is None and h[-1]['status']=='not_selected'
    s.record(3400,groups({'a':None}))
    assert s.history('a','smart_verified',3400)[-1]['status']=='failed'


def test_price_change_does_not_create_quantity_activity(tmp_path):
    from crypig.clients.hyperliquid import HyperliquidClient
    from unittest.mock import Mock
    c=HyperliquidClient();s=AccountPositions(tmp_path/'a.db')
    try:
        for ts,price in [(1000,60000),(2200,70000)]:
            c._post_info=Mock(return_value={'marginSummary':{'accountValue':'100000','totalNtlPos':str(price*2)},'assetPositions':[{'position':{'coin':'BTC','szi':'2','positionValue':str(price*2)}}]})
            a=c.slim_account('a');s.record(ts,groups({'a':point(a['sizes']['BTC'])}))
        assert s.compare('smart_verified')['changed']==0
        assert s.compare('smart_verified')['net_change_btc']==0
    finally:c.close()


def test_invalid_batch_cannot_replace_saved_data(tmp_path):
    s=AccountPositions(tmp_path/'a.db');s.record(1000,groups({'a':point(1)}))
    with pytest.raises(ValueError):s.record(2200,groups({'a':point(float('nan'))}))
    assert s.compare('smart_verified')['as_of']==1000


def test_account_api_pins_completed_sample_and_validates_input(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from fastapi.testclient import TestClient
    from crypig.dashboard import api
    address='0x'+'a'*40
    s=AccountPositions(tmp_path/'account_positions.db')
    data=s.record(1000,groups({address:point(2)}))
    s.record(2200,groups({address:point(3)}))
    view=SimpleNamespace(trader_summary={'account_activity':{'groups':data}},config=SimpleNamespace(posseries_db=str(tmp_path/'posseries.db')))
    monkeypatch.setattr(api,'dashboard_state',lambda:view)
    client=TestClient(api.app)
    assert client.get('/account_activity').json()['groups']['smart_verified']['previous']['as_of']==1000
    result=client.get('/account_history',params={'address':address}).json()
    assert len(result['history'])==1 and result['history'][0]['btc']==2
    assert client.get('/account_history',params={'address':'bad'}).status_code==422
    assert client.get('/account_history',params={'address':address,'cohort':'wrong'}).status_code==422
