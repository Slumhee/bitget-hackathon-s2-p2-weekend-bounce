#!/usr/bin/env python3
"""bitget-signal perception layer (cross-crypto context for the weekend window).

Official Agent Hub `bitget-signal` skills are backed by a PUBLIC streamable-HTTP
MCP server: https://datahub.noxiaohao.com/mcp — no account, no API key.

Verified-usable tool: technical_analysis (action=full_analysis, CCXT pair
format 'BTC/USDT'). Macro/sentiment/news tools have been measured hollow
(empty {error:""} responses) — wired here with graceful degradation only.

Output: a compact BTC-regime annotation appended to the weekend paper log,
since the backtest showed BTC beta 0.48 on strategy returns.
"""
import json
import time
import urllib.request

BASE = 'https://datahub.noxiaohao.com/mcp'
_session = {'id': None}
_rpc = [0]
_cache = {'ts': 0.0, 'data': None}
TTL = 300  # 5 min server-side-ish cache; also caps dead-tool damage


def _post(body, sid=None, timeout=9):
    headers = {'Content-Type': 'application/json',
               'Accept': 'application/json, text/event-stream',
               'User-Agent': 'p2-weekend-bounce/1.0'}
    if sid:
        headers['mcp-session-id'] = sid
    req = urllib.request.Request(BASE, data=json.dumps(body).encode(), headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        sid_out = r.headers.get('mcp-session-id')
        raw = r.read().decode()
    data = None
    for line in raw.splitlines():
        if line.startswith('data:'):
            data = json.loads(line[5:].strip())
    return data, sid_out


def _sid():
    if _session['id'] is None:
        _, sid = _post({'jsonrpc': '2.0', 'id': 0, 'method': 'initialize',
                        'params': {'protocolVersion': '2024-11-05', 'capabilities': {},
                                   'clientInfo': {'name': 'p2-weekend-bounce', 'version': '1.0'}}})
        try:
            _post({'jsonrpc': '2.0', 'method': 'notifications/initialized'}, sid)
        except Exception:  # noqa: BLE001
            pass
        _session['id'] = sid
    return _session['id']


def _call(name, args):
    _rpc[0] += 1
    body = {'jsonrpc': '2.0', 'id': _rpc[0], 'method': 'tools/call',
            'params': {'name': name, 'arguments': args}}
    try:
        res, _ = _post(body, _sid())
    except Exception:  # noqa: BLE001
        _session['id'] = None
        res, _ = _post(body, _sid())
    if res is None or 'result' not in res:
        return None
    content = res['result'].get('content') or []
    return content[0].get('text', '') if content else None


def btc_context():
    """BTC technical regime snapshot (cached). Returns dict or None on failure."""
    if time.time() - _cache['ts'] < TTL and _cache['data'] is not None:
        return _cache['data']
    txt = _call('technical_analysis', {'action': 'full_analysis', 'pair': 'BTC/USDT'})
    if not txt:
        _cache.update(ts=time.time(), data=None)
        return None
    try:
        d = json.loads(txt)
    except json.JSONDecodeError:
        return None
    out = {}
    try:
        d = json.loads(txt) if isinstance(txt, str) else txt
        out['price'] = d.get('ma', {}).get('price') or d.get('support_resistance', {}).get('current_price')
        out['rsi14'] = d.get('rsi', {}).get('rsi')
        out['rsi_signal'] = d.get('rsi', {}).get('signal')
        out['macd_cross'] = d.get('macd', {}).get('cross')
        out['ma_trend'] = d.get('ma', {}).get('trend')
        out['verdict'] = d.get('verdict')
    except Exception:  # noqa: BLE001
        return None
    _cache.update(ts=time.time(), data=out)
    return out


if __name__ == '__main__':
    print(json.dumps(btc_context(), indent=1))
