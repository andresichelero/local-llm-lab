"""Small real MCP stdio server for the practical selection round (stdlib only)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ISSUES = [
    {'id': 101, 'status': 'open', 'estimate': 3},
    {'id': 102, 'status': 'closed', 'estimate': 5},
    {'id': 103, 'status': 'open', 'estimate': 8},
    {'id': 104, 'status': 'open', 'estimate': 2},
    {'id': 105, 'status': 'closed', 'estimate': 1},
    {'id': 106, 'status': 'open', 'estimate': 5},
]


def schema(properties, required=()):
    return {'type': 'object', 'properties': properties, 'required': list(required),
            'additionalProperties': False}


TOOLS = [
    {'name': 'list_issues', 'description': 'List all issues, at most two per page. Follow next_cursor until null.',
     'inputSchema': schema({'cursor': {'type': ['string', 'null']},
                            'page_size': {'type': 'integer', 'minimum': 1, 'maximum': 2}})},
    {'name': 'get_change', 'description': 'Read current version and required idempotency key for a change.',
     'inputSchema': schema({'change_id': {'type': 'string'}}, ('change_id',))},
    {'name': 'apply_change', 'description': 'Apply a change at its current version. Retry temporary errors with the same idempotency key.',
     'inputSchema': schema({'change_id': {'type': 'string'}, 'version': {'type': 'integer'},
                            'idempotency_key': {'type': 'string'}},
                           ('change_id', 'version', 'idempotency_key'))},
]


class Server:
    def __init__(self, state_path: Path):
        self.path = state_path
        self.state = (json.loads(state_path.read_text()) if state_path.exists() else
                      {'apply_count': 0, 'temporary_seen': False, 'calls': []})

    def call(self, name, args):
        self.state['calls'].append({'name': name, 'arguments': args})
        try:
            if name == 'list_issues':
                cursor = args.get('cursor') or '0'
                size = args.get('page_size', 2)
                if not isinstance(cursor, str) or not cursor.isdigit() or type(size) is not int or not 1 <= size <= 2:
                    raise ValueError('cursor must be a returned cursor and page_size 1..2')
                start = int(cursor)
                if start > len(ISSUES):
                    raise ValueError('invalid cursor')
                return {'items': ISSUES[start:start + size],
                        'next_cursor': str(start + size) if start + size < len(ISSUES) else None}
            if name == 'get_change' and args.get('change_id') == 'C-17':
                reads = sum(c['name'] == 'get_change' for c in self.state['calls'])
                return {'change_id': 'C-17', 'version': 1 if reads == 1 else 2,
                        'idempotency_key': 'C-17-v2'}
            if name == 'apply_change':
                if (args.get('change_id') != 'C-17' or type(args.get('version')) is not int
                        or args.get('version') != 2 or args.get('idempotency_key') != 'C-17-v2'):
                    raise ValueError('invalid or stale version; refresh current change with get_change')
                if not self.state['temporary_seen']:
                    self.state['temporary_seen'] = True
                    raise ValueError('temporary service failure; retry same request')
                self.state['apply_count'] = 1
                return {'change_id': 'C-17', 'applied': True, 'version': 2}
            raise ValueError('unknown tool or change')
        except (ValueError, TypeError, KeyError):
            self.state['error_count'] = self.state.get('error_count', 0) + 1
            raise
        finally:
            self.path.write_text(json.dumps(self.state))

    def respond(self, request):
        method, params = request.get('method'), request.get('params', {})
        if 'id' not in request:
            return None
        if method == 'initialize':
            result = {'protocolVersion': params.get('protocolVersion', '2024-11-05'),
                      'capabilities': {'tools': {}},
                      'serverInfo': {'name': 'practical-lab', 'version': '1.0.0'}}
        elif method == 'tools/list':
            result = {'tools': TOOLS}
        elif method == 'tools/call':
            try:
                value = self.call(params.get('name'), params.get('arguments', {}))
                result = {'content': [{'type': 'text', 'text': json.dumps(value)}], 'isError': False}
            except (ValueError, TypeError, KeyError) as exc:
                result = {'content': [{'type': 'text', 'text': str(exc)}], 'isError': True}
        elif method == 'ping':
            result = {}
        else:
            return {'jsonrpc': '2.0', 'id': request['id'],
                    'error': {'code': -32601, 'message': 'Method not found'}}
        return {'jsonrpc': '2.0', 'id': request['id'], 'result': result}


def main():
    server = Server(Path(sys.argv[1]))
    for line in sys.stdin:
        try:
            response = server.respond(json.loads(line))
        except (ValueError, TypeError, KeyError):
            continue
        if response is not None:
            print(json.dumps(response), flush=True)


if __name__ == '__main__':
    main()
