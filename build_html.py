#!/usr/bin/env python3
"""Build the submission HTML report via template placeholders (no f-string JS)."""
import pandas as pd, numpy as np, json, os

HERE = os.path.dirname(os.path.abspath(__file__))
D = os.path.join(HERE, 'data')

wk = pd.read_csv(os.path.join(D, 'weekend_returns.csv'), index_col=0, parse_dates=True)
eq = pd.read_csv(os.path.join(D, 'portfolio_equity.csv'), parse_dates=['sat'])
cs = pd.read_csv(os.path.join(D, 'cost_sensitivity.csv'))
mc = json.load(open(os.path.join(D, 'monte_carlo.json')))
oos = json.load(open(os.path.join(D, 'oos_results.json')))
frozen = json.load(open(os.path.join(D, 'strategy_frozen_config.json')))
tr = pd.read_csv(os.path.join(D, 'trade_log.csv'), parse_dates=['sat'])

OOS_START = pd.Timestamp('2026-08-18', tz='UTC')

labels = [str(s)[:10] for s in eq['sat']]
is_line = [round(v, 4) if s < OOS_START else None for s, v in zip(eq['sat'], eq['equity'])]
oos_line = [round(v, 4) if s >= OOS_START else None for s, v in zip(eq['sat'], eq['equity'])]
wk_labels = [str(s)[:10] for s in wk.index]
wk_vals = [round(v, 1) for v in wk['net_bp']]
wk_colors = ['#3b82f6' if s < OOS_START else '#10b981' for s in wk.index]
mca = mc['hist_A']
mca_labels = [round(e, 0) for e in mca[1][:-1]]
mcc = mc['hist_C']
mcc_labels = [round(e, 0) for e in mcc[1][:-1]]
cs_labels = [f"{int(c)}bp" for c in cs['cost_rt_bp']]
cs_vals = [round(v, 1) for v in cs['mean_bp']]
tr['net'] = tr['gross_bp'] + tr['fund_bp'] - 12.0
scatter = [{'x': round(r, 0), 'y': round(n, 1)} for r, n in zip(tr['sat_am_bp'], tr['net'])]
mon = wk.copy(); mon['m'] = [str(s)[:7] for s in mon.index]
MO = mon.groupby('m')['net_bp'].mean()
mon_labels = MO.index.tolist(); mon_vals = [round(v, 1) for v in MO.values]

TPL = open(os.path.join(HERE, 'report_template.html')).read()
rep = {
    '__TITLE__': 'P2 · Weekend Bounce Harvester',
    '__OOS_TOTAL__': str(oos['oos']['total_pct']),
    '__OOS_MEAN__': str(oos['oos']['mean_bp']),
    '__OOS_SHARPE__': str(oos['oos']['sharpe_ann']),
    '__MC_P5__': f"{mc['A_iid_bootstrap']['p5']:.0f}",
    '__MCB_P5__': f"{mc['B_block_bootstrap']['p5']:.0f}",
    '__UNIVERSE__': ' / '.join(frozen['selected']),
    '__EQ_LABELS__': json.dumps(labels),
    '__EQ_IS__': json.dumps(is_line),
    '__EQ_OOS__': json.dumps(oos_line),
    '__WK_LABELS__': json.dumps(wk_labels),
    '__WK_VALS__': json.dumps(wk_vals),
    '__WK_COLORS__': json.dumps(wk_colors),
    '__MCA_LABELS__': json.dumps(mca_labels),
    '__MCA_COUNTS__': json.dumps(mca[0]),
    '__MCC_LABELS__': json.dumps(mcc_labels),
    '__MCC_COUNTS__': json.dumps(mcc[0]),
    '__CS_LABELS__': json.dumps(cs_labels),
    '__CS_VALS__': json.dumps(cs_vals),
    '__SCATTER__': json.dumps(scatter),
    '__MON_LABELS__': json.dumps(mon_labels),
    '__MON_VALS__': json.dumps(mon_vals),
}
for k, v in rep.items():
    TPL = TPL.replace(k, v)
open(os.path.join(HERE, 'index.html'), 'w').write(TPL)
print('index.html written', len(TPL), 'chars')
