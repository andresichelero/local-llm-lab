import json
import subprocess
import urllib.request

import pytest

from benchmark import opencode_baseline as baseline


@pytest.mark.parametrize('failure, oracle, visible, expected', [
    # v5 bug: phase 1 hit the step cap, the oracle could not grade, and the unit was retried.
    ('model_phase1_incomplete', {'passed': None, 'status': 'infrastructure'}, {'passed': False}, 'model'),
    ('model_wall_timeout', {'passed': None, 'status': 'infrastructure'}, {'passed': False}, 'model'),
    ('grader_infrastructure', {'passed': None, 'status': 'infrastructure'}, {'passed': True}, 'infrastructure'),
    ('server_http_error', {'passed': False, 'status': 'fail'}, {'passed': False}, 'infrastructure'),
    ('harness_session_mismatch', {'passed': True, 'status': 'pass'}, {'passed': True}, 'harness'),
    ('model_oracle_failed', {'passed': False, 'status': 'fail'}, {'passed': True}, 'model'),
    (None, {'passed': True, 'status': 'pass'}, {'passed': True}, 'success'),
])
def test_classify_only_retries_real_infrastructure(failure, oracle, visible, expected):
    assert baseline.classify(failure, oracle, visible) == expected


def test_bwrap_denies_host_paths_with_runner_mounts(tmp_path):
    config = baseline.load_config()
    workspace = tmp_path / 'workspace'
    home = tmp_path / 'home'
    workspace.mkdir()
    home.mkdir()
    (workspace / 'TASK.md').write_text('visible')
    proof = baseline.verify_isolation(config, workspace, home, 'cont_path')
    assert proof['returncode'] == 0
    assert proof['workspace_readable'] is True
    assert proof['oracle_denied'] is True
    assert proof['mnt_d_denied'] is True
    assert proof['home_denied'] is True
    assert '--unshare-net' not in proof['command']


@pytest.mark.parametrize('arm_name', ['B0', 'S-qwen-sampling'])
def test_real_opencode_accepts_sandbox_profile(tmp_path, arm_name):
    config = baseline.load_config()
    workspace, home = tmp_path / 'workspace', tmp_path / 'home'
    workspace.mkdir()
    config_dir = home / '.config/opencode'
    config_dir.mkdir(parents=True)
    (config_dir / 'opencode.json').write_text(json.dumps(baseline.profile(config, config['arms'][arm_name], 1234)))
    command = baseline.bwrap_command(config, workspace, home, ['/opt/opencode/opencode.exe', 'debug', 'config'])
    result = subprocess.run(command, env=baseline.sandbox_environment(), capture_output=True, text=True, timeout=30, check=False)
    assert result.returncode == 0, result.stderr


def test_schedule_matches_matrix():
    config = baseline.load_config()
    units = baseline.schedule(config)
    assert len(units) == 300
    assert [len([u for u in units if u['stage'] == stage]) for stage in (1, 2, 3)] == [24, 60, 48]
    assert len({(u['arm'], u['task'], u['repetition']) for u in units}) == 300
    assert len([u for u in units if u['stage'] == 4]) == 168


def test_server_and_profile_follow_arm_config():
    config = baseline.load_config()
    arm = config['arms']['B-think']
    cmd = baseline.server_command(config, arm, 1234)
    assert cmd[cmd.index('--reasoning') + 1] == 'on'
    assert json.loads(cmd[cmd.index('--chat-template-kwargs') + 1]) == {'enable_thinking': True}
    profile = baseline.profile(config, arm, 1234)
    assert profile['agent']['build']['steps'] == config['steps']
    assert profile['provider']['local']['models']['local-qwen']['options']['temperature'] == 0.6
    assert '--no-cache-prompt' in baseline.server_command(config, config['arms']['B-nocache'], 1234)
    assert profile['agent']['build']['permission']['webfetch'] == 'deny'
    assert profile['agent']['build']['permission']['websearch'] == 'deny'


def test_continuation_releases_after_visible_success_and_reuses_session(tmp_path):
    calls = []

    def fake(prompt, session):
        calls.append((prompt, session))
        return {'code': 0, 'session': 'session-123', 'events': []}

    result = baseline.run_phases(fake, lambda: True, lambda: 'followup', 'first', True)
    assert result['released'] is True
    assert calls == [('first', None), ('followup', 'session-123')]
    calls.clear()
    result = baseline.run_phases(fake, lambda: False, lambda: pytest.fail('released early'), 'first', True)
    assert result['released'] is False
    assert len(calls) == 1


def test_manifest_rejects_different_protocol(tmp_path):
    path = tmp_path / 'manifest.json'
    baseline.ensure_manifest(path, {'protocol_id': 'one'})
    with pytest.raises(RuntimeError, match='refusing to mix'):
        baseline.ensure_manifest(path, {'protocol_id': 'two'})


def test_parser_errors_are_model_failures_and_do_not_retry():
    assert baseline.classify_failure(1, 'HTTP 500: invalid tool call JSON', True) == 'model_protocol_error'
    assert baseline.classify_failure(1, 'Error: Configuration is invalid at /episode-home', True) == 'harness_configuration_error'
    assert baseline.classify_failure(0, 'ordinary output: invalid tool call JSON', True) is None
    attempts = []
    result = baseline.retry_infrastructure(lambda: attempts.append(1) or {'category': 'model'})
    assert result['category'] == 'model' and len(attempts) == 1
    attempts.clear()
    baseline.retry_infrastructure(lambda: attempts.append(1) or {'category': 'infrastructure'})
    assert len(attempts) == 2


def test_successful_phase_does_not_classify_tool_output_as_parser_error():
    phase = {'code': 0, 'stderr': '', 'events': [
        {'type': 'tool_use', 'part': {'state': {'output': 'invalid tool call JSON'}}}
    ]}
    assert baseline.phase_failure(phase, 'parser output in server log', True) is None
    phase['events'].append({'type': 'error', 'error': 'invalid tool call JSON'})
    assert baseline.phase_failure(phase, '', True) == 'model_protocol_error'


def test_prepare_hides_private_and_followup(tmp_path):
    config = baseline.load_config()
    workspace = tmp_path / 'workspace'
    baseline.prepare_workspace(config, 'cont_path', workspace)
    assert (workspace / 'TASK.md').is_file()
    assert (workspace / 'verify_phase1.py').is_file()
    assert not (workspace / 'verify.py').exists()
    assert not (workspace / 'followup.json').exists()
    assert not list(workspace.rglob('oracle.py'))


@pytest.mark.parametrize('task_id', ['tests_query', 'tests_range'])
def test_real_authored_oracle_scores_bug_and_reference(tmp_path, task_id):
    config = baseline.load_config()
    workspace = tmp_path / 'workspace'
    baseline.prepare_workspace(config, task_id, workspace)
    bug_output = tmp_path / 'bug-grade'
    bug_output.mkdir()
    assert baseline.grade(config, task_id, workspace, bug_output) == {'passed': False, 'status': 'fail'}
    subprocess.run(['git', 'apply', '--whitespace=nowarn',
                    str(baseline.CORPUS / 'tasks' / task_id / 'reference.patch')],
                   cwd=workspace, check=True)
    fixed_output = tmp_path / 'reference-grade'
    fixed_output.mkdir()
    assert baseline.grade(config, task_id, workspace, fixed_output) == {'passed': True, 'status': 'pass'}


def test_server_log_metrics():
    log = 'prompt_n = 42, cache_n = 12\nprompt eval time = 100.00 ms / 10 tokens'
    data = baseline.parse_server_metrics(log)
    assert data['prompt_n'] == [42]
    assert data['cache_n'] == [12]


def test_dry_run_never_starts_server(monkeypatch, capsys):
    monkeypatch.setattr(baseline, 'execute', lambda *args: pytest.fail('GPU execution'))
    baseline.main(['--dry-run'])
    assert '132' in capsys.readouterr().out


def test_arm_can_be_selected_without_stage(monkeypatch):
    selected = []
    monkeypatch.setattr(baseline, 'execute', lambda config, units, smoke: selected.extend(units))
    baseline.main(['--arm', 'B-kv8'])
    assert len(selected) == 12
    assert {item['arm'] for item in selected} == {'B-kv8'}


def test_execute_retries_infrastructure_once_without_restarting_live_server(tmp_path, monkeypatch):
    config = baseline.load_config()
    config['output'] = str(tmp_path)
    monkeypatch.setattr(baseline, 'manifest', lambda _config: {'protocol_id': 'fake'})
    monkeypatch.setattr(baseline.subprocess, 'run', lambda *a, **k: type('Proc', (), {'returncode': 1})())
    launches, calls = [], []
    class FakeServer:
        def __init__(self, config, arm, output):
            self.process = self
            self.port = 1
            self.path = output / 'server.log'
        def __enter__(self):
            launches.append(1)
            return self
        def __exit__(self, *args):
            pass
        def poll(self):
            return None
    def attempt(config, unit, output, process, port, log):
        calls.append(output)
        return {'category': 'infrastructure' if len(calls) == 1 else 'model', 'failure': None}
    monkeypatch.setattr(baseline, 'Server', FakeServer)
    monkeypatch.setattr(baseline, 'run_attempt', attempt)
    baseline.execute(config, baseline.schedule(config)[:1])
    assert len(launches) == 1
    assert [p.name for p in calls] == ['attempt-01', 'attempt-02']


def test_fake_opencode_emits_session_and_continues(tmp_path):
    executable = tmp_path / 'opencode'
    executable.write_text(
        '#!/usr/bin/python3\n'
        'import json,sys\n'
        'session = sys.argv[sys.argv.index("--session")+1] if "--session" in sys.argv else "s-fake"\n'
        'print(json.dumps({"type":"step_finish","sessionID":session,"part":{"tokens":{"input":5,"output":2}}}))\n'
    )
    executable.chmod(0o755)
    config = baseline.load_config()
    config['opencode'] = str(executable)
    home = tmp_path / 'home'
    home.mkdir()
    first = baseline.run_cli(config, tmp_path, home, 'first', None, 5)
    second = baseline.run_cli(config, tmp_path, home, 'followup', first['session'], 5)
    assert first['code'] == second['code'] == 0
    assert first['session'] == second['session'] == 's-fake'
    assert baseline.summarize_usage('opencode', first['events'])['prompt_tokens'] == 5


def test_fake_server_and_proxy(tmp_path):
    server = tmp_path / 'server'
    server.write_text(
        '#!/usr/bin/python3\n'
        'import sys\n'
        'from http.server import HTTPServer,BaseHTTPRequestHandler\n'
        'class H(BaseHTTPRequestHandler):\n'
        ' def do_GET(self):\n  self.send_response(200); self.end_headers()\n'
        ' def do_POST(self):\n'
        '  self.rfile.read(int(self.headers["Content-Length"]))\n'
        '  self.send_response(200); self.end_headers(); self.wfile.write(b\'{"choices":[{"delta":{"content":"ok"}}],"timings":{"prompt_n":10,"cache_n":4}}\\n\')\n'
        ' def log_message(self,*args): pass\n'
        'HTTPServer(("127.0.0.1",int(sys.argv[sys.argv.index("--port")+1])),H).serve_forever()\n'
    )
    server.chmod(0o755)
    config = baseline.load_config()
    config['server'] = str(server)
    with baseline.Server(config, config['arms']['B0'], tmp_path / 'logs') as process:
        with baseline.Proxy(process.port) as proxy:
            request = urllib.request.Request(f'http://127.0.0.1:{proxy.server.server_address[1]}/v1/chat/completions',
                                             b'{}', {'Content-Type': 'application/json'})
            with urllib.request.urlopen(request, timeout=5) as response:
                assert json.load(response)['timings']['cache_n'] == 4
        assert proxy.rows[0]['timings'][0]['prompt_n'] == 10
        assert proxy.rows[0]['ttft_ms'] is not None
    assert process.process.poll() is not None


def test_fake_continuation_attempt_grades_only_after_followup(tmp_path, monkeypatch):
    executable = tmp_path / 'opencode'
    executable.write_text(
        '#!/usr/bin/python3\n'
        'import json,sys\n'
        's=sys.argv[sys.argv.index("--session")+1] if "--session" in sys.argv else "continuation-session"\n'
        'print(json.dumps({"type":"step_finish","sessionID":s,"part":{"tokens":{"input":7,"output":1}}}))\n'
    )
    executable.chmod(0o755)
    config = baseline.load_config()
    config['opencode'] = str(executable)
    monkeypatch.setattr(baseline, 'sample_vram', lambda stop, rows: None)
    log = tmp_path / 'server.log'
    log.write_text('')
    class FakeServer:
        def poll(self):
            return None
    unit = {'stage': 1, 'arm': 'B0', 'task': 'cont_path', 'repetition': 1}
    result = baseline.run_attempt(config, unit, tmp_path / 'episode', FakeServer(), 1, log)
    assert result['continuation_released'] is True
    assert [p['session'] for p in result['phases']] == ['continuation-session'] * 2
    assert result['oracle']['passed'] is False
    assert result['category'] == 'model'
    assert (tmp_path / 'episode/oracle-probe.json').is_file()
    assert not list((tmp_path / 'episode/workspace').rglob('oracle.py'))


def test_arm_overrides_and_stage4_dry_run(monkeypatch, capsys):
    config = baseline.load_config()
    arm = dict(config['arms']['B0'], stage=4, repetitions=1, steps=80,
               sampling={'temperature': 0.7, 'top_p': 0.8, 'top_k': 20,
                         'min_p': 0, 'presence_penalty': 1.5},
               server_extra_args=['--cache-reuse', '256'])
    config['arms'] = {'test': arm, 'disabled': dict(arm, enabled=False)}
    cmd = baseline.server_command(config, arm, 1)
    assert cmd[cmd.index('--min-p') + 1] == '0'
    assert cmd[cmd.index('--presence-penalty') + 1] == '1.5'
    assert cmd[-2:] == ['--cache-reuse', '256']
    options = baseline.profile(config, arm, 1)['provider']['local']['models']['local-qwen']['options']
    assert options['topP'] == 0.8 and options['presencePenalty'] == 1.5
    assert baseline.profile(config, arm, 1)['agent']['build']['steps'] == 80
    monkeypatch.setattr(baseline, 'load_config', lambda: config)
    baseline.main(['--dry-run', '--stage', '4'])
    assert 'disabled' not in capsys.readouterr().out


def test_diff_quality_detects_regressions_and_writable_paths():
    before = {'test/test_old.py': b'def test_x():\n    assert x == 1\n', 'src/a.py': b'x=1\n'}
    after = {'test/test_old.py': b'def test_x():\n    assert True\n', 'src/a.py': b'x=2\n',
             'src/new.py': b'hello\n'}
    quality = baseline.diff_quality(before, after, {'writable_files': ['src/a.py'],
                                                     'relevant_files': ['src']})
    assert quality['lines_added'] == 3 and quality['lines_removed'] == 2
    assert quality['new_files'] == ['src/new.py']
    assert quality['outside_writable'] == ['src/new.py', 'test/test_old.py']
    assert quality['weakened_test_files'] == ['test/test_old.py']


def test_taxonomy_and_tokens_after_last_edit():
    events = [
        {'type': 'tool_use', 'part': {'tool': 'edit', 'state': {'status': 'completed',
            'input': {'filePath': '/workspace/x'}, 'metadata': {'diff': '-old\n+new\n'}}}},
        {'type': 'step_finish', 'part': {'tokens': {'input': 200, 'output': 10, 'cache': {'read': 0}}}},
        {'type': 'step_finish', 'part': {'tokens': {'input': 10, 'output': 2, 'cache': {'read': 3}}}},
        {'type': 'tool_use', 'part': {'tool': 'bash', 'state': {'status': 'error', 'error': 'oops'}}},
        {'type': 'tool_use', 'part': {'tool': 'bash', 'state': {'status': 'error', 'error': 'oops'}}},
        {'type': 'tool_use', 'part': {'tool': 'bash', 'state': {'status': 'error', 'error': 'oops'}}},
    ]
    assert baseline.tokens_after_last_edit(events, {'x': '--- a/x\n+++ b/x\n-old\n+new\n'}) == {'prompt_tokens': 13, 'completion_tokens': 2}
    tags = baseline.failure_taxonomy('model_oracle_failed', {'passed': True}, {'passed': False},
                                     {'files_touched': ['x'], 'outside_relevant': ['x']}, events, 40)
    assert 'wrong_file' in tags['secondary'] or tags['primary'] == 'wrong_file'
    assert 'oracle_only' in tags['secondary'] or tags['primary'] == 'oracle_only'
    assert 'tool_error_loop' in tags['secondary'] or tags['primary'] == 'tool_error_loop'
    assert baseline.tokens_after_last_edit([], {}) is None
    assert baseline.tokens_after_last_edit(events, {'elsewhere': '-old\n+new\n'}) is None
    assert baseline.tokens_after_last_edit(events, {'x': '-other\n+other2\n', 'elsewhere': '-old\n+new\n'}) is None


def test_tool_error_loop_counts_nonzero_bash_exit():
    event = {'type': 'tool_use', 'part': {'tool': 'bash', 'state': {'status': 'completed',
             'metadata': {'exit': 1}, 'output': 'file not found'}}}
    tags = baseline.failure_taxonomy('model_cli_failure', {'passed': None}, {'passed': None},
                                     {'files_touched': []}, [event] * 3, 40)
    assert 'tool_error_loop' in [tags['primary'], *tags['secondary']]


def test_gave_up_requires_terminal_text_and_no_timeout():
    text_event = {'type': 'text', 'part': {'text': 'I cannot solve this.'}}
    tool_event = {'type': 'tool_use', 'part': {'tool': 'read'}}
    kwargs = {'visible': {'passed': False}, 'oracle': {'passed': False},
              'quality': {'files_touched': []}, 'steps': 40}
    assert 'gave_up' not in baseline.failure_taxonomy('model_wall_timeout', events=[text_event], **kwargs)['secondary']
    assert 'gave_up' not in baseline.failure_taxonomy('model_oracle_failed', events=[text_event, tool_event], **kwargs)['secondary']
    assert 'gave_up' in baseline.failure_taxonomy('model_oracle_failed', events=[tool_event, text_event], **kwargs)['secondary']


def test_request_metrics_and_resource_summary():
    rows = [{'timings': [{'prompt_n': 10, 'cache_n': 5, 'prompt_per_second': 100,
                         'predicted_per_second': 20}]}]
    result = baseline.request_metrics(rows)
    assert result['prompt_processed_tokens'] == 10 and result['prompt_cached_tokens'] == 5
    assert result['median_prefill_tokens_per_second'] == 100
    assert result['median_decode_tokens_per_second'] == 20
    assert baseline.request_metrics([{'timings': []}])['prompt_processed_tokens'] is None
    assert baseline.request_metrics(rows + [{'timings': []}])['prompt_processed_tokens'] is None
    summary = baseline.resource_summary([{'cpu_percent': 50, 'wsl_available_mib': 100,
                                          'windows_available_mib': None, 'vram_mib': 5}])
    assert summary['cpu_percent']['mean'] == 50
    assert summary['windows_available_mib']['mean'] is None
