"""Explicit BTC address balance cohorts; not entity-adjusted trades."""
from datetime import date, timedelta
import math

COHORTS = (
    ('whale', '1,000–10,000 BTC 地址', 'coins-addr-10K-1K-BTC', 'coinsAddr10Kto1Kbtc'),
    ('humpback', '>10,000 BTC 地址', 'coins-addr-10K-BTC', 'coinsAddr10Kbtc'),
)

def normalize(rows, field):
    out = {}
    for row in rows:
        try:
            day = date.fromisoformat(row['d']).isoformat()
            value = float(row[field])
            if isinstance(row[field], bool) or not math.isfinite(value) or value < 0:
                continue
            if day in out and out[day] != value:
                raise RuntimeError('Conflicting cohort values for one date')
            out[day] = value
        except (ValueError, TypeError, KeyError):
            continue
    return out

def build_cohorts(series):
    common = sorted(set(series[0]) & set(series[1]))
    if not common:
        raise ValueError('No common cohort dates')
    latest = common[-1]
    def changes(values):
        return {str(n): values[latest]-values[target] if target in values else None
                for n in (1, 7, 30)
                for target in [(date.fromisoformat(latest)-timedelta(days=n)).isoformat()]}
    history = [{'date': d, 'btc': sum(s[d] for s in series),
                'whale': series[0][d], 'humpback': series[1][d]} for d in common]
    cohorts = [{'id': cid, 'label': label, 'source': 'https://bitcoin-data.com/v1/'+slug,
                'balance_btc': values[latest], 'changes_btc': changes(values)}
               for (cid,label,slug,_),values in zip(COHORTS,series)]
    combined = {r['date']:r['btc'] for r in history}
    return {'history':history, 'cohorts':cohorts, 'as_of':latest,
            'bands':'≥1,000 BTC 地址合計', 'changes_btc':changes(combined),
            'methodology':'address_balance_btc_v1',
            'note':'地址餘額分組，未排除交易所與託管，未做實體合併；不代表成交買賣或長期持有者。'}

def fetch_cohorts(client):
    return build_cohorts([normalize(client.fetch_history(slug, ttl=0),field)
                          for _,_,slug,field in COHORTS])
