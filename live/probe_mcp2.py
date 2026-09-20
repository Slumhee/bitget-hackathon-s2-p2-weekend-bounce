#!/usr/bin/env python3
"""Probe bitget-mcp-server data coverage: walk guide -> find US-stock candle tools."""
import json
import sys

sys.path.insert(0, '.') 
from probe_mcp import post  # noqa: E402


def call(sid, name, args):
    return post({'jsonrpc': '2.0', 'id': abs(hash(name + json.dumps(args, sort_keys=True))) % 10000,
                 'method': 'tools/call',
                 'params': {'name': name, 'arguments': args}}, sid)


def main():
    _, sid = post({'jsonrpc': '2.0', 'id': 1, 'method': 'initialize',
                   'params': {'protocolVersion': '2024-11-05', 'capabilities': {},
                              'clientInfo': {'name': 'p2-weekend-bounce', 'version': '1.0'}}})
    post({'jsonrpc': '2.0', 'method': 'notifications/initialized'}, sid)

    res, _ = call(sid, 'guide', {})
    text = res['result']['content'][0]['text']
    print('=== guide root ===')
    print(text[:3000])


if __name__ == '__main__':
    main()
