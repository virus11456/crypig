"""Bounded, atomic Reddit board snapshots; timestamps survive process restarts."""
import json
import math
import os
from pathlib import Path
import tempfile


def load(path, subs, now):
    try:
        path = Path(path)
        if path.stat().st_size > 2_000_000:
            return None
        data = json.loads(path.read_text())
        if data['version'] != 1 or data['subs'] != list(subs):
            return None
        idx = data['idx']
        if type(idx) is not int or not 0 <= idx < len(subs):
            return None
        titles, times, attempts = data['titles'], data['times'], data['attempts']
        if not all(isinstance(x, dict) and set(x) <= set(subs) for x in [titles, times, attempts]):
            return None
        if set(titles) != set(times):
            return None
        def timestamp(x):
            return type(x) in (int, float) and math.isfinite(x) and 0 < x <= now
        for name, rows in titles.items():
            if not timestamp(times[name]) or not isinstance(rows, list) or len(rows) > 200:
                return None
            for row in rows:
                if (not isinstance(row, list) or len(row) != 2 or not isinstance(row[0], str)
                        or not row[0].strip() or len(row[0]) > 10000
                        or (row[1] is not None and not timestamp(row[1]))):
                    return None
        for item in attempts.values():
            if not timestamp(item['attempted_at']) or type(item['refresh_failed']) is not bool:
                return None
        return {**data, 'titles': {k: [tuple(row) for row in rows] for k, rows in titles.items()}}
    except (OSError, ValueError, TypeError, KeyError, OverflowError):
        return None


def save(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                         prefix=path.name+'.', suffix='.tmp', delete=False) as f:
            temp = f.name
            json.dump(data, f, ensure_ascii=False, allow_nan=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp, path)
    finally:
        if temp and os.path.exists(temp):
            os.unlink(temp)
