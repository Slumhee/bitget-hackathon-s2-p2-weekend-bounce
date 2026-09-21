#!/usr/bin/env python3
"""Live signal engine for the P2 Weekend Bounce strategy (frozen v1.0).

Causally identical to reproduce/study11_core.py::weekend_trades:
  - signal:   Sat 00:00 UTC close  ->  Sat 12:00 UTC close, return < 0
  - entry:    first 1m bar open strictly AFTER Sat 12:00
  - exit:     first 1m bar open strictly AFTER Sun 21:00
  - universe: frozen 9 symbols, equal weight

Reads only from live/cache (refreshed by bitget_market.py). Emits JSONL events.
"""
import json
import os
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from bitget_market import UNIVERSE, load_cache  # noqa: E402

SIGNAL_H = 12   # Sat 12:00 UTC signal bar
EXIT_H = 21     # Sun 21:00 UTC exit bar


def utc(ts_ms):
    return datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)


def last_bar_at_or_before(rows, ts_ms):
    """Close of the newest bar with open-time <= ts_ms (mirrors get_bar)."""
    prev = None
    for r in rows:
        if r[0] <= ts_ms:
            prev = r
        else:
            break
    return prev


def first_bar_after(rows, ts_ms):
    """First bar strictly after ts_ms (mirrors next_open: entry uses its open)."""
    for r in rows:
        if r[0] > ts_ms:
            return r
    return None


def sat_signal(sym_rows, sat_start_ms):
    """Return dict if symbol triggers entry this weekend, else None."""
    sig_ms = sat_start_ms + SIGNAL_H * 3600_000
    b0 = last_bar_at_or_before(sym_rows, sat_start_ms)
    b1 = last_bar_at_or_before(sym_rows, sig_ms)
    if b0 is None or b1 is None:
        return None
    # freshness (backtest allows <=6h staleness)
    if sat_start_ms - b0[0] > 6 * 3600_000 or sig_ms - b1[0] > 6 * 3600_000:
        return None
    ret = b1[4] / b0[4] - 1
    if ret >= 0:
        return None
    return {'symbol': None, 'sat_am_bp': round(ret * 1e4, 2),
            'ref0_ts': b0[0], 'ref1_ts': b1[0], 'ref0_close': b0[4], 'ref1_close': b1[4]}


def plan_weekend(saturday_iso):
    """Compute the full trade plan for the given Saturday (YYYY-MM-DD, UTC)."""
    sat = datetime.fromisoformat(saturday_iso).replace(tzinfo=timezone.utc)
    sat_ms = int(sat.timestamp() * 1000)
    sig_ms = sat_ms + SIGNAL_H * 3600_000
    xit_ms = sat_ms + (24 + EXIT_H) * 3600_000
    plan = []
    for sym in UNIVERSE:
        rows, _ = load_cache(sym)
        sig = sat_signal(rows, sat_ms)
        if sig is None:
            continue
        sig['symbol'] = sym
        eb = first_bar_after(rows, sig_ms)
        if eb is not None:
            sig['planned_entry_ts'] = eb[0]
            sig['planned_entry_px'] = eb[1]
        plan.append(sig)
    return {'saturday': saturday_iso, 'signal_cutoff': sig_ms,
            'exit_after': xit_ms, 'entries': plan,
            'n_selected': len(plan)}


def replay_current_weekend():
    """Most recent Saturday at or before now (UTC)."""
    import time
    from datetime import timedelta
    now = datetime.fromtimestamp(time.time(), tz=timezone.utc)
    offset = (now.weekday() - 5) % 7  # days back to most recent Saturday
    sat = (now - timedelta(days=offset)).date().isoformat()
    return plan_weekend(sat)


if __name__ == '__main__':
    target = sys.argv[1] if len(sys.argv) > 1 else None
    result = plan_weekend(target) if target else replay_current_weekend()
    print(json.dumps(result, indent=2))
