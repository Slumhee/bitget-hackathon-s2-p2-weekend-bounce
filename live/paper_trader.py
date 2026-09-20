#!/usr/bin/env python3
"""Paper trader for the P2 Weekend Bounce strategy on Bitget.

Two modes:
  - SHADOW (default, no key): signals from public 1m data, fills simulated at
    the next-bar open exactly like the backtest engine. Every event appended
    to live/logs/paper_<saturday>.jsonl. This log IS the paper-trading evidence.
  - DEMO (BITGET_DEMO_API_KEY/SECRET/PASSPHRASE set): same loop, but orders are
    placed on Bitget demo trading via the x-simulated-trading: 1 header
    (UTA v2 mix order endpoint, HMAC-SHA256 auth).

Loop cadence: poll every POLL_SECONDS (default 300 = 5 min).
Strategy: frozen v1.0 — Sat 12:00 UTC signal, 12:01 entry, Sun 21:01 exit,
equal weight 1x gross across triggered names, equity-per-name sizing.
"""
import hashlib
import hmac
import base64
import json
import os
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from bitget_market import UNIVERSE, load_cache, refresh, fetch_1m  # noqa: E402
from weekend_signal import SIGNAL_H, EXIT_H, sat_signal, first_bar_after, utc  # noqa: E402

LOG_DIR = os.path.join(HERE, 'logs')
POLL_SECONDS = int(os.environ.get('POLL_SECONDS', '300'))
NOTIONAL_USDT = float(os.environ.get('PAPER_NOTIONAL', '1000'))  # total gross 1x
COST_RT_BP = 12.0  # frozen assumption, shadow-mode accounting

DEMO_KEY = os.environ.get('BITGET_DEMO_API_KEY', '')
DEMO_SECRET = os.environ.get('BITGET_DEMO_SECRET', '')
DEMO_PASS = os.environ.get('BITGET_DEMO_PASSPHRASE', '')
MODE = 'demo' if DEMO_KEY else 'shadow'


def log_path(sat_iso):
    return os.path.join(LOG_DIR, f'paper_{sat_iso}.jsonl')


def emit(sat_iso, event):
    os.makedirs(LOG_DIR, exist_ok=True)
    event['logged_at'] = datetime.now(timezone.utc).isoformat()
    with open(log_path(sat_iso), 'a') as fh:
        fh.write(json.dumps(event) + '\n')
    print(json.dumps(event, ensure_ascii=False))


# ---------------------------------------------------------------- demo orders
def _demo_request(method, path, body=None):
    """Signed request against Bitget UTA v2 with demo header. Raises on API error."""
    ts = str(int(time.time() * 1000))
    body_str = json.dumps(body) if body else ''
    pre = ts + method + path + body_str
    sign = base64.b64encode(
        hmac.new(DEMO_SECRET.encode(), pre.encode(), hashlib.sha256).digest()).decode()
    req = urllib.request.Request(
        'https://api.bitget.com' + path,
        data=body_str.encode() if body else None,
        headers={
            'ACCESS-KEY': DEMO_KEY, 'ACCESS-SIGN': sign, 'ACCESS-TIMESTAMP': ts,
            'ACCESS-PASSPHRASE': DEMO_PASS, 'Content-Type': 'application/json',
            'x-simulated-trading': '1', 'User-Agent': 'p2-weekend-bounce/1.0',
        }, method=method)
    with urllib.request.urlopen(req, timeout=15) as r:
        out = json.loads(r.read().decode())
    if out.get('code') != '00000':
        raise RuntimeError(f'bitget demo API error: {out}')
    return out


def place_demo_market(sym, side, size):
    return _demo_request('POST', '/api/v2/mix/order/place', {
        'symbol': f'{sym}USDT', 'productType': 'USDT-FUTURES',
        'marginMode': 'crossed', 'marginCoin': 'USDT',
        'side': side, 'orderType': 'market', 'size': str(size)})


# ---------------------------------------------------------------- trader loop
def trader_state(sat_iso):
    """Replay log -> current open positions + realized weekends."""
    positions, realized = {}, []
    p = log_path(sat_iso)
    if not os.path.exists(p):
        return positions, realized
    for line in open(p):
        ev = json.loads(line)
        if ev['event'] == 'entry_fill':
            positions[ev['symbol']] = ev
        elif ev['event'] == 'exit_fill':
            realized.append(ev)
            positions.pop(ev['symbol'], None)
    return positions, realized


def shadow_pnl(entry, exit_px):
    gross = (exit_px / entry['entry_px'] - 1) * 1e4
    return round(gross - COST_RT_BP, 2)


def run_weekend(sat_iso):
    """One iteration of the trading loop for the weekend of sat_iso."""
    sat = datetime.fromisoformat(sat_iso).replace(tzinfo=timezone.utc)
    sat_ms = int(sat.timestamp() * 1000)
    sig_ms = sat_ms + SIGNAL_H * 3600_000
    xit_ms = sat_ms + (24 + EXIT_H) * 3600_000
    now_ms = int(time.time() * 1000)

    refresh()  # pull newest 1m bars for all 9 symbols
    positions, realized = trader_state(sat_iso)

    # --- ENTRY PHASE -------------------------------------------------------
    if now_ms >= sig_ms and not positions and not realized:
        entries = []
        for sym in UNIVERSE:
            rows, _ = load_cache(sym)
            sig = sat_signal(rows, sat_ms)
            if sig is None:
                continue
            eb = first_bar_after(rows, sig_ms)
            if eb is None or eb[0] > now_ms:
                continue
            per_name = NOTIONAL_USDT / 9  # 1/N sizing on full universe gross=1x
            ev = {'event': 'entry_fill', 'mode': MODE, 'symbol': sym,
                  'sat_am_bp': sig['sat_am_bp'],
                  'entry_ts': eb[0], 'entry_px': eb[1],
                  'notional_usdt': round(per_name, 2)}
            if MODE == 'demo':
                try:
                    size = round(per_name / eb[1], 3)
                    res = place_demo_market(sym, 'buy', size)
                    ev['demo_order'] = res.get('data', {}).get('orderId')
                except Exception as e:  # noqa: BLE001
                    ev['demo_error'] = str(e)
            entries.append(ev)
            emit(sat_iso, ev)
        if entries:
            emit(sat_iso, {'event': 'entry_batch_done', 'n': len(entries),
                           'gross_exposure': round(sum(e['notional_usdt'] for e in entries), 2)})

    # --- EXIT PHASE --------------------------------------------------------
    elif now_ms >= xit_ms and positions:
        exited = []
        for sym, pos in positions.items():
            rows, _ = load_cache(sym)
            xb = first_bar_after(rows, xit_ms)
            if xb is None:
                continue
            ev = {'event': 'exit_fill', 'mode': MODE, 'symbol': sym,
                  'exit_ts': xb[0], 'exit_px': xb[1],
                  'entry_ts': pos['entry_ts'], 'entry_px': pos['entry_px']}
            if MODE == 'demo':
                try:
                    size = round(pos['notional_usdt'] / pos['entry_px'], 3)
                    res = place_demo_market(sym, 'sell', size)
                    ev['demo_order'] = res.get('data', {}).get('orderId')
                except Exception as e:  # noqa: BLE001
                    ev['demo_error'] = str(e)
            ev['net_bp_shadow'] = shadow_pnl(pos, xb[1])
            emit(sat_iso, ev)
            exited.append(sym)
        if exited and len(exited) == len(positions):
            emit(sat_iso, {'event': 'weekend_done'})
        elif exited:
            emit(sat_iso, {'event': 'exit_partial', 'filled': exited,
                           'pending': [s for s in positions if s not in exited]})

    # --- MARK PHASE (open positions, mid-weekend) --------------------------
    elif positions:
        marks = {}
        for sym, pos in positions.items():
            rows, _ = load_cache(sym)
            if rows:
                last = rows[-1]
                marks[sym] = {'px': last[4],
                              'unreal_bp': round((last[4] / pos['entry_px'] - 1) * 1e4, 2)}
        if marks:
            ev = {'event': 'mark', 'marks': marks,
                  'unreal_mean_bp': round(sum(m['unreal_bp'] for m in marks.values())
                                          / len(marks), 2)}
            try:  # bitget-signal perception layer (official Agent Hub skill backend)
                from bitget_signal import btc_context
                btc = btc_context()
                if btc:
                    ev['btc_context'] = btc  # strategy BTC beta 0.48 — regime context
            except Exception:  # noqa: BLE001
                pass
            emit(sat_iso, ev)
    return positions


def current_saturday_iso():
    now = datetime.now(timezone.utc)
    offset = (now.weekday() - 5) % 7
    return (now - timedelta(days=offset)).date().isoformat()


if __name__ == '__main__':
    sat_iso = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith('-') else current_saturday_iso()
    once = '--once' in sys.argv
    emit(sat_iso, {'event': 'loop_start', 'mode': MODE,
                   'saturday': sat_iso, 'notional_usdt': NOTIONAL_USDT})
    while True:
        try:
            pos = run_weekend(sat_iso)
            if not pos and trader_state(sat_iso)[1]:
                emit(sat_iso, {'event': 'loop_exit', 'reason': 'weekend complete'})
                break
        except Exception as e:  # noqa: BLE001
            emit(sat_iso, {'event': 'error', 'error': str(e)})
        if once:
            break
        time.sleep(POLL_SECONDS)
