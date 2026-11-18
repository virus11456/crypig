"""Count requests at the HTTP boundary across the actual cycle consumers."""
import time
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest

from crypig.agents.whale import WhaleAgent
from crypig.clients.market_data import MarketDataClient
from crypig.orchestrator import Orchestrator


@pytest.fixture
def cycle(monkeypatch):
    calls = []
    status = [200]
    clock = [time.time()]
    monkeypatch.setattr('crypig.clients.market_data.time.time', lambda: clock[0])
    def handler(request):
        calls.append(request.url.path)
        if request.url.path.endswith('/derivatives'):
            return httpx.Response(status[0], json=[{
                'contract_type': 'perpetual', 'index_id': 'ETH', 'market': 'test',
                'symbol': 'ETHUSD', 'open_interest': 100, 'price': 10,
                'last_traded_at': clock[0], 'expired_at': None}])
        if request.url.path.endswith('/global'):
            return httpx.Response(200, json={'data': {'total_market_cap': {'usd': 1000},
                                                       'total_volume': {'usd': 200}}})
        raise AssertionError(request.url)
    md = MarketDataClient()
    md._client.close()
    md._client = httpx.Client(transport=httpx.MockTransport(handler))
    agent = object.__new__(WhaleAgent)
    agent._client = Mock()
    agent._client.aggregate_derivatives.side_effect = AssertionError('Second client fetched')
    agent._hl = SimpleNamespace(funding_scan=lambda: [{'symbol': 'ETH', 'funding_ann': .1}])
    agent._store = Mock(latest=lambda *args: None)
    orc = object.__new__(Orchestrator)
    orc.config = SimpleNamespace(use_mock=False)
    orc._md = md
    orc.agents = [agent]
    orc._cycle_steps = {}
    orc.deriv_agg = {'OLD': {'open_interest_usd': 20}}
    orc.valuation_times = {'aggregate_oi': 10}
    # Other sources are isolated; exercise the actual market refresh wiring.
    orc._dl = SimpleNamespace(snapshot=lambda **kw: {})
    orc._rd = SimpleNamespace(crypto_buzz=lambda: {})
    orc._nc = SimpleNamespace(analyze=lambda: {})
    orc._lc = SimpleNamespace(enabled=False)
    orc.defi = {}; orc.fear_greed = {}; orc.macro = None
    monkeypatch.setattr(md, 'top_markets', lambda: {})
    monkeypatch.setattr('crypig.clients.fear_greed.snapshot', lambda previous: {})
    yield orc, agent, calls, status, clock
    md._client.close()


def test_one_request_shared_by_whale_and_macro_even_after_ttl(cycle):
    orc, agent, calls, status, clock = cycle
    orc._prepare_cycle_derivatives()
    fetched = orc.valuation_times['aggregate_oi']
    clock[0] += 180  # Longer than the standalone client's 60-second TTL.
    for symbol in ['ETH', 'SOL', 'ETH']:
        raw = agent._fetch_market(symbol)
        assert raw['open_interest_usd'] == (100 if symbol == 'ETH' else None)
    orc._refresh_market_data()
    assert orc.macro['open_interest'] == 100
    assert orc.valuation_times['aggregate_oi'] == fetched
    assert calls.count('/api/v3/derivatives') == 1
    agent._client.aggregate_derivatives.assert_not_called()
    with pytest.raises(TypeError):
        orc._cycle_derivatives['ETH']['open_interest_usd'] = 999
    orc.deriv_agg['ETH']['open_interest_usd'] = 999
    assert agent._fetch_market('ETH')['open_interest_usd'] == 100
    agent.end_cycle()
    assert agent._cycle_derivatives is None


def test_failed_cycle_does_not_retry_or_record_stale_oi_and_next_cycle_recovers(cycle):
    orc, agent, calls, status, clock = cycle
    orc._prepare_cycle_derivatives()
    old_time = orc.valuation_times['aggregate_oi']
    clock[0] += 1200
    status[0] = 429
    orc._prepare_cycle_derivatives()
    for symbol in ['ETH', 'SOL']:
        raw = agent._fetch_market(symbol)
        obs = agent._analyze_market(symbol, raw)
        assert raw['open_interest_usd'] is None
        assert obs.status == 'no_data'
    agent._store.record.assert_not_called()
    orc._refresh_market_data()
    assert calls.count('/api/v3/derivatives') == 2  # One attempt per cycle.
    assert orc.macro['open_interest'] is None
    assert orc.deriv_agg['ETH']['open_interest_usd'] == 100
    assert orc.valuation_times['aggregate_oi'] == old_time
    assert orc._cycle_steps['market.deriv']['state'] == 'raised'
    status[0] = 200
    clock[0] += 1200
    orc._prepare_cycle_derivatives()
    assert agent._fetch_market('ETH')['open_interest_usd'] == 100
    assert orc.valuation_times['aggregate_oi'] > old_time
    assert calls.count('/api/v3/derivatives') == 3


def test_standalone_macro_still_fetches_derivatives(cycle):
    orc, _, calls, _, _ = cycle
    assert orc._md.global_macro()['open_interest'] == 100
    assert calls.count('/api/v3/derivatives') == 1


def test_mock_cycle_makes_no_derivatives_request(cycle):
    orc, agent, calls, _, _ = cycle
    orc.config.use_mock = True
    orc._prepare_cycle_derivatives()
    assert not calls
    assert not orc._cycle_derivatives


def test_cycle_exception_always_releases_whale_snapshot(cycle):
    import threading
    orc, agent, _, _, _ = cycle
    orc._cycle_lock = threading.Lock()
    orc._published = None
    orc._empty_state = {}
    def fail():
        orc._prepare_cycle_derivatives()
        raise RuntimeError('Later cycle stage failed')
    orc._run_cycle_locked = fail
    with pytest.raises(RuntimeError):
        orc.run_cycle()
    assert agent._cycle_derivatives is None
    assert orc._cycle_derivatives is None
    assert not orc._cycle_lock.locked()
