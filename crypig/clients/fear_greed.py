"""Validated daily Bitcoin sentiment, retaining the last good observation."""
import copy
import time


def available(data, now=None):
    now = time.time() if now is None else now
    observed = data.get('observed_at')
    return (data.get('value') is not None and isinstance(observed, (int, float))
            and 0 <= now - observed <= 172800 and not data.get('refresh_failed'))


def refresh(client, previous=None, now=None):
    now = time.time() if now is None else now
    previous = previous or {}
    try:
        response = client.get('https://api.alternative.me/fng/?limit=0')
        response.raise_for_status()
        payload = response.json()
        rows = payload.get('data')
        if (payload.get('metadata') or {}).get('error') or not isinstance(rows, list) or not rows:
            raise ValueError('Missing sentiment history')
        by_day = {}
        for row in rows:
            # Reject malformed batches instead of silently skipping the newest bad row.
            raw_value, raw_ts = row['value'], row['timestamp']
            if isinstance(raw_value, bool) or isinstance(raw_ts, bool):
                raise ValueError('Boolean observation')
            value, ts = int(raw_value), int(raw_ts)
            if float(raw_value) != value or float(raw_ts) != ts or not 0 <= value <= 100 or not 0 < ts <= now:
                raise ValueError('Invalid observation')
            label = row['value_classification']
            if label not in {'Extreme Fear', 'Fear', 'Neutral', 'Greed', 'Extreme Greed'}:
                raise ValueError('Invalid classification')
            observation = {'v': value, 't': ts, 'label': label}
            day = ts // 86400
            if day in by_day and by_day[day] != observation:
                raise ValueError('Conflicting daily observation')
            by_day[day] = observation
        history = sorted(by_day.values(), key=lambda x: x['t'])
        latest = history[-1]
        if latest['t'] < (previous.get('observed_at') or 0):
            raise ValueError('Observation date regressed')
        values = [x['v'] for x in history]
        return {'value': latest['v'], 'label': latest['label'],
                'percentile': round(sum(v < latest['v'] for v in values) / len(values) * 100),
                'hist_min': min(values), 'hist_max': max(values), 'days': len(values),
                'history': [{'v': x['v'], 't': x['t']} for x in history],
                'observed_at': latest['t'], 'fetched_at': now, 'attempted_at': now,
                'refresh_failed': False}
    except Exception:
        retained = copy.deepcopy(previous)
        retained.update(attempted_at=now, refresh_failed=True)
        return retained


def snapshot(previous=None, now=None, ttl=3600):
    """Reuse today's validated batch for one hour; new UTC day/failure retries next cycle."""
    import httpx
    now = time.time() if now is None else now
    previous = previous or {}
    fetched = previous.get('fetched_at')
    if (available(previous, now) and isinstance(fetched, (int, float))
            and 0 <= now-fetched < ttl
            and previous['observed_at']//86400 == now//86400):
        return copy.deepcopy(previous)
    # Dedicated public-source client: never inherit another provider's API headers.
    with httpx.Client(timeout=15, headers={'User-Agent': 'crypig/0.1'}) as client:
        return refresh(client, previous, now=now)
