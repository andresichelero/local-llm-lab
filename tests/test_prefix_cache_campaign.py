"""Offline tests for the prefix-cache campaign planner."""
from benchmark.prefix_cache_campaign import estimate_tokens, schedule


def test_schedule_pairs_each_task_and_repetition():
    tasks = [{'id': 'a', 'host': 'one'}, {'id': 'b', 'host': 'two'}]
    units = schedule(tasks)
    assert len(units) == 18
    assert {(u['task'], u['repetition']) for u in units if u['arm'] == 'P-W16'} == {
        (task, rep) for task in ('a', 'b') for rep in (1, 2, 3)
    }


def test_estimate_is_conservative_for_empty_and_ascii():
    assert estimate_tokens('') == 0
    assert estimate_tokens('abcde') == 2


def test_prefix_fit_is_stable_and_respects_budget():
    from benchmark.prefix_cache_campaign import fit_prefix

    prefix = ('abc\n' * 100).encode()
    fitted = fit_prefix(prefix, ['one', 'longer'], lambda p, s: len(p) + len(s), 53)
    assert fitted.endswith(b'\n')
    assert len(fitted) + len('longer') <= 53
    assert fitted == fit_prefix(prefix, ['longer', 'one'], lambda p, s: len(p) + len(s), 53)
    assert len(fitted) < len(prefix)


def test_wilson_and_pairing():
    from benchmark.prefix_cache_campaign import summarize

    rows = [{'arm': arm, 'task': 'a', 'repetition': 1, 'success': success, 'category': 'success' if success else 'model'}
            for arm, success in [('P-W16', True), ('P-WL-cold', False), ('P-WL-warm', True)]]
    result = summarize(rows)
    assert result['arms']['P-W16']['successes'] == 1
    assert 0 < result['arms']['P-W16']['wilson_95'][0] < 1
    assert result['pairs']['P-W16__P-WL-cold']['left_only'] == 1


def test_lifecycle_cold_and_warm():
    from benchmark.prefix_cache_campaign import run_lifecycle

    events = []
    class Server:
        def __init__(self, name):
            self.name = name
        def __enter__(self):
            events.append(('start', self.name))
            return self
        def __exit__(self, *args):
            events.append(('stop', self.name))
    units = [{'arm': arm, 'host': 'h', 'task': str(i), 'repetition': 1}
             for arm in ('P-WL-cold', 'P-WL-warm') for i in range(2)]
    run_lifecycle(units, lambda arm, host, index: Server(arm),
                  lambda server, host: events.append(('warm', host)),
                  lambda server, unit: events.append(('run', unit['arm'])))
    assert events.count(('start', 'P-WL-cold')) == 2
    assert events.count(('start', 'P-WL-warm')) == 1
    assert events.count(('warm', 'h')) == 1


def test_selection_uses_only_public_relevant_files(tmp_path):
    from benchmark.prefix_cache_campaign import select_context

    (tmp_path / 'source.py').write_text('a\n' * 100 + 'def parse_query():\n' + 'b\n' * 100)
    task = {'objective': 'Repair parse_query', 'relevant_files': ['source.py']}
    result = select_context(task, tmp_path, max_chars=80)
    assert 'def parse_query()' in result['source.py']
    assert result == select_context(task, tmp_path, max_chars=80)
    assert result['source.py'] in (tmp_path / 'source.py').read_text()


def test_classification_and_running_server_refusal(monkeypatch):
    import types

    import pytest

    from benchmark import prefix_cache_campaign as campaign

    result = types.SimpleNamespace(state='rejected', reason='invalid_format')
    assert campaign.classify_result(result, {'passed': False}, {'passed': False})[1] == 'model'
    assert campaign.classify_result(result, {'passed': False}, {'passed': False}, False)[1] == 'infrastructure'
    monkeypatch.setattr(campaign.subprocess, 'run', lambda *a, **k: types.SimpleNamespace(returncode=0))
    with pytest.raises(RuntimeError, match='llama-server'):
        campaign.ensure_no_server()


def test_real_runner_repair_then_private_grade(monkeypatch, tmp_path):
    import types

    from benchmark import prefix_cache_campaign as campaign

    task = {'id': 'py_query', 'host': 'bottle-0.13.2', 'class': 'python_fix',
            'objective': 'Repair query', 'relevant_files': ['bottle.py']}
    events = []
    def prepare(config, task_id, workspace):
        workspace.mkdir()
        (workspace / 'bottle.py').write_text('x = 1\n')
    def visible(*args, **kwargs):
        events.append('visible')
        return {'passed': events.count('visible') == 2, 'stdout': 'visible failure', 'stderr': ''}
    def grade(*args, **kwargs):
        events.append('private')
        return {'passed': True, 'status': 'pass'}
    class Client:
        def __init__(self, *args):
            self.rows = []
        def count_tokens(self, messages, timeout):
            assert not any('private' in str(m) for m in messages)
            return 20
        def generate(self, messages, *args):
            before, after = ('1', '2') if events.count('visible') == 0 else ('2', '3')
            self.rows.append({'ttft_ms': 1, 'timings': {'prompt_n': 10, 'cache_n': 5,
                                                        'predicted_n': 4, 'predicted_per_second': 20}})
            return f'FILE: bottle.py\n<<<<<<< SEARCH\nx = {before}\n=======\nx = {after}\n>>>>>>> REPLACE\n'
    monkeypatch.setattr(campaign.baseline, 'prepare_workspace', prepare)
    monkeypatch.setattr(campaign, 'isolated_verify',
                        lambda config, task_id, output, kind, *args:
                        visible() if kind == 'visible' else grade())
    monkeypatch.setattr(campaign.baseline, 'sample_vram', lambda *args: None)
    monkeypatch.setattr(campaign, 'MeasuredClient', Client)
    server = types.SimpleNamespace(port=1, process=types.SimpleNamespace(poll=lambda: None))
    unit = {'arm': 'P-W16', 'host': task['host'], 'task': task['id'], 'repetition': 1}
    row = campaign.run_episode({}, task, unit, server, None, tmp_path / 'episode')
    assert events == ['visible', 'visible', 'private']
    assert row['success'] and row['repairs'] == 1
    assert row['prompt_n'] == 20 and row['cache_n'] == 10 and row['generated_tokens'] == 8


def test_isolated_visible_verifier_offline(tmp_path):
    import json

    import pytest

    from benchmark import prefix_cache_campaign as campaign

    if not campaign.guard.worker_capabilities()['supported']:
        pytest.skip('Landlock ABI 4 is unavailable')
    config = json.loads(campaign.CONFIG.read_text(encoding='utf-8'))
    output = tmp_path / 'episode'
    (output / 'workspace').mkdir(parents=True)
    (output / 'home').mkdir()
    (output / 'workspace' / 'bottle.py').write_text('x = 1\n')
    result = campaign.isolated_verify(config, 'py_query', output, 'visible')
    assert result['passed'] is False
    assert result['returncode'] != 0


def test_streamed_metrics_from_fake_server(monkeypatch):
    import json
    import urllib.request

    from benchmark.prefix_cache_campaign import MeasuredClient, metric_summary

    class Response:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def __iter__(self):
            events = [
                {'choices': [{'delta': {'content': 'hello'}}]},
                {'choices': [], 'timings': {'prompt_n': 100, 'cache_n': 80,
                                            'predicted_n': 10, 'predicted_per_second': 25}},
            ]
            return iter([b'data: ' + json.dumps(event).encode() + b'\n' for event in events]
                        + [b'data: [DONE]\n'])
    monkeypatch.setattr(urllib.request, 'urlopen', lambda *args, **kwargs: Response())
    client = MeasuredClient('http://fake')
    assert client.generate([{'role': 'user', 'content': 'x'}], 10, 5, True) == 'hello'
    metrics = metric_summary(client.rows)
    assert metrics['ttft_ms'] is not None
    assert metrics['generated_tokens'] == 10
    assert metrics['cache_fraction'] == 80 / 180
    assert metrics['decode_tok_s'] == 25


def test_classify_private_grader_infrastructure():
    import types

    from benchmark.prefix_cache_campaign import classify_result

    result = types.SimpleNamespace(state='infrastructure_error', reason='RuntimeError')
    failure, category = classify_result(result, {'passed': True}, {'passed': None, 'status': 'infrastructure'})
    assert failure == 'grader_infrastructure'
    assert category == 'infrastructure'


def test_continuation_releases_followup_only_after_first_visible_pass(monkeypatch, tmp_path):
    import types

    from benchmark import prefix_cache_campaign as campaign

    task = {'id': 'cont_path', 'host': 'bottle-0.13.2', 'class': 'continuation',
            'objective': 'Shift path', 'relevant_files': ['bottle.py']}
    events = []
    def prepare(config, task_id, workspace):
        workspace.mkdir()
        (workspace / 'bottle.py').write_text('x = 1\n')
    def verify(config, task_id, output, kind, phase1=False):
        events.append((kind, phase1))
        return ({'passed': True, 'stdout': '', 'stderr': ''} if kind == 'visible'
                else {'passed': True, 'status': 'pass'})
    class Client:
        def __init__(self, *args):
            self.rows = []
        def count_tokens(self, messages, timeout):
            return 20
        def generate(self, messages, *args):
            n = len([event for event in events if event[0] == 'visible'])
            self.rows.append({'ttft_ms': 1, 'timings': {}})
            return f'FILE: bottle.py\n<<<<<<< SEARCH\nx = {n + 1}\n=======\nx = {n + 2}\n>>>>>>> REPLACE\n'
    monkeypatch.setattr(campaign.baseline, 'prepare_workspace', prepare)
    monkeypatch.setattr(campaign.baseline, 'release_followup', lambda *args: events.append(('release', False)))
    monkeypatch.setattr(campaign.baseline, 'sample_vram', lambda *args: None)
    monkeypatch.setattr(campaign, 'isolated_verify', verify)
    monkeypatch.setattr(campaign, 'MeasuredClient', Client)
    server = types.SimpleNamespace(port=1, process=types.SimpleNamespace(poll=lambda: None))
    unit = {'arm': 'P-W16', 'host': task['host'], 'task': task['id'], 'repetition': 1}
    row = campaign.run_episode({}, task, unit, server, None, tmp_path / 'episode')
    assert events == [('visible', True), ('release', False), ('visible', False), ('oracle', False)]
    assert row['success'] and len(row['phases']) == 2


def test_continuation_uses_a_single_repair_for_the_whole_episode(monkeypatch, tmp_path):
    import types

    from benchmark import prefix_cache_campaign as campaign

    task = {'id': 'cont_path', 'host': 'bottle-0.13.2', 'class': 'continuation',
            'objective': 'Shift path', 'relevant_files': ['bottle.py']}
    calls = []
    def prepare(config, task_id, workspace):
        workspace.mkdir()
        (workspace / 'bottle.py').write_text('x = 1\n')
    def verify(config, task_id, output, kind, phase1=False):
        calls.append((kind, phase1))
        if kind == 'oracle':
            return {'passed': False, 'status': 'fail'}
        return {'passed': calls.count(('visible', True)) == 2 if phase1 else False,
                'stdout': 'new diagnostic', 'stderr': ''}
    class Client:
        def __init__(self, *args):
            self.rows = []
        def count_tokens(self, messages, timeout):
            return 20
        def generate(self, messages, *args):
            n = len(self.rows) + 1
            self.rows.append({'ttft_ms': 1, 'timings': {}})
            return f'FILE: bottle.py\n<<<<<<< SEARCH\nx = {n}\n=======\nx = {n + 1}\n>>>>>>> REPLACE\n'
    monkeypatch.setattr(campaign.baseline, 'prepare_workspace', prepare)
    monkeypatch.setattr(campaign.baseline, 'release_followup', lambda *args: None)
    monkeypatch.setattr(campaign.baseline, 'sample_vram', lambda *args: None)
    monkeypatch.setattr(campaign, 'isolated_verify', verify)
    monkeypatch.setattr(campaign, 'MeasuredClient', Client)
    server = types.SimpleNamespace(port=1, process=types.SimpleNamespace(poll=lambda: None))
    unit = {'arm': 'P-W16', 'host': task['host'], 'task': task['id'], 'repetition': 1}
    row = campaign.run_episode({}, task, unit, server, None, tmp_path / 'episode')
    assert row['state'] == 'rejected'
    assert row['repairs'] == 1 and row['generations'] == 3
    assert calls[-2:] == [('visible', False), ('oracle', False)]
