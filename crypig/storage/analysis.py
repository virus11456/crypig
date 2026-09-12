"""Versioned, atomic persistence of completed dashboard analysis only."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
from datetime import datetime, timezone

FIELDS = {
    'all_scores': dict, 'radar': dict, 'trader_summary': dict,
    'last_result': dict, 'macro': (dict, type(None)), 'market_caps': dict,
    'deriv_agg': dict, 'social': dict, 'fear_greed': dict, 'defi': dict,
    'reddit': dict, 'hl_scan': list, 'news': dict, '_prev_pos': dict,
    'snapshot_decisions': list,
}


class AnalysisStore:
    def __init__(self, path, config):
        self.path = Path(path)
        self.signature = hashlib.sha256(config.model_dump_json().encode()).hexdigest()

    def validate(self, saved):
        if saved['version'] != 1 or saved['config'] != self.signature:
            raise ValueError('Incompatible analysis snapshot')
        ts = datetime.fromisoformat(saved['completed_at'])
        if ts.tzinfo is None or not 0 < ts.timestamp() <= datetime.now(timezone.utc).timestamp()+60:
            raise ValueError('Invalid completion time')
        state = saved['state']
        if any(not isinstance(state[k], typ) for k, typ in FIELDS.items()):
            raise ValueError('Invalid analysis fields')
        if not state['last_result'].get('ts') or not isinstance(state['last_result'].get('signals'), dict):
            raise ValueError('Incomplete analysis result')
        json.dumps(saved, allow_nan=False)
        return saved

    def load(self):
        try:
            return self.validate(json.loads(self.path.read_text()))
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            return None

    def save(self, state, completed_at):
        saved = self.validate({'version': 1, 'config': self.signature,
                               'completed_at': completed_at, 'state': state})
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix('.tmp')
        with temporary.open('w') as f:
            json.dump(saved, f, allow_nan=False)
            f.flush()
            os.fsync(f.fileno())
        temporary.replace(self.path)
