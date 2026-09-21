#!/usr/bin/env python3
"""Study 11: formal 60D IS + 30D OOS P2 validation with universe selection in IS only.

Timeline (frozen): IS = 2026-06-19 .. 2026-08-17 (60d), OOS = 2026-08-18 .. 2026-09-17 (30d).
Eligibility: perp 1m history covering full 06-19..09-17 window with <2d missing.
IS: nested split (Dev 06-19..07-29 40d, Val 07-30..08-17 19d) for symbol scoring & K choice.
OOS runner reads frozen config only.
"""
import pandas as pd, numpy as np, os, json, glob, hashlib

HERE = os.path.dirname(os.path.abspath(__file__))
D1 = os.path.join(HERE, 'pair_1m')
IS_START = pd.Timestamp('2026-06-19', tz='UTC')
IS_END = pd.Timestamp('2026-08-17', tz='UTC')
OOS_START = pd.Timestamp('2026-08-18', tz='UTC')
OOS_END = pd.Timestamp('2026-09-20', tz='UTC')  # last COMPLETE weekend (exit Sun 09-20 21:01)

_cache = {}

def load1m(u):
    if u in _cache:
        return _cache[u]
    f = os.path.join(D1, f'{u}USDT_perp.jsonl')
    df = pd.read_json(f, orient='records', lines=True, convert_dates=False)
    ncol = len(df.columns)
    df.columns = ['ts', 'o', 'h', 'l', 'c', 'vb', 'vq', 'vq2'][:ncol]
    df['dt'] = pd.to_datetime(df['ts'].astype('int64'), unit='ms', utc=True)
    for c in ('o', 'h', 'l', 'c', 'vb'):
        df[c] = pd.to_numeric(df[c], errors='coerce')
    df = df.drop_duplicates('dt').sort_values('dt').set_index('dt')
    _cache[u] = df
    return df


def eligible_universe():
    rows = []
    for f in sorted(os.listdir(D1)):
        if not f.endswith('USDT_perp.jsonl'):
            continue
        u = f.replace('USDT_perp.jsonl', '')
        df = load1m(u)
        t0, t1 = df.index[0], df.index[-1]
        # SLIDING window: asset eligible if it has 90d of continuous history ending at OOS_END
        # (i.e., covers [OOS_END-90d, OOS_END]); IS part uses whatever falls in IS window
        need0 = OOS_END - pd.Timedelta(days=90)
        if not (t0 <= need0 and t1 >= OOS_END):
            # allow later start if it still covers >=90d ending at OOS_END
            if not (t0 <= IS_START and t1 >= OOS_END):
                rows.append({'u': u, 'start': str(t0.date()), 'end': str(t1.date()), 'eligible': False,
                             'reason': f'history {t0.date()}..{t1.date()} too short for 90d ending 09-17'})
                continue
        win_start = max(t0, IS_START)
        sub = df.loc[win_start:OOS_END]
        expect = int((OOS_END - win_start).total_seconds() // 60) + 1
        miss = expect - len(sub)
        ok = miss / expect < 0.02
        rows.append({'u': u, 'start': str(t0.date()), 'end': str(t1.date()), 'eligible': ok,
                     'bars': len(sub), 'missing_min': int(miss), 'missing_pct': round(miss / expect * 100, 2),
                     'reason': 'ok' if ok else f'missing {miss/expect*100:.1f}%'})
    return pd.DataFrame(rows)


def load_funding():
    fund = {}
    for f in glob.glob(os.path.join(HERE, 'pair_funding', '*.jsonl')) + [os.path.join(HERE, 'pair_funding', 'funding_hist.jsonl')]:
        u = os.path.basename(f).replace('.jsonl', '').replace('USDT', '')
        if u == 'funding_hist':
            u = 'NVDA'
        rows = [json.loads(l) for l in open(f) if l.strip()]
        if rows:
            d = pd.DataFrame(rows)
            d['dt'] = pd.to_datetime(d['fundingTime'].astype('int64'), unit='ms', utc=True)
            d['rate'] = pd.to_numeric(d['fundingRate'])
            fund[u] = d.sort_values('dt').set_index('dt')['rate']
    return fund


FUND = load_funding()


def funding_over(u, t0, t1):
    if u not in FUND:
        return 0.0
    s = FUND[u].loc[t0:t1]
    return float(s.sum()) if len(s) else 0.0


def get_bar(df, ts, field):
    pos = df.index.searchsorted(ts, side='right') - 1
    if pos < 0:
        return None
    v = df[field].iloc[pos]
    return None if pd.isna(v) else v


def next_open(df, ts):
    pos = df.index.searchsorted(ts, side='left')
    if pos < len(df.index) and df.index[pos] == ts:
        pos += 1
    if pos >= len(df.index):
        return None, None
    return df['o'].iloc[pos], df.index[pos]


def weekend_trades(universe, t0, t1, entry_h=12, exit_h=21):
    """Generate causal weekend basket trades for Saturdays in [t0,t1]."""
    data = {u: load1m(u) for u in universe}
    out = []
    sats = pd.date_range(t0, t1, freq='W-SAT')
    for wsat in sats:
        sig_t = wsat + pd.Timedelta(hours=entry_h)
        xit_t = wsat + pd.Timedelta(days=1, hours=exit_h)
        for u, df in data.items():
            p0 = get_bar(df, wsat, 'c')
            p1 = get_bar(df, sig_t, 'c')
            if p0 is None or p1 is None or p1 / p0 - 1 >= 0:
                continue
            # freshness: reference bars recent
            pos0 = df.index.searchsorted(wsat, side='right') - 1
            pos1 = df.index.searchsorted(sig_t, side='right') - 1
            if (wsat - df.index[pos0]).total_seconds() > 6 * 3600:
                continue
            if (sig_t - df.index[pos1]).total_seconds() > 6 * 3600:
                continue
            ep, ets = next_open(df, sig_t)
            xp, xts = next_open(df, xit_t)
            if ep is None or xp is None or ets >= xit_t:
                continue
            win = df.loc[ets:xts]
            if len(win) < 30:
                continue
            gross = xp / ep - 1
            fsum = funding_over(u, ets, xts)
            mae = win['l'].min() / ep - 1
            mfe = win['h'].max() / ep - 1
            sat_am = p1 / p0 - 1
            out.append({'sat': wsat, 'u': u, 'entry_ts': ets, 'exit_ts': xts,
                        'entry_px': ep, 'exit_px': xp, 'sat_am_bp': sat_am * 1e4,
                        'gross_bp': gross * 1e4, 'fund_bp': fsum * 1e4,
                        'mae_bp': mae * 1e4, 'mfe_bp': mfe * 1e4})
    return pd.DataFrame(out)


def portfolio_returns(tr, cost_rt_bp):
    """Weekend-level equal-weight portfolio returns (statistical unit = weekend)."""
    if len(tr) == 0:
        return pd.Series(dtype=float)
    tr = tr.copy()
    tr['net_bp'] = tr['gross_bp'] + tr['fund_bp'] - cost_rt_bp
    wk = tr.groupby('sat')['net_bp'].mean()
    return wk  # in bp


def metrics(wk_bp, n_weeks_per_year=52):
    r = wk_bp / 1e4
    if len(r) == 0:
        return {}
    cum = (1 + r).cumprod()
    dd = cum - cum.cummax()
    dn = r[r < 0]
    dsd = np.sqrt((dn ** 2).mean()) if len(dn) else np.nan
    var95 = np.percentile(r, 5)
    return {'weekends': int(len(r)), 'trades': None,
            'total_pct': round((cum.iloc[-1] - 1) * 100, 2),
            'mean_bp': round(r.mean() * 1e4, 1), 'median_bp': round(r.median() * 1e4, 1),
            'win': round((r > 0).mean(), 3),
            'sharpe_ann': round(r.mean() / r.std() * np.sqrt(52), 2) if r.std() > 0 else None,
            'sortino_ann': round(r.mean() / dsd * np.sqrt(52), 2) if dsd and dsd > 0 else None,
            'maxDD_pct': round(dd.min() * 100, 2),
            'worst_bp': round(r.min() * 1e4, 1), 'best_bp': round(r.max() * 1e4, 1),
            'VaR95_bp': round(var95 * 1e4, 1),
            'CVaR95_bp': round(r[r <= var95].mean() * 1e4, 1) if (r <= var95).any() else None}
