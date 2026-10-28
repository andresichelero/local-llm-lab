"""Opt-in WSL integration: actual namespaces, CPython, OpenCode and MCP, no GPU."""
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from benchmark import practical_selection as selection, practical_tasks

pytestmark = pytest.mark.skipif(os.environ.get('RUN_PRACTICAL_INTEGRATION') != '1',
                                reason='explicit WSL sandbox integration only')


def test_real_cpython_grading_and_hidden_checks(tmp_path):
    workspace = tmp_path / 'project'
    practical_tasks.seed_task('bugfix', workspace)
    assert not selection.grade(workspace, 'bugfix')
    for name, source in practical_tasks.reference_files('bugfix', variant=1).items():
        (workspace / name).write_text(source)
    assert selection.grade(workspace, 'bugfix')
    assert not (workspace / 'checks.py').exists()


def test_opencode_uses_real_mcp_through_stdio(tmp_path):
    calls = []

    class FakeModel(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            request = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            calls.append(request)
            name = next((t['function']['name'] for t in request.get('tools', [])
                         if t['function']['name'].endswith('list_issues')), None)
            has_tool = any(m.get('role') == 'tool' for m in request['messages'])
            if has_tool or name is None:
                delta, finish = {'content': 'READY'}, 'stop'
            else:
                delta = {'tool_calls': [{'index': 0, 'id': 'call_test_1', 'type': 'function',
                                        'function': {'name': name, 'arguments': '{}'}}]}
                finish = 'tool_calls'
            chunks = [{'id': 'fake-1', 'object': 'chat.completion.chunk', 'created': 1,
                       'model': request['model'], 'choices': [{'index': 0, 'delta': delta, 'finish_reason': None}]},
                      {'id': 'fake-1', 'object': 'chat.completion.chunk', 'created': 1,
                       'model': request['model'], 'choices': [{'index': 0, 'delta': {}, 'finish_reason': finish}],
                       'usage': {'prompt_tokens': 100, 'completion_tokens': 20, 'total_tokens': 120}}]
            streaming = request.get('stream') is True
            if streaming:
                data = ''.join('data: ' + json.dumps(c) + '\n\n' for c in chunks) + 'data: [DONE]\n\n'
            else:
                data = json.dumps({'id': 'fake-title', 'object': 'chat.completion', 'created': 1,
                                   'model': request['model'], 'choices': [{'index': 0,
                                   'message': {'role': 'assistant', 'content': 'Task'}, 'finish_reason': 'stop'}],
                                   'usage': {'prompt_tokens': 10, 'completion_tokens': 1, 'total_tokens': 11}})
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream' if streaming else 'application/json')
            self.send_header('Content-Length', str(len(data.encode())))
            self.end_headers()
            self.wfile.write(data.encode())

    server = ThreadingHTTPServer(('127.0.0.1', 0), FakeModel)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        workspace = tmp_path / 'project'
        workspace.mkdir()
        result = selection.run_agent(workspace, tmp_path / 'run', 'qwen3.5-4b', selection.contracts(),
                                     ['Call lab list_issues once and reply READY.', 'Now confirm READY again.'],
                                     upstream_port=server.server_port, seconds=60)
        assert not result.infrastructure_error, result
        assert result.cleanup_verified
        metadata = json.loads(result.workspace_outputs['.practical.json'])
        assert metadata['phases'][0]['exit_code'] == 0, result.output.decode(errors='replace')
        assert len(metadata['phases']) == 2
        assert metadata['phases'][0]['session_id'] == metadata['phases'][1]['session_id']
        events = [json.loads(line) for line in result.output.splitlines() if line.startswith(b'{')]
        assert any(e.get('type') == 'tool_use' and 'list_issues' in str(e.get('part', {})) for e in events)
        assert len([c for c in calls if c.get('tools')]) == 3
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
