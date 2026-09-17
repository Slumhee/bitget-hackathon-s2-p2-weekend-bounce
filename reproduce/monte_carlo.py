#!/usr/bin/env python3
"""Monte Carlo v2 (2000 sims) — proper placebo: random-Saturday-entry control vs P2 signal.

A) IID weekend bootstrap (13 weekends, frozen universe, net 12bp)
B) Circular block bootstrap (block=3)
C) Signal placebo: 2000 random weekends-of-entries sampled by randomly re-drawing the
   Sat-AM return gate sign per asset-weekend from ALL 13 weekends x 9 assets, recomputing
   basket return — measures how special 'AM-down' is vs random gate.
"""
import pandas as pd, numpy as np, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from study11_core import weekend_trades, IS_START, IS_END, OOS_START, OOS_END

HERE = os.path.dirname(os.path.abspath(__file__))
cfg = json.load(open(os.path.join(HERE, 'strategy_frozen_config.json')))
SEL = cfg['selected']

tr = pd.concat([weekend_trades(SEL, IS_START, IS_END), weekend_trades(SEL, OOS_START, OOS_END)])
tr['net_bp'] = tr['gross_bp'] + tr['fund_bp'] - 12.0
wk = tr.groupby('sat')['net_bp'].mean()
r = (wk / 1e4).values
rng = np.random.default_rng(42)
N = 2000

sims_a = np.array([rng.choice(r, size=len(r), replace=True).mean() for _ in range(N)])
def circ_block(x, block, n_sims, rng):
    n = len(x)
    starts = rng.integers(0, n, size=(n_sims, n))
    idx = (starts[:, :, None] + np.arange(block)[None, None, :]) % n
    idx = idx.reshape(n_sims, -1)[:, :n]
    return np.array([x[row].mean() for row in idx])
sims_b = circ_block(r, 3, N, rng)

# C) random-gate placebo: per asset-weekend cell, randomly keep/drop (same keep-rate as signal)
cells = tr[['sat', 'u', 'net_bp']].copy()
gate_rate = len(tr) / (wk.index.size * len(SEL))  # observed trigger frequency
sims_c = []
for _ in range(N):
    mask = rng.random(len(cells)) < gate_rate
    if mask.sum() == 0:
        continue
    # re-group: random assignment of cells to weekends preserving each weekend's count
    perm = rng.permutation(cells['sat'].values)
    dfc = pd.DataFrame({'sat': perm, 'net': cells['net_bp'].values[mask][rng.permutation(int(mask.sum()))]}) if False else None
    break  # placeholder — simpler: bootstrap means over random gate within each weekend below
# simpler correct placebo: for each weekend, sample the same NUMBER of assets from the 9 at random
per_wk_n = tr.groupby('sat').size()
all_assets_gross = {}
for sat in wk.index:
    rows = {}
    for u in SEL:
        g = tr[(tr['sat'] == sat) & (tr['u'] == u)]
        rows[u] = float(g['net_bp'].iloc[0]) if len(g) else np.nan
    all_assets_gross[sat] = rows
AG = pd.DataFrame(all_assets_gross).T  # weekends x assets, NaN = wasn't triggered (unknown outcome)
# For placebo we need ALL assets' weekend outcomes: recompute without gate
from study11_core import get_bar, next_open, funding_over, load1m
full = []
for sat in AG.index:
    for u in SEL:
        df = load1m(u)
        sig = sat + pd.Timedelta(hours=12)
        p0 = get_bar(df, sat, 'c'); p1 = get_bar(df, sig, 'c')
        if p0 is None or p1 is None:
            continue
        ep, ets = next_open(df, sig)
        xp, xts = next_open(df, sat + pd.Timedelta(days=1, hours=21))
        if ep is None or xp is None:
            continue
        if (xts - ets).total_seconds() > 40 * 3600:  # execution window sanity
            continue
        nb = (xp / ep - 1) * 1e4 + funding_over(u, ets, xts) * 1e4 - 12.0
        if abs(nb) > 3000:  # price dislocation guard
            continue
        full.append({'sat': sat, 'u': u, 'net_bp': nb})
FU = pd.DataFrame(full)
per_wk = FU.groupby('sat')['net_bp'].apply(list)
sims_c = []
sats = list(per_wk.index)
for _ in range(N):
    tots = []
    for sat in sats:
        arr = per_wk[sat]
        k = per_wk_n.get(sat, 2)
        k = min(max(k, 1), len(arr))
        tots.append(rng.choice(arr, size=k, replace=False).mean())
    sims_c.append(np.mean(tots))

sims_c = np.array(sims_c)  # already in bp
obs_bp = r.mean() * 1e4

out = {
 'n_sims': N, 'n_weekends': int(len(r)),
 'observed_mean_bp': float(obs_bp),
 'A_iid_bootstrap': {'p5': float(np.percentile(sims_a, 5) * 1e4), 'p50': float(np.percentile(sims_a, 50) * 1e4),
                     'p95': float(np.percentile(sims_a, 95) * 1e4), 'prob_neg': float((sims_a < 0).mean())},
 'B_block_bootstrap': {'p5': float(np.percentile(sims_b, 5) * 1e4), 'p50': float(np.percentile(sims_b, 50) * 1e4),
                       'p95': float(np.percentile(sims_b, 95) * 1e4), 'prob_neg': float((sims_b < 0).mean())},
 'C_random_gate_placebo': {'p5': float(np.percentile(sims_c, 5)), 'p50': float(np.percentile(sims_c, 50)),
                           'p95': float(np.percentile(sims_c, 95)),
                           'observed_percentile': float((sims_c < obs_bp).mean() * 100)},
 'hist_A': [np.histogram(sims_a, bins=40)[0].tolist(), np.histogram(sims_a, bins=40)[1].tolist()],
 'hist_B': [np.histogram(sims_b, bins=40)[0].tolist(), np.histogram(sims_b, bins=40)[1].tolist()],
 'hist_C': [np.histogram(sims_c, bins=40)[0].tolist(), np.histogram(sims_c, bins=40)[1].tolist()],
}
json.dump(out, open(os.path.join(HERE, '..', 'data', 'monte_carlo.json'), 'w'))
print('obs', round(r.mean() * 1e4, 1))
print('A', {k: round(v, 1) for k, v in out['A_iid_bootstrap'].items()})
print('B', {k: round(v, 1) for k, v in out['B_block_bootstrap'].items()})
print('C', {k: round(v, 1) for k, v in out['C_random_gate_placebo'].items()})
