"""One persisted, nonblocking LTH daily history for agents and dashboard readers."""
import copy
from datetime import datetime, timezone
import time

from ..clients.bitcoin_data import BitcoinDataClient
from ..clients.lth_history import build_lth, SLUG
from ..dashboard.cache import SnapshotCache

KEY = 'lth_daily_supply_v1'  # Reuse the deployed history file; no history migration.


def validate_snapshot(data):
    if not isinstance(data, dict) or data.get('source') != 'https://bitcoin-data.com/v1/' + SLUG:
        raise ValueError('Invalid LTH source')
    rebuilt = build_lth([{'d': row['date'], 'longTermHodlerSupplyBtc': row['btc']}
                         for row in data['history']])
    for field in ('as_of', 'balance_btc', 'changes_btc', 'history'):
        if data.get(field) != rebuilt[field]:
            raise ValueError('Invalid LTH history snapshot')
    return rebuilt


class _LTHCache(SnapshotCache):
    def _restore(self, key):
        entry = super()._restore(key)
        if entry['data'] is not None:
            try:
                entry['data'] = validate_snapshot(entry['data'])
            except (ValueError, TypeError, KeyError, RuntimeError):
                entry.update(data=None, updated_at=None)
        return entry

    def _refresh(self, key, loader):
        def checked():
            value = validate_snapshot(loader())
            with self._lock:
                previous = self._entries[key]['data']
            if previous and value['as_of'] < previous['as_of']:
                raise ValueError('LTH source date regressed')
            return value
        super()._refresh(key, checked)


class LTHSupply:
    def __init__(self, directory=None, loader=None):
        self._cache = _LTHCache(workers=1, retry_seconds=3600, directory=directory)
        self._loader = loader or self._load

    @staticmethod
    def _load():
        client = BitcoinDataClient()
        try:
            return build_lth(client.fetch_history(SLUG, ttl=0))
        finally:
            client.close()

    def read(self):
        now = time.time()
        today = datetime.fromtimestamp(now, timezone.utc).date()
        # Expire at UTC midnight or after six hours, whichever comes first.
        ttl = min(21600, now % 86400)
        data, meta = self._cache.read(KEY, self._loader, ttl=ttl)
        meta.update(source_date=data['as_of'] if data else None,
                    source_age_days=(today-datetime.fromisoformat(data['as_of']).date()).days if data else None,
                    refresh_interval_seconds=21600, retry_interval_seconds=3600,
                    timestamp_kind='fetched_at')
        # Callers cannot mutate the shared history or create false agent readings.
        return copy.deepcopy(data), meta

    def close(self):
        self._cache.close()
