#!/usr/bin/env python3
"""Extend reproduce/pair_1m/<SYM>USDT_perp.jsonl with fresh Bitget v2 1m bars.

Fetches full-column candles (matching the original 8-col format) from each
symbol's current last bar up to now, dedupes on ts, appends, keeps file sorted.
Only PUBLIC market data endpoints are used.
"""
import json
import os
import sys
import time
import urllib.request
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
D1 = os.path.join(HERE, 'pair_1m')
BASE = 'https://api.bitget.com'
UNIVERSE = ['SPY', 'META', 'NFLX', 'AAPL', 'HOOD', 'COIN', 'TSLA', 'QQQ', 'RDDT']


def get(path, params):
    url = BASE + path + '?' + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={'User-Agent': 'p2-weekend-bounce/1.0'})
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                return json.loads(r.read().decode())
        except Exception:
            if attempt == 4:
                raise
            time.sleep(1.5 * (attempt + 1))


def fetch(sym, start_ms, end_ms):
    """Backward-paginate 1m candles; return full raw rows (string fields kept)."""
    rows = []
    cur_end = end_ms
    while True:
        p = {'symbol': f'{sym}USDT', 'productType': 'USDT-FUTURES',
             'granularity': '1m', 'limit': '200', 'endTime': str(cur_end)}
        d = get('/api/v2/mix/market/history-candles', p)
        if d.get('code') != '00000':
            raise RuntimeError(f'{sym}: {d}')
        batch = d['data']
        if not batch:
            break
        rows.extend(batch)
        oldest = int(batch[0][0])
        if oldest <= start_ms or len(batch) < 200:
            break
        cur_end = oldest - 1
        time.sleep(0.15)
    return rows


def main():
    now_ms = int(time.time() * 1000)
    for sym in UNIVERSE:
        f = os.path.join(D1, f'{sym}USDT_perp.jsonl')
        existing = {}
        with open(f) as fh:
            for line in fh:
                r = json.loads(line)
                existing[int(r[0])] = r
        last_ts = max(existing)
        new = fetch(sym, last_ts + 1, now_ms)
        added = 0
        for r in new:
            ts = int(r[0])
            if ts > last_ts and ts not in existing:
                # keep 8-col shape: ts,o,h,l,c,baseVol,quoteVol,usdtVol (pad if short)
                row = list(r) + ['0'] * (8 - len(r))
                existing[ts] = [str(row[0])] + [str(x) for x in row[1:8]]
                added += 1
        with open(f, 'w') as fh:
            for ts in sorted(existing):
                fh.write(json.dumps(existing[ts]) + '\n')
        print(f'{sym}: +{added} bars -> last '
              f'{time.strftime("%Y-%m-%d %H:%M", time.gmtime(max(existing)/1000))} UTC')


if __name__ == '__main__':
    main()
