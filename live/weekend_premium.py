#!/usr/bin/env python3
"""Weekend premium tracker: Bitget Stock Perp (7x24) vs native US stock (via bitget-mcp-server).

Core hypothesis of the P2 strategy, now grounded in official ecosystem data:
  - The perp keeps trading while the native market is closed (weekend)
  - Saturday-morning perp drawdowns are "information-less overshoot" that mean-revert
  - The native close (MCP daily bar) is the fair-value anchor

Writes live/data/weekend_premium.csv — one row per (symbol, weekend):
  perp entries from the local 1m cache; native anchor from MCP daily bars.
"""
import os
import sys
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from bitget_market import UNIVERSE, load_cache  # noqa: E402
from mcp_data import native_daily  # noqa: E402

OUT = os.path.join(HERE, 'data')
os.makedirs(OUT, exist_ok=True)


def weekend_premium(sym, sat):
    """Premium of perp over native Fri close at Sat 12:00 UTC signal time."""
    rows, _ = load_cache(sym)
    sat_dt = datetime.fromisoformat(sat).replace(tzinfo=timezone.utc)
    sat_ms = int(sat_dt.timestamp() * 1000)
    sig_ms = sat_ms + 12 * 3600_000

    # native Friday close: last native bar strictly before the Saturday
    bars = native_daily(sym, (sat_dt - timedelta(days=10)).date().isoformat(),
                        (sat_dt + timedelta(days=1)).date().isoformat())
    fri = [b for b in bars if b['date'] < f'{sat}T']
    if not fri:
        return None
    fri_close = fri[-1]['close']

    # perp close at/before Sat 12:00 UTC
    perp_px = None
    for r in rows:
        if r[0] <= sig_ms:
            perp_px = r[4]
        else:
            break
    if perp_px is None:
        return None
    return {'symbol': sym, 'sat': sat, 'fri_native_close': fri_close,
            'perp_sat_noon': perp_px,
            'premium_bp': round((perp_px / fri_close - 1) * 1e4, 2)}


def main():
    sats = sys.argv[1:]
    out_path = os.path.join(OUT, 'weekend_premium.csv')
    lines = []
    if os.path.exists(out_path):
        lines = [l for l in open(out_path).read().splitlines() if l]
    header = 'symbol,sat,fri_native_close,perp_sat_noon,premium_bp'
    if lines and lines[0] != header:
        lines = []
    if not lines:
        lines = [header]
    have = {(l.split(',')[0], l.split(',')[1]) for l in lines[1:]}
    for sat in sats:
        for sym in UNIVERSE:
            if (sym, sat) in have:
                continue
            try:
                row = weekend_premium(sym, sat)
            except Exception as e:  # noqa: BLE001
                print(f'WARN {sym} {sat}: {e}')
                continue
            if row:
                lines.append(f"{row['symbol']},{row['sat']},{row['fri_native_close']},"
                             f"{row['perp_sat_noon']},{row['premium_bp']}")
                print(f"{row['symbol']} {row['sat']}: perp {row['perp_sat_noon']} vs "
                      f"native Fri close {row['fri_native_close']} -> {row['premium_bp']}bp")
    with open(out_path, 'w') as fh:
        fh.write('\n'.join(lines) + '\n')
    print(f'-> {out_path} ({len(lines) - 1} rows)')


if __name__ == '__main__':
    main()
