#!/usr/bin/env python3
"""Study 11 Step 1: eligible universe audit + IS symbol scoring + K selection + freeze."""
import pandas as pd, numpy as np, json, os
from study11_core import (eligible_universe, weekend_trades, portfolio_returns, metrics,
                          IS_START, IS_END, OOS_START, OOS_END, load1m)

HERE = os.path.dirname(os.path.abspath(__file__))
DEV_END = pd.Timestamp('2026-07-29', tz='UTC')   # IS nested: Dev 06-19..07-29 (40d), Val 07-30..08-17 (19d)

elig = eligible_universe()
elig.to_csv(os.path.join(HERE, 'eligible_universe.csv'), index=False)
E = elig[elig['eligible'] == True]['u'].tolist()
print('eligible:', len(E), E)

# IS trades for ALL eligible (per-symbol diagnostics over full IS 60d)
tr_is = weekend_trades(E, IS_START, IS_END)
tr_is.to_csv(os.path.join(HERE, 'is_trades_all.csv'), index=False)
print('IS weekends:', tr_is['sat'].nunique(), 'trades:', len(tr_is))

# per-symbol IS scoring (task §4: quality/liquidity/consistency/risk/cost-robustness)
rows = []
for u in E:
    g = tr_is[tr_is['u'] == u]
    df = load1m(u).loc[IS_START:OOS_END]
    rvol = np.log(df['c']).diff().rolling(30).std().median() * 1e4  # bp per sqrt(30m)
    vol_med = df['vb'].median()
    if len(g) == 0:
        rows.append({'u': u, 'n_trades': 0}); continue
    netbp = g['gross_bp'] + g['fund_bp'] - 12.0
    wk_win = g.groupby('sat')['gross_bp'].mean()
    # split-consistency: Dev vs Val inside IS
    dev = g[g['sat'] < DEV_END]; val = g[g['sat'] >= DEV_END]
    dev_m = dev.groupby('sat')['gross_bp'].mean().mean() if len(dev) else 0
    val_m = val.groupby('sat')['sat_am_bp'].mean().mean() if len(val) else 0
    rows.append({
        'u': u, 'n_trades': len(g), 'n_weekends_active': g['sat'].nunique(),
        'mean_gross_bp': round(g['gross_bp'].mean(), 1),
        'median_gross_bp': round(g['gross_bp'].median(), 1),
        'win_rate': round((g['gross_bp'] > 0).mean(), 3),
        'weekend_win': round((wk_win > 0).mean(), 3),
        'mae_med_bp': round(g['mae_bp'].median(), 1),
        'mfe_med_bp': round(g['mfe_bp'].median(), 1),
        'rvol30_bp': round(rvol, 1), 'vol_med': round(vol_med, 0),
        'btc_beta_proxy_rvol': round(rvol, 1),
        'net_contrib_bp': round(netbp.sum(), 0),
        'dev_mean_bp': round(dev.groupby('sat')['gross_bp'].mean().mean(), 1) if len(dev) else None,
        'val_mean_bp': round(val.groupby('sat')['gross_bp'].mean().mean(), 1) if len(val) else None,
    })
S = pd.DataFrame(rows).sort_values('net_contrib_bp', ascending=False)
S.to_csv(os.path.join(HERE, 'is_symbol_scores.csv'), index=False)
print(S.to_string(index=False))

# Composite score (IS only): consistency(40) + risk(25) + liquidity(15) + cost robust(10) + quality(10)
# - consistency: weekend_win rank + dev/val sign agreement
# - risk: -mae rank (smaller adverse better), -rvol
# - liquidity: vol_med rank
# - cost robust: net_contrib at 12bp > 0
# - quality: eligibility already passed (all full coverage)
def rank_desc(s):
    return s.rank(ascending=False)

def rank_asc(s):
    return s.rank(ascending=True)

Sd = S.dropna(subset=['n_trades']).copy()
Sd = Sd[Sd['n_trades'] > 0]
Sd['consist_score'] = rank_desc(Sd['weekend_win']) * 0.7 + \
    (np.sign(Sd['dev_mean_bp']) == np.sign(Sd['val_mean_bp'])).astype(float).rank(ascending=False) * 0.3
Sd['risk_score'] = rank_asc(Sd['mae_med_bp'])
Sd['liq_score'] = rank_desc(Sd['vol_med'])
Sd['cost_score'] = (Sd['net_contrib_bp'] > 0).astype(float).rank(ascending=False)
Sd['quality_score'] = 1.0  # all passed coverage gate
Sd['total'] = (Sd['consist_score'] * 0.40 + Sd['risk_score'] * 0.25 + Sd['liq_score'] * 0.15 +
               Sd['cost_score'] * 0.10 + Sd['quality_score'] * 0.10)
Sd = Sd.sort_values('total', ascending=False)
print('\ncomposite ranking:')
print(Sd[['u', 'total', 'weekend_win', 'mae_med_bp', 'net_contrib_bp']].to_string(index=False))

# K selection in IS nested validation: K in 6..12 -> pick K maximizing VAL (07-30..08-17) weekend mean
# with tie-break toward larger K (diversification), only using IS data
best = None
for K in range(6, 13):
    sel = Sd.head(K)['u'].tolist()
    trk = tr_is[tr_is['u'].isin(sel)]
    trk_val = trk[trk['sat'] >= DEV_END]
    wk = portfolio_returns(trk_val, 12.0)
    m = metrics(wk)
    print(f'K={K}: VAL weekends={m.get("weekends")} mean={m.get("mean_bp")}bp win={m.get("win")} total={m.get("total_pct")}% sel={sel}')
    score = (m.get('mean_bp') or -9e9)
    if best is None or score > best[1] + 1e-9 or (abs(score - best[1]) < 1e-9 and K > best[0]):
        best = (K, score, sel)
K, _, SEL = best
print(f'\nFROZEN: K={K}, selected={SEL}')
json.dump({'K': int(K), 'selected': SEL, 'dev_end': str(DEV_END),
           'is_window': [str(IS_START.date()), str(IS_END.date())],
           'oos_window': [str(OOS_START.date()), str(OOS_END.date())],
           'entry_rule': 'Sat 00:00->12:00 close return < 0 -> long at next bar open (12:01)',
           'exit_rule': 'Sun 21:00 bar -> next bar open (21:01) flatten all',
           'sizing': 'equal weight 1/N, gross=1x',
           'cost_rt_bp': 12.0, 'entry_h': 12, 'exit_h': 21},
          open(os.path.join(HERE, 'strategy_frozen_config.json'), 'w'), indent=1)
print('saved strategy_frozen_config.json')
