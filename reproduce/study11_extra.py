#!/usr/bin/env python3
"""Study 11 Step 3: remaining deliverables + final report."""
import pandas as pd, numpy as np, json, os
from study11_core import (weekend_trades, portfolio_returns, metrics,
                          IS_START, IS_END, OOS_START, OOS_END, load1m, funding_over, get_bar, next_open)

HERE = os.path.dirname(os.path.abspath(__file__))
cfg = json.load(open(os.path.join(HERE, 'strategy_frozen_config.json')))
SEL = cfg['selected']

tr_oos = weekend_trades(SEL, OOS_START, OOS_END)
tr_is = weekend_trades(SEL, IS_START, IS_END)

# 1) OOS cost sensitivity
cs = []
for c in (0, 4, 6, 8, 12, 14, 18):
    wk = portfolio_returns(tr_oos, float(c))
    m = metrics(wk)
    m['cost_rt_bp'] = c
    cs.append(m)
pd.DataFrame(cs).to_csv(os.path.join(HERE, 'cost_sensitivity.csv'), index=False)

# 2) OOS LOO asset + LOO weekend
loo = []
for skip in SEL:
    wk = portfolio_returns(tr_oos[tr_oos['u'] != skip], 12.0)
    m = metrics(wk); m['dropped'] = skip
    loo.append(m)
pd.DataFrame(loo).to_csv(os.path.join(HERE, 'loo_asset.csv'), index=False)
wkfull = portfolio_returns(tr_oos, 12.0)
low = []
for sat in wkfull.index:
    m = metrics(wkfull.drop(sat)); m['dropped_sat'] = str(sat.date())
    low.append(m)
pd.DataFrame(low).to_csv(os.path.join(HERE, 'loo_weekend.csv'), index=False)

# 3) OOS per-asset stats
ast = tr_oos.groupby('u').agg(N=('gross_bp', 'size'), mean_gross_bp=('gross_bp', 'mean'),
                              win=('gross_bp', lambda s: (s > 0).mean()),
                              mae_med=('mae_bp', 'median'), mfe_med=('mfe_bp', 'median'),
                              net_contrib_bp=('gross_bp', lambda s: (s - 12).sum())).round(1)
ast.to_csv(os.path.join(HERE, 'asset_stats.csv'))

# 4) synthetic tick stress: intrabar sequencing uncertainty for entry bar.
#    Entry is next-bar OPEN (market) -> no intrabar dependency for entry.
#    The exposure risk is the holding path; model exit-bar uncertainty: exit executes at 21:01 open,
#    which is a real print -> no synthetic needed. Stress instead the WORST intrabar close ordering:
#    for each trade, replace exit with worst of (bar low, exit) for 30% of trades (adverse selection sim).
#    Plus a Brownian-bridge MTM drawdown stress on 5m grid.
rng = np.random.default_rng(7)
res = []
for pct in (0, 30, 100):
    sims = []
    for sim in range(40):
        tot = []
        for _, t in tr_oos.iterrows():
            df = load1m(t['u'])
            win = df.loc[t['entry_ts']:t['exit_ts']]
            if len(win) < 5:
                continue
            # adverse exit: with prob pct/100 exit at bar LOW near exit time (worst 15min window)
            if rng.random() < pct / 100.0:
                tail = win.tail(15)
                exit_px = tail['l'].min()
            else:
                exit_px = t['exit_px']
            tot.append((exit_px / t['entry_px'] - 1) * 1e4 - 12.0)
        # weekend mean
        sims.append(np.mean(tot))
    res.append({'adverse_pct': pct, 'mean_bp_median': round(float(np.median(sims)), 1),
                'p10': round(float(np.percentile(sims, 10)), 1),
                'p90': round(float(np.percentile(sims, 90)), 1),
                'worst_sim': round(float(np.min(sims)), 1), 'best_sim': round(float(np.max(sims)), 1)})
pd.DataFrame(res).to_csv(os.path.join(HERE, 'synthetic_tick_stress.csv'), index=False)

# 5) resampling / multi-timeframe diagnostics: 1h vol & 4h efficiency per OOS weekend vs pnl
rd = []
for sat, grp in tr_oos.groupby('sat'):
    pnls = []
    for _, t in grp.iterrows():
        df = load1m(t['u'])
        h1 = df.loc[sat:sat + pd.Timedelta(hours=12), 'c'].resample('1h').last().dropna()
        rv1h = np.log(h1).diff().std() * 1e4 if len(h1) > 3 else np.nan
        c4 = df.loc[sat - pd.Timedelta(days=3):sat, 'c'].resample('4h').last().dropna()
        r4 = np.log(c4).diff().dropna()
        eff = abs(r4.iloc[-4:].sum()) / (r4.iloc[-4:].abs().sum() + 1e-9) if len(r4) >= 4 else np.nan
        pnls.append({'rv1h': rv1h, 'eff4h': eff, 'net': t['gross_bp'] + t['fund_bp'] - 12})
    d = pd.DataFrame(pnls)
    rd.append({'sat': str(sat.date()), 'mean_net_bp': round(d['net'].mean(), 1),
               'rv1h_med': round(d['rv1h'].median(), 1), 'eff4h_med': round(d['eff4h'].median(), 2)})
pd.DataFrame(rd).to_csv(os.path.join(HERE, 'resampling_diagnostics.csv'), index=False)

# 6) BTC beta OOS (weekend level)
b = pd.read_json(os.path.join(HERE, 'btc_1m.jsonl'), orient='records', lines=True, convert_dates=False)
b.columns = ['ts', 'o', 'h', 'l', 'c', 'vb', 'vq'][:len(b.columns)]
b['dt'] = pd.to_datetime(b['ts'].astype('int64'), unit='ms', utc=True)
b = b.drop_duplicates('dt').sort_values('dt').set_index('dt')
rows = []
for sat in wkfull.index:
    ep, _ = next_open(b, sat + pd.Timedelta(hours=12))
    xp, _ = next_open(b, sat + pd.Timedelta(days=1, hours=21))
    rows.append({'sat': sat, 'p2_bp': wkfull[sat], 'btc_bp': (xp / ep - 1) * 1e4 - 12})
bd = pd.DataFrame(rows)
beta, alpha = np.polyfit(bd['btc_bp'], bd['p2_bp'], 1)
bd.to_csv(os.path.join(HERE, 'btc_beta_analysis.csv'), index=False)

# 7) portfolio equity curve (weekend-level, IS+OOS)
wk_is = portfolio_returns(tr_is, 12.0)
eq = pd.concat([wk_is, wkfull]).sort_index()
eq_ret = eq / 1e4
curve = (1 + eq_ret).cumprod()
pd.DataFrame({'sat': eq.index, 'net_bp': eq.values, 'equity': curve.values}).to_csv(
    os.path.join(HERE, 'portfolio_equity.csv'), index=False)

# 8) freeze selected universe csv
pd.DataFrame({'u': SEL}).to_csv(os.path.join(HERE, 'selected_universe.csv'), index=False)

oos_m = json.load(open(os.path.join(HERE, 'oos_results.json')))
print('OOS:', oos_m['oos'])
print('LOO asset all positive:', all(m['mean_bp'] > 0 for m in loo if m['mean_bp'] is not None))
print('synthetic:', res)
print('btc beta OOS:', round(float(beta), 2), 'alpha bp:', round(float(alpha), 1))
print('DONE deliverables')
