import json

import pytest

from benchmark import baseline_stage5 as stage5


@pytest.mark.parametrize(('failure', 'visible', 'phase1', 'expected'), [
    ('model_oracle_failed', True, [], False),
    ('model_visible_failed', False, [], True),
    ('model_wall_timeout', None, [], True),
    ('model_phase1_incomplete', None, [False], True),
    ('server_exited', False, [], False),
    ('grader_infrastructure', None, [], False),
    ('grader_infrastructure', False, [], True),
    ('harness_session_mismatch', False, [], False),
    (None, True, [], False),
])
def test_escalation_uses_only_visible_and_model_failures(failure, visible, phase1, expected):
    result = {'failure': failure, 'visible': {'passed': visible},
              'phase1_visible': [{'passed': value} for value in phase1]}
    assert stage5.should_escalate(result) is expected


def test_cascade_runs_second_only_after_visible_failure_and_preserves_attempts():
    attempts = []

    def run(variant):
        attempts.append(variant)
        return {'failure': 'model_visible_failed' if variant == 'control' else None,
                'visible': {'passed': variant != 'control'}, 'phase1_visible': [],
                'oracle': {'passed': variant != 'control'}, 'category': 'model' if variant == 'control' else 'success',
                'total_seconds': 1}

    result = stage5.run_cascade(run, 'think')
    assert attempts == ['control', 'think']
    assert result['escalated'] is True
    assert result['first_pass'] is False
    assert result['final_pass'] is True
    assert len(result['attempts']) == 2


def test_dry_run_does_not_start_execution(monkeypatch, capsys):
    monkeypatch.setattr(stage5, 'execute', lambda *_: pytest.fail('started inference'))
    stage5.main(['--dry-run'])
    output = capsys.readouterr().out
    assert 'Q5-UDQ4XL' in output and 'X-think' in output and 'X-9b' in output


def test_execute_cascade_uses_new_workspace_and_thinking_server(tmp_path, monkeypatch):
    config = stage5.load_config()
    config['output'] = str(tmp_path)
    config['tasks'] = ['py_query']
    config['arms'] = {'X-think': config['arms']['X-think']}
    monkeypatch.setattr(stage5, 'manifest', lambda _: {'protocol_id': 'test'})
    monkeypatch.setattr(stage5.subprocess, 'run', lambda *a, **k: type('P', (), {'returncode': 1})())
    variants = []

    class Pool:
        def __init__(self, config, output):
            self.switches = []

        def get(self, arm):
            variants.append(arm['thinking'])
            return type('Server', (), {'process': None, 'port': 0, 'path': tmp_path})(), arm

        def close(self):
            pass

    def fake_run(config, unit, output, process, port, log):
        workspace = output / 'workspace'
        workspace.mkdir(parents=True)
        assert not (workspace / 'edited').exists()
        (workspace / 'edited').write_text('changed')
        thinking = config['arms']['X-think']['thinking']
        return {'unit': unit, 'failure': None if thinking else 'model_visible_failed',
                'visible': {'passed': thinking}, 'phase1_visible': [],
                'category': 'success' if thinking else 'model', 'total_seconds': 1}

    monkeypatch.setattr(stage5, 'ServerPool', Pool)
    monkeypatch.setattr(stage5.baseline, 'run_attempt', fake_run)
    monkeypatch.setattr(stage5.baseline, 'sample_vram', lambda stop, rows: stop.wait())
    stage5.execute(config, stage5.baseline.schedule(config))
    result = json.loads((tmp_path / 'units/X-think/py_query-r1/cascade.json').read_text())
    assert variants == [False, True]
    assert result['escalated'] is True and result['final_pass'] is True
    assert (tmp_path / 'units/X-think/py_query-r1/attempt-01/workspace/edited').exists()
    assert (tmp_path / 'units/X-think/py_query-r1/attempt-02/workspace/edited').exists()


def test_cascade_summary_reports_rates_and_escalation_cost():
    rows = [
        {'first_pass': False, 'final_pass': True, 'escalated': True,
         'total_seconds': 12, 'escalation_extra_seconds': 7},
        {'first_pass': True, 'final_pass': True, 'escalated': False,
         'total_seconds': 3, 'escalation_extra_seconds': 0},
    ]
    assert stage5.summarize_cascades(rows) == {
        'units': 2, 'first_pass_rate': 0.5, 'final_pass_rate': 1.0,
        'escalations': 1, 'total_seconds': 15, 'escalation_extra_seconds': 7}


def test_9b_context_falls_back_if_headroom_is_too_small(tmp_path, monkeypatch):
    config = stage5.load_config()
    contexts = []
    closed = []

    class FakeServer:
        def __init__(self, config, arm, output):
            self.context = arm['context']
            self.process = type('P', (), {'poll': lambda self: None})()

        def __enter__(self):
            contexts.append(self.context)
            return self

        def __exit__(self, *args):
            closed.append(self.context)

    headroom = iter([499, 600])
    monkeypatch.setattr(stage5.baseline, 'Server', FakeServer)
    monkeypatch.setattr(stage5, 'free_vram_mib', lambda: next(headroom))
    pool = stage5.ServerPool(config, tmp_path)
    arm = {**config['arms']['X-9b'], 'model': 'q9', 'fit_9b': True, 'context': 32768}
    _, selected = pool.get(arm)
    assert contexts == [32768, 16384]
    assert closed == [32768]
    assert selected['context'] == 16384
    assert pool.switches[0]['status'] == 'insufficient_headroom'
    _, reused = pool.get(arm)
    assert reused['context'] == 16384
    pool.close()


def test_rtk_hook_installs_only_plugin_and_rewrites_sandbox_command(tmp_path, monkeypatch):
    config = stage5.load_config()
    plugin = tmp_path / 'rtk.ts'
    plugin.write_text('plugin')
    config['rtk_plugin'] = str(plugin)
    config['rtk_binary'] = str(tmp_path / 'rtk')
    home = tmp_path / 'home'
    home.mkdir()
    monkeypatch.setattr(stage5.baseline, 'bwrap_command',
                        lambda config, workspace, home, command: ['bwrap', '--', *command])
    with stage5.tool_hooks(config, {'rtk': True}):
        command = stage5.baseline.bwrap_command(config, tmp_path, home,
                                                ['/opt/opencode/opencode', 'run', '--pure'])
        environment = stage5.baseline.sandbox_environment()
    assert '--pure' not in command
    assert '--ro-bind' in command and '/opt/rtk/rtk' in command
    assert environment['PATH'].startswith('/opt/rtk:')
    assert (home / '.config/opencode/plugins/rtk.ts').read_text() == 'plugin'


def test_server_pool_does_not_overwrite_existing_server_logs(tmp_path, monkeypatch):
    (tmp_path / 'server-004').mkdir()
    directories = []

    class FakeServer:
        def __init__(self, config, arm, output):
            directories.append(output.name)
            self.process = type('P', (), {'poll': lambda self: None})()

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    monkeypatch.setattr(stage5.baseline, 'Server', FakeServer)
    pool = stage5.ServerPool(stage5.load_config(), tmp_path)
    pool.get(stage5.load_config()['arms']['X-think'])
    assert directories == ['server-005']
    pool.close()


def test_timeout_with_dead_server_is_not_escalated(tmp_path, monkeypatch):
    config = stage5.load_config()
    config.update(output=str(tmp_path), tasks=['py_query'])
    config['arms'] = {'X-think': config['arms']['X-think']}
    monkeypatch.setattr(stage5, 'manifest', lambda _: {'protocol_id': 'test'})
    monkeypatch.setattr(stage5.subprocess, 'run', lambda *a, **k: type('P', (), {'returncode': 1})())
    monkeypatch.setattr(stage5.baseline, 'sample_vram', lambda stop, rows: stop.wait())
    variants = []

    class Pool:
        def __init__(self, config, output):
            self.switches = []

        def get(self, arm):
            variants.append(arm['thinking'])
            process = type('P', (), {'poll': lambda self: 1})()
            return type('S', (), {'process': process, 'port': 0, 'path': tmp_path})(), arm

        def close(self):
            pass

    def fake_run(config, unit, output, process, port, log):
        output.mkdir()
        return {'failure': 'model_wall_timeout', 'category': 'model', 'visible': {'passed': False},
                'phase1_visible': [], 'total_seconds': 1}

    monkeypatch.setattr(stage5, 'ServerPool', Pool)
    monkeypatch.setattr(stage5.baseline, 'run_attempt', fake_run)
    with pytest.raises(RuntimeError, match='infrastructure'):
        stage5.execute(config, stage5.baseline.schedule(config))
    assert variants == [False]
    path = tmp_path / 'units/X-think/py_query-r1/attempt-01/result.json'
    assert json.loads(path.read_text())['failure'] == 'server_exited'


def test_lsp_sandbox_installs_launch_tracers_in_episode_home(tmp_path, monkeypatch):
    config = stage5.load_config()
    home = tmp_path / 'home'
    home.mkdir()
    monkeypatch.setattr(stage5.baseline, 'bwrap_command',
                        lambda config, workspace, home, command: ['bwrap', '--', *command])
    with stage5.tool_hooks(config, {'lsp': True, 'lsp_tool': True}):
        command = stage5.baseline.bwrap_command(config, tmp_path, home, ['/opt/opencode/cli', 'run'])
        env = stage5.baseline.sandbox_environment()
    assert '/opt/lsp/node_modules' in command
    assert env['PATH'].startswith('/episode-home/.local/bin:/opt/lsp/node_modules/.bin:')
    assert env['OPENCODE_EXPERIMENTAL_LSP_TOOL'] == 'true'
    assert (home / '.local/bin/pyright-langserver').stat().st_mode & 0o111


def test_9b_headroom_checks_peak_as_well_as_post_episode_free_memory():
    assert stage5.minimum_headroom(8192, 800, 7800) == 392
    assert stage5.minimum_headroom(8192, 700, 7400) == 700
    assert stage5.minimum_headroom(8192, 700, None) is None


def test_9b_exception_still_uses_server_log_as_oom_evidence(tmp_path, monkeypatch):
    config = stage5.load_config()
    config.update(output=str(tmp_path), tasks=['py_query'])
    config['arms'] = {'X-9b': config['arms']['X-9b']}
    monkeypatch.setattr(stage5, 'manifest', lambda _: {'protocol_id': 'test'})
    monkeypatch.setattr(stage5.subprocess, 'run', lambda *a, **k: type('P', (), {'returncode': 1})())
    monkeypatch.setattr(stage5.baseline, 'sample_vram', lambda stop, rows: stop.wait())
    monkeypatch.setattr(stage5, 'vram_capacity_and_free', lambda: (8192, 800))
    contexts = []

    class Pool:
        def __init__(self, config, output):
            self.switches = []

        def get(self, arm):
            contexts.append((arm['model'], arm['context']))
            dead = arm['model'] == 'q9' and arm['context'] == 65536
            path = tmp_path / f'server-{len(contexts)}.log'
            path.write_text('')
            process = type('P', (), {'poll': lambda self: 1 if dead else None})()
            return type('S', (), {'process': process, 'port': 0, 'path': path})(), arm

        def close(self):
            pass

    def fake_run(config, unit, output, process, port, log):
        output.mkdir()
        arm = config['arms']['X-9b']
        if arm['model'] == 'q4':
            return {'category': 'model', 'failure': 'model_visible_failed',
                    'visible': {'passed': False}, 'total_seconds': 1}
        if arm['context'] == 65536:
            log.write_text('CUDA error: out of memory')
            return {'category': 'infrastructure', 'failure': 'unexpected_error', 'total_seconds': 1}
        return {'category': 'success', 'failure': None, 'visible': {'passed': True},
                'peak_vram_mib': 7000, 'total_seconds': 1}

    monkeypatch.setattr(stage5, 'ServerPool', Pool)
    monkeypatch.setattr(stage5.baseline, 'run_attempt', fake_run)
    stage5.execute(config, stage5.baseline.schedule(config))
    assert contexts == [('q4', 65536), ('q9', 65536), ('q9', 49152)]
    result = json.loads((tmp_path / 'units/X-9b/py_query-r1/cascade.json').read_text())
    assert result['escalated'] and result['final_pass']


def test_private_grader_exception_is_a_returned_infrastructure_status(monkeypatch):
    def broken(*args, **kwargs):
        raise TimeoutError('private grader timed out')

    monkeypatch.setattr(stage5.baseline, 'grade', broken)
    with stage5.tool_hooks(stage5.load_config(), {}):
        result = stage5.baseline.grade(None, None, None, None)
    assert result['passed'] is None
    assert result['status'] == 'infrastructure'


def test_9b_oom_at_smallest_context_is_infrastructure(tmp_path, monkeypatch):
    config = stage5.load_config()
    config.update(output=str(tmp_path), tasks=['py_query'])
    config['arms'] = {'X-9b': config['arms']['X-9b']}
    monkeypatch.setattr(stage5, 'manifest', lambda _: {'protocol_id': 'test'})
    monkeypatch.setattr(stage5.subprocess, 'run', lambda *a, **k: type('P', (), {'returncode': 1})())
    monkeypatch.setattr(stage5.baseline, 'sample_vram', lambda stop, rows: stop.wait())
    monkeypatch.setattr(stage5, 'vram_capacity_and_free', lambda: (8192, 800))

    class Pool:
        def __init__(self, config, output):
            self.switches = []

        def get(self, arm):
            log = tmp_path / f"{arm['model']}.log"
            log.write_text('')
            process = type('P', (), {'poll': lambda self: None})()
            selected = {**arm, 'context': 8192} if arm['model'] == 'q9' else arm
            return type('S', (), {'process': process, 'port': 0, 'path': log})(), selected

        def close(self):
            pass

    def fake_run(config, unit, output, process, port, log):
        output.mkdir()
        if config['arms']['X-9b']['model'] == 'q9':
            log.write_text('CUDA out of memory')
        return {'category': 'model', 'failure': 'model_wall_timeout', 'visible': {'passed': False},
                'peak_vram_mib': 7000, 'total_seconds': 1}

    monkeypatch.setattr(stage5, 'ServerPool', Pool)
    monkeypatch.setattr(stage5.baseline, 'run_attempt', fake_run)
    with pytest.raises(RuntimeError, match='OOM'):
        stage5.execute(config, stage5.baseline.schedule(config))


@pytest.mark.parametrize(('row', 'failure', 'expected'), [
    ({'status': 200, 'error': 'ConnectionResetError'}, 'model_wall_timeout', False),
    ({'status': 200, 'error': 'ConnectionResetError'}, None, True),
    ({'status': 500, 'error': None}, 'model_wall_timeout', True),
    ({'status': 200, 'error': 'HTTPError'}, 'model_wall_timeout', True),
    ({'status': 200, 'error': None}, None, False),
])
def test_wall_timeout_client_abort_is_not_server_error(row, failure, expected):
    assert stage5.server_side_error(row, failure) is expected
