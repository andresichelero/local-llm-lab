import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

from benchmark.practical_mcp import Server


def test_pagination_and_recovery(tmp_path):
    server = Server(tmp_path / 'state.json')
    rows, cursor = [], None
    while True:
        result = server.call('list_issues', {'cursor': cursor, 'page_size': 2})
        rows.extend(result['items'])
        cursor = result['next_cursor']
        if cursor is None:
            break
    assert len(rows) == 6
    assert sum(r['estimate'] for r in rows if r['status'] == 'open') == 18
    assert server.call('get_change', {'change_id': 'C-17'})['version'] == 1
    with pytest.raises(ValueError):
        server.call('apply_change', {'change_id': 'C-17', 'version': 1, 'idempotency_key': 'C-17-v2'})
    assert server.call('get_change', {'change_id': 'C-17'})['version'] == 2
    args = {'change_id': 'C-17', 'version': 2, 'idempotency_key': 'C-17-v2'}
    with pytest.raises(ValueError, match='temporary'):
        server.call('apply_change', args)
    assert server.call('apply_change', args)['applied'] is True
    assert server.call('apply_change', args)['applied'] is True
    assert json.loads((tmp_path / 'state.json').read_text())['apply_count'] == 1


def test_real_stdio_jsonrpc(tmp_path):
    source = Path(importlib.util.find_spec('benchmark.practical_mcp').origin)
    proc = subprocess.Popen([sys.executable, str(source), str(tmp_path / 'state.json')],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    try:
        for ident, method, params in [(1, 'initialize', {'protocolVersion': '2024-11-05'}),
                                      (2, 'tools/list', {}),
                                      (3, 'tools/call', {'name': 'list_issues', 'arguments': {}})]:
            proc.stdin.write(json.dumps({'jsonrpc': '2.0', 'id': ident, 'method': method, 'params': params}) + '\n')
            proc.stdin.flush()
            result = json.loads(proc.stdout.readline())
            assert result['id'] == ident
            assert 'result' in result
        assert len(json.loads(result['result']['content'][0]['text'])['items']) == 2
    finally:
        proc.stdin.close()
        proc.wait(timeout=5)
