#!/usr/bin/env python3
"""Bitget MCP data layer client (bitget-mcp-server @ https://agent.bitget.com/mcp).

Official read-only US-stock/ETF data MCP from the S2 hackathon toolbox.
No account, no API key. Streamable-HTTP MCP protocol:
  initialize -> capture mcp-session-id response header -> notifications/initialized
  -> tools/call (guide / do_query). Responses are SSE bodies; parse `data:` lines.

Session id is cached at module level; re-initialized only when a call fails.
"""
import json
import time
import urllib.request

BASE = 'https://agent.bitget.com/mcp'
_session = {'id': None, 'ts': 0.0}
_rpc_id = [0]


def _post(body, sid=None, timeout=30):
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


def _init():
    _, sid = _post({'jsonrpc': '2.0', 'id': 1, 'method': 'initialize',
                    'params': {'protocolVersion': '2024-11-05', 'capabilities': {},
                               'clientInfo': {'name': 'p2-weekend-bounce', 'version': '1.0'}}})
    _post({'jsonrpc': '2.0', 'method': 'notifications/initialized'}, sid)
    _session['id'] = sid
    _session['ts'] = time.time()
    return sid


def _sid():
    if _session['id'] is None or time.time() - _session['ts'] > 1800:
        return _init()
    return _session['id']


def _call(name, args):
    _rpc_id[0] += 1
    body = {'jsonrpc': '2.0', 'id': _rpc_id[0], 'method': 'tools/call',
            'params': {'name': name, 'arguments': args}}
    try:
        res, _ = _post(body, _sid())
    except Exception:  # noqa: BLE001 — stale session, re-init once
        _session['id'] = None
        res, _ = _post(body, _sid())
    if res is None or 'result' not in res:
        raise RuntimeError(f'MCP call {name} failed: {res}')
    content = res['result'].get('content') or []
    text = content[0].get('text', '') if content else ''
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def guide(category=None):
    args = {'category': category} if category else {}
    return _call('guide', args)


def query(entry_id, **params):
    """Execute a catalog entry, e.g. query('equity_price_historical', symbol='SPY', ...)."""
    return _call('do_query', {'entry_id': entry_id, 'params': params})


# ---------------------------------------------------------------- data helpers
def native_daily(symbol, start_date, end_date):
    """Native US-stock daily OHLCV via MCP. Returns list of bar dicts."""
    out = query('equity_price_historical', symbol=symbol,
                start_date=start_date, end_date=end_date)
    if isinstance(out, dict) and out.get('success'):
        return out.get('data', {}).get('results', [])
    raise RuntimeError(f'equity_price_historical failed for {symbol}: {str(out)[:200]}')


def native_quote(symbol):
    """Real-time native quote via MCP."""
    return query('equity_price_quote', symbol=symbol)


if __name__ == '__main__':
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == 'guide':
        print(json.dumps(guide(sys.argv[2] if len(sys.argv) > 2 else None),
                         indent=1, ensure_ascii=False))
    else:
        sym = sys.argv[1] if len(sys.argv) > 1 else 'SPY'
        bars = native_daily(sym, '2026-09-14', '2026-09-21')
        print(json.dumps(bars, indent=1)[:1200])
