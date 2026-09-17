#!/usr/bin/env python3
"""Study 11 Step 2: OOS evaluation — reads frozen config only, zero tuning."""
import pandas as pd, numpy as np, json, os
from study11_core import (weekend_trades, portfolio_returns, metrics,
                          IS_START, IS_END, OOS_START, OOS_END, load1m)

HERE = os.path.dirname(os.path.abspath(__file__))
cfg = json.load(open(os.path.join(HERE, 'strategy_frozen_config.json')))
SEL = cfg['selected']
COST = cfg['cost_rt_bp']

# --- OOS run ---
tr_oos = weekend_trades(SEL, OOS_START, OOS_END)
tr_oos.to_csv(os.path.join(HERE, 'trade_log.csv'), index=False)
wk = portfolio_returns(tr_oos, COST)
wk.to_frame('net_bp').to_csv(os.path.join(HERE, 'weekend_returns.csv'))
m_oos = metrics(wk)
print('OOS (frozen):', json.dumps(m_oos))

# --- IS run (same frozen universe for fair decay comparison) ---
tr_is = weekend_trades(SEL, IS_START, IS_END)
wk_is = portfolio_returns(tr_is, COST)
m_is = metrics(wk_is)
print('IS (frozen):', json.dumps(m_is))

# decay
decay = 1 - (m_oos['mean_bp'] / m_is['mean_bp']) if m_is['mean_bp'] else None
print('OOS/IS mean decay: %.1f%%' % (decay * 100) if decay is not None else 'n/a')

# --- benchmarks (task §32) ---
# A: all-eligible weekend long (no signal)
elig = pd.read_csv(os.path.join(HERE, 'eligible_universe.csv'))
E = elig[elig['eligible'] == True]['u'].tolist()
tr_a = weekend_trades(E, OOS_START, OOS_END)
# force "all" = every asset every weekend: rebuild without signal filter
from study11_core import get_bar, next_open, funding_over
rows = []
for wsat in pd.date_range(OOS_START, OOS_END, freq='W-SAT'):
    for u in E:
        df = load1m(u)
        sig = wsat + pd.Timedelta(hours=12)
        p0 = get_bar(df, wsat, 'c'); p1 = get_bar(df, sig, 'c')
        if p0 is None or p1 is None:
            continue
        ep, ets = next_open(df, sig)
        xp, xts = next_open(df, wsat + pd.Timedelta(days=1, hours=21))
        if ep is None or xp is None:
            continue
        rows.append({'sat': wsat, 'u': u, 'gross_bp': (xp / ep - 1) * 1e4,
                     'fund_bp': funding_over(u, ets, xts) * 1e4})
bmA = pd.DataFrame(rows).groupby('sat').apply(lambda g: (g['gross_bp'] + g['fund_bp'] - COST).mean())
# B = P2 signal (already computed as wk)
# C: BTC same window
b = pd.read_json(os.path.join(HERE, 'btc_1m.jsonl'), orient='records', lines=True, convert_dates=False)
b.columns = ['ts', 'o', 'h', 'l', 'c', 'vb', 'vq'][:len(b.columns)]
b['dt'] = pd.to_datetime(b['ts'].astype('int64'), unit='ms', utc=True)
b = b.drop_duplicates('dt').sort_values('dt').set_index('dt')
bmC = []
for wsat in pd.date_range(OOS_START, OOS_END, freq='W-SAT'):
    ep, _ = next_open(b, wsat + pd.Timedelta(hours=12))
    xp, _ = next_open(b, wsat + pd.Timedelta(days=1, hours=21))
    if ep and xp:
        bmC.append({'sat': wsat, 'net_bp': (xp / ep - 1) * 1e4 - COST})
bmC = pd.DataFrame(bmC).set_index('sat')['net_bp']

print('Benchmark A (all-eligible long, OOS):', metrics(bmA))
print('Benchmark C (BTC same window, OOS):', metrics(bmC))
print('P2 OOS:', m_oos)

out = {'frozen_cfg': cfg, 'is': m_is, 'oos': m_oos, 'decay_mean': decay,
       'benchmark_A_oos': metrics(bmA), 'benchmark_C_oos': metrics(bmC)}
json.dump(out, open(os.path.join(HERE, 'oos_results.json'), 'w'), indent=1, default=str)
json.dump(m_is, open(os.path.join(HERE, 'is_results.json'), 'w'), indent=1, default=str)
print('saved is_results.json / oos_results.json')
