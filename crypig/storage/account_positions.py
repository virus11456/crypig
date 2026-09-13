"""BTC contract snapshots; compare observed quantities, never missing reads as zero."""
import json
from contextlib import contextmanager
import math
import sqlite3
from pathlib import Path

GROUPS = ('smart_verified', 'smart_pnl_only', 'whale')


def action(before, after):
    if abs(after-before) < 1e-8: return 'unchanged'
    if before == 0: return 'open_long' if after > 0 else 'open_short'
    if after == 0: return 'close_long' if before > 0 else 'close_short'
    if before*after < 0: return 'flip_long' if after > 0 else 'flip_short'
    if after > 0: return 'add_long' if after > before else 'reduce_long'
    return 'add_short' if after < before else 'reduce_short'


class AccountPositions:
    def __init__(self, path):
        self.path = str(path)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as c:
            c.execute('CREATE TABLE IF NOT EXISTS btc_account_batches(ts REAL PRIMARY KEY, payload TEXT NOT NULL)')

    @contextmanager
    def connect(self):
        c=sqlite3.connect(self.path, timeout=10)
        try:
            with c: yield c
        finally: c.close()

    def record(self, ts, groups):
        # Strict JSON refuses non-finite numbers before the transaction starts.
        payload = json.dumps(groups, allow_nan=False)
        if not math.isfinite(ts) or ts <= 0: raise ValueError('Invalid timestamp')
        with self.connect() as c:
            c.execute('INSERT OR IGNORE INTO btc_account_batches VALUES (?,?)', (ts, payload))
            c.execute('DELETE FROM btc_account_batches WHERE ts < ?', (ts-90*86400,))
        return {g: {w:self.compare(g, w, ts) for w in ('previous','24h','7d')} for g in GROUPS}

    def compare(self, group, window='previous', as_of=None):
        with self.connect() as c:
            latest = c.execute('SELECT ts,payload FROM btc_account_batches WHERE ts<=? ORDER BY ts DESC LIMIT 1', (as_of or 1e20,)).fetchone()
            if not latest: return {'status':'waiting', 'rows':[], 'matched':0}
            ts, payload = latest
            if window == 'previous':
                prev = c.execute('SELECT ts,payload FROM btc_account_batches WHERE ts<? ORDER BY ts DESC LIMIT 1',(ts,)).fetchone()
            else:
                target = ts-({'24h':86400,'7d':7*86400}[window])
                prev = c.execute('SELECT ts,payload FROM btc_account_batches WHERE ts<=? AND ts>=? ORDER BY ts DESC LIMIT 1',(target,target-2400)).fetchone()
        now = json.loads(payload).get(group,{})
        valid = {a:v for a,v in now.items() if v is not None}
        result = {'status':'waiting', 'as_of':ts, 'baseline_at':None, 'selected':len(now), 'received':len(valid),
                  'failed':len(now)-len(valid), 'matched':0, 'rows':[],
                  'current_long_btc':sum(max(v['btc'],0) for v in valid.values()),
                  'current_short_btc':sum(max(-v['btc'],0) for v in valid.values())}
        result['current_rows'] = sorted(
            [{'address':a,'after_btc':v['btc'],'observed_at':v['observed_at']} for a,v in valid.items() if v['btc'] != 0],
            key=lambda r:(-abs(r['after_btc']),r['address']))[:20]
        if not prev: return result
        before = json.loads(prev[1]).get(group,{})
        common = sorted(a for a in now if a in before and now[a] is not None and before[a] is not None)
        rows = [{'address':a, 'before_btc':before[a]['btc'], 'after_btc':now[a]['btc'],
                 'delta_btc':now[a]['btc']-before[a]['btc'], 'observed_at':now[a]['observed_at'],
                 'before_observed_at':before[a]['observed_at'], 'action':action(before[a]['btc'],now[a]['btc'])} for a in common]
        changed = [r for r in rows if r['action']!='unchanged']
        changed.sort(key=lambda r:(-abs(r['delta_btc']),r['address']))
        counts = {k:sum(r['action']==k for r in rows) for k in ('open_long','open_short','close_long','close_short','flip_long','flip_short','add_long','add_short','reduce_long','reduce_short','unchanged')}
        result.update(status='ok' if common else 'no_overlap', baseline_at=prev[0], matched=len(common),
            entered=len(set(now)-set(before)), exited=len(set(before)-set(now)),
            unobserved=len(set(now)&set(before))-len(common), counts=counts, changed=len(changed), rows=changed[:20],
            long_change_btc=sum(max(r['after_btc'],0)-max(r['before_btc'],0) for r in rows),
            short_change_btc=sum(max(-r['after_btc'],0)-max(-r['before_btc'],0) for r in rows),
            net_change_btc=sum(r['delta_btc'] for r in rows),
            gap_seconds=ts-prev[0])
        return result

    def history(self, address, group, as_of, limit=120):
        with self.connect() as c:
            batches=c.execute('SELECT ts,payload FROM btc_account_batches WHERE ts<=? ORDER BY ts DESC LIMIT ?', (as_of,limit)).fetchall()
        rows=[]
        for ts,payload in reversed(batches):
            members=json.loads(payload).get(group,{})
            v=members.get(address)
            rows.append({'ts':ts,'btc':v['btc'] if v else None,'status':'observed' if v else 'failed' if address in members else 'not_selected'})
        return rows
