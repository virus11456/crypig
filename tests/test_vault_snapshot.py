from types import SimpleNamespace
from unittest.mock import Mock
import httpx
import pytest
from crypig.dashboard import api
from crypig.obsidian import export_vault


def make_orc(stale=False, failed=False, mock=False):
    return SimpleNamespace(config=SimpleNamespace(use_mock=mock),
        quotes=SimpleNamespace(read=Mock(return_value=([
            {'symbol':'BTC','funding_ann':0.0,'open_interest_usd':999},
            {'symbol':'ETH','funding_ann':.1,'open_interest_usd':999}],
            {'source':'hyperliquid','fetched_at':1000,'stale':stale,'refresh_failed':failed}))),
        market_caps={'BTC':{'market_cap':100},'ETH':{'market_cap':100}},
        deriv_agg={'BTC':{'open_interest_usd':0},'ETH':{'open_interest_usd':None}},
        all_scores={'BTC':{},'ETH':{}},pos_series=Mock(history=lambda *a,**kw: [],radar_history=lambda **kw: []),
        radar={},trader_summary={},valuation_times={'aggregate_oi':900,'market_caps':800},
        cycle_status=lambda:{'analysis':{'completed_at':'2026-09-14T00:00:00+00:00'}})


@pytest.mark.parametrize('stale,failed', [(False,False),(False,True),(True,True)])
def test_export_uses_snapshot_without_network_and_preserves_zero(monkeypatch,tmp_path,stale,failed):
    monkeypatch.setattr(httpx.Client,'send',Mock(side_effect=AssertionError('export requested upstream')))
    orc=make_orc(stale,failed)
    data=api._build_vault_data(orc)
    orc.quotes.read.assert_called_once()
    btc,eth=data['coins']
    assert btc['oi_cap']==0 and eth['oi_cap'] is None and eth['_oi'] is None
    assert btc['funding_ann']==(None if stale else 0)
    assert data['quote_meta']['fetched_at']==1000
    export_vault(data,str(tmp_path))
    text=(tmp_path/'Coins/BTC.md').read_text()
    assert 'OI/市值：0.00%' in text
    assert '1970-01-01T00:16:40+00:00' in text
    assert ('最近刷新失敗' in text)==failed
    assert 'oi_cap: null' in (tmp_path/'Coins/ETH.md').read_text()
    assert '過期或尚無資料' in text if stale else '未過期' in text


def test_mock_export_never_reads_real_quotes(monkeypatch):
    monkeypatch.setattr(httpx.Client,'send',Mock(side_effect=AssertionError('network')))
    orc=make_orc(mock=True)
    data=api._build_vault_data(orc)
    orc.quotes.read.assert_not_called()
    assert data['quote_meta']['source']=='mock'
