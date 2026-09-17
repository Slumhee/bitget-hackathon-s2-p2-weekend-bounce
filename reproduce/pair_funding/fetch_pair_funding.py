#!/usr/bin/env python3
"""Fetch Bitget USDT-FUTURES stock perp funding history into pair_funding/."""
import requests, time, json, os

B = 'https://api.bitget.com/api/v2/mix/market/history-fund-rate'
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = HERE
os.makedirs(OUT, exist_ok=True)
s = requests.Session()

symbols = ['MSTRUSDT', 'INTCUSDT', 'TSLAUSDT', 'HOODUSDT', 'COINUSDT', 'PLTRUSDT',
           'SPYUSDT', 'QQQUSDT', 'AAPLUSDT', 'GOOGLUSDT', 'METAUSDT']

for sym in symbols:
    f = os.path.join(OUT, f'{sym}.jsonl')
    seen = set()
    if os.path.exists(f):
        for line in open(f):
            try:
                seen.add(json.loads(line)['fundingTime'])
            except Exception:
                pass
    page = 1
    with open(f, 'a') as fh:
        while True:
            d = []
            for attempt in range(6):
                try:
                    r = s.get(B, params={'symbol': sym, 'productType': 'USDT-FUTURES',
                                         'pageSize': '100', 'pageNo': str(page)}, timeout=20)
                    if r.status_code == 429:
                        time.sleep(2 * (attempt + 1))
                        continue
                    j = r.json()
                    if j.get('code') == '00000':
                        d = j.get('data') or []
                    break
                except Exception:
                    time.sleep(1 * (attempt + 1))
            if not d:
                break
            new = 0
            for row in d:
                t = row.get('fundingTime')
                if t is not None and t not in seen:
                    fh.write(json.dumps({'fundingTime': row['fundingTime'],
                                         'fundingRate': row['fundingRate']}) + '\n')
                    seen.add(t)
                    new += 1
            fh.flush()
            if len(d) < 100 or (new == 0 and page > 3):
                break
            page += 1
            time.sleep(0.2)
    print(sym, len(seen), flush=True)
print('DONE', flush=True)
