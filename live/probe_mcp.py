#!/usr/bin/env python3
"""Probe bitget-mcp-server (https://agent.bitget.com/mcp) — list tools, try US-stock data calls.

Streamable-HTTP MCP: initialize -> capture mcp-session-id header -> initialized -> tools/call.
Every response is an SSE body; parse the `data:` line.
"""
import json
import urllib.request

BASE = 'https://agent.bitget.com/mcp'


def post(body, sid=None, timeout=30):
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


def main():
    init = {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize',
            'params': {'protocolVersion': '2024-11-05', 'capabilities': {},
                       'clientInfo': {'name': 'p2-weekend-bounce', 'version': '1.0'}}}
    _, sid = post(init)
    print('session:', sid)
    post({'jsonrpc': '2.0', 'method': 'notifications/initialized'}, sid)
    res, _ = post({'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list'}, sid)
    tools = res['result']['tools']
    print(len(tools), 'tools:')
    for t in tools:
        print('-', t['name'], '|', (t.get('description') or '').split('.')[0][:100])


if __name__ == '__main__':
    main()
