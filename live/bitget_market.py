#!/usr/bin/env python3
"""Bitget public market-data client for the P2 weekend strategy (no API key).

Uses only PUBLIC endpoints:
  - GET /api/v2/mix/market/history-candles  (1m bars, 200/call, paginate backward)
  - GET /api/v2/mix/market/tickers          (universe / volume screen)
Caches every page to live/cache/<SYM>USDT_1m.jsonl so reruns never re-download.

Granularity note (v2 mix): '1m' lowercase; limit<300; page backward via endTime.
"""
import json
import os
import time
import urllib.request
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, 'cache')
BASE = 'https://api.bitget.com'

FROZEN = json.load(open(os.path.join(HERE, '..', 'data', 'strategy_frozen_config.json')))
UNIVERSE = FROZEN['selected']  # SPY META NFLX AAPL HOOD COIN TSLA QQQ RDDT


def _get(path, params):
    url = BASE + path + '?' + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={'User-Agent': 'p2-weekend-bounce/1.0'})
    last_err = RuntimeError(f'{path}: exhausted retries')
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                return json.loads(r.read().decode())
        except Exception as e:  # noqa: BLE001
            last_err = e
            time.sleep(1.5 * (attempt + 1))
    raise last_err


def _cache_file(sym):
    return os.path.join(CACHE, f'{sym}USDT_1m.jsonl')


def load_cache(sym):
    """Return (rows, last_ts_ms) from the on-disk incremental cache."""
    f = _cache_file(sym)
    if not os.path.exists(f):
        return [], None
    rows = [json.loads(l) for l in open(f) if l.strip()]
    rows.sort(key=lambda r: r[0])
    return rows, (rows[-1][0] if rows else None)


def append_cache(sym, new_rows):
    """Append deduped, time-sorted rows; keep the file strictly ascending."""
    f = _cache_file(sym)
    os.makedirs(CACHE, exist_ok=True)
    rows, _ = load_cache(sym)
    seen = {r[0] for r in rows}
    fresh = sorted((r for r in new_rows if r[0] not in seen), key=lambda r: r[0])
    with open(f, 'a') as fh:
        for r in fresh:
            fh.write(json.dumps(r) + '\n')
    return len(fresh)


def fetch_1m(sym, start_ms=None, end_ms=None, max_bars=20000):
    """Fetch 1m bars for <sym>USDT perp with backward pagination.

    If start_ms given, page back until oldest bar <= start_ms or max_bars hit.
    Returns ascending rows [ts, o, h, l, c, volumeQuote].
    """
    all_rows = []
    cur_end = end_ms
    while len(all_rows) < max_bars:
        params = {'symbol': f'{sym}USDT', 'productType': 'USDT-FUTURES',
                  'granularity': '1m', 'limit': '200'}
        if cur_end is not None:
            params['endTime'] = str(int(cur_end))
        data = _get('/api/v2/mix/market/history-candles', params)
        if not data or data.get('code') != '00000':
            raise RuntimeError(f'candles API error for {sym}: {data}')
        batch = [[int(r[0])] + [float(x) for x in r[1:6]] for r in data['data']]
        if not batch:
            break
        all_rows.extend(batch)
        oldest = batch[0][0]
        if start_ms is not None and oldest <= start_ms:
            break
        if len(batch) < 200:  # reached listing start
            break
        cur_end = oldest - 1
        time.sleep(0.15)
    merged = sorted({r[0]: r for r in all_rows}.values(), key=lambda r: r[0])
    return merged


def refresh(sym_list=None, lookback_days=4):
    """Incrementally refresh the cache for each symbol; returns per-symbol stats."""
    out = {}
    now_ms = int(time.time() * 1000)
    lo = now_ms - lookback_days * 86_400_000
    for sym in (sym_list or UNIVERSE):
        rows, last = load_cache(sym)
        if last is None:
            new = fetch_1m(sym, start_ms=lo, max_bars=20000)
        else:
            new = fetch_1m(sym, start_ms=last + 1, end_ms=now_ms, max_bars=2000)
        new = [r for r in new if r[0] >= lo and (last is None or r[0] > last)]
        n = append_cache(sym, new)
        out[sym] = {'cached_bars': len(rows) + n, 'new_bars': n}
    return out


def tickers():
    data = _get('/api/v2/mix/market/tickers', {'productType': 'USDT-FUTURES'})
    if not data or data.get('code') != '00000':
        raise RuntimeError(f'tickers API error: {data}')
    return data['data']


if __name__ == '__main__':
    print(json.dumps(refresh(), indent=2))
