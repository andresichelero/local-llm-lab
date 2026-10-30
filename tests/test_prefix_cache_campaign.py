"""Offline tests for the prefix-cache campaign planner."""
from benchmark.prefix_cache_campaign import (
    estimate_tokens,
    schedule,
    terminate_last_marker,
)


def test_v3_schedule_and_marker_detection():
    from benchmark.prefix_cache_campaign import marker_in_search

    assert len(schedule([{'id': 'a', 'host': 'h'}], 1)) == 3
    assert marker_in_search('<<<<<<< SEARCH\n# task-specific line withheld\n=======\nx\n>>>>>>> REPLACE\n')
    assert not marker_in_search('<<<<<<< SEARCH\nx\n=======\n# task-specific line withheld\n>>>>>>> REPLACE\n')


def test_withheld_alignment_after_insertions():
    from benchmark.prefix_cache_campaign import withheld_section

    prefix = 'a\nb\n# task-specific line withheld\nd\ne\nf\n'
    current = 'new\na\nb\nchanged\nd\ne\nf\n'
    section = withheld_section(prefix, current, 'bottle.py')
    assert '4: changed' in section
    assert '2: a' in section and '6: e' in section
    assert section == withheld_section(prefix, current, 'bottle.py')


def test_withheld_line_deleted_by_an_edit_shows_surrounding_text():
    from benchmark.prefix_cache_campaign import withheld_section

    section = withheld_section('a\n# task-specific line withheld\nb\n', 'a\nb\n', 'bottle.py')
    assert '1: a\n2: b' in section


def test_wl_package_contains_current_withheld_lines_only_for_wl(tmp_path):
    import json

    from benchmark import prefix_cache_campaign as campaign

    task = json.loads((campaign.CORPUS / 'tasks/py_range/task.json').read_text())
    source = campaign.CORPUS / 'hosts' / task['host'] / 'bottle.py'
    (tmp_path / 'bottle.py').write_bytes(source.read_bytes())
    w16 = campaign.make_package(task, tmp_path, 'P-W16')
    cold = campaign.make_package(task, tmp_path, 'P-WL-cold')
    warm = campaign.make_package(task, tmp_path, 'P-WL-warm')
    assert 'withheld_prefix_lines' not in w16.readonly_context
    section = cold.readonly_context['withheld_prefix_lines']
    assert section == warm.readonly_context['withheld_prefix_lines']
    assert section in cold.markdown and 'never from a marker line' in section


def test_summary_counts_repair_episodes_and_last_rejection():
    from benchmark.prefix_cache_campaign import summarize

    rows = [{'arm': 'P-W16', 'task': 'a', 'repetition': 1, 'success': False,
             'category': 'model', 'edit_repair': True, 'visible_repair': True,
             'last_edit_rejection': 'zero_occurrences'}]
    arm = summarize(rows)['arms']['P-W16']
    assert arm['edit_repair_episodes'] == arm['visible_repair_episodes'] == 1
    assert arm['last_edit_rejection_statuses'] == {'zero_occurrences': 1}


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
    assert row['visible_repair'] and not row['edit_repair']
    assert row['last_edit_rejection'] is None and not row['marker_in_search']
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
    (output / 'verify-tmp').mkdir()
    (output / 'workspace' / 'bottle.py').write_text('x = 1\n')
    result = campaign.isolated_verify(config, 'py_query', output, 'visible')
    assert result['passed'] is False
    assert result['returncode'] != 0


def test_visible_candidate_cannot_read_private_files_or_modify_journal(tmp_path):
    import json

    import pytest

    from benchmark import prefix_cache_campaign as campaign

    if not campaign.guard.worker_capabilities()['supported']:
        pytest.skip('Landlock ABI 4 is unavailable')
    config = json.loads(campaign.CONFIG.read_text(encoding='utf-8'))
    output = tmp_path / 'episode'
    workspace = output / 'workspace'
    workspace.mkdir(parents=True)
    (output / 'verify-tmp').mkdir()
    journal = output / 'journal.jsonl'
    journal.write_text('preserved', encoding='utf-8')
    (workspace / 'bottle.py').write_text('x = 1\n', encoding='utf-8')
    campaign.isolated_verify(config, 'py_query', output, 'oracle')
    paths = [campaign.CORPUS / 'oracles' / 'py_query' / 'oracle.py',
             output / 'verify-oracle' / 'oracle.py',
             campaign.CORPUS / 'tasks' / 'py_query' / 'reference.patch',
             campaign.CORPUS / 'tasks' / 'py_query' / 'bug.patch']
    code = 'from pathlib import Path\n'
    for path in paths:
        code += f'try:\n print("LEAK:", Path({str(path)!r}).read_text())\nexcept OSError:\n print("DENIED")\n'
    code += f'try:\n Path({str(journal)!r}).write_text("altered")\nexcept OSError:\n print("DENIED WRITE")\n'
    code += 'raise RuntimeError("candidate diagnostic")\n'
    (workspace / 'bottle.py').write_text(code, encoding='utf-8')
    result = campaign.isolated_verify(config, 'py_query', output, 'visible')
    diagnostic = result['stdout'] + result['stderr']
    assert diagnostic.count('DENIED') == 5 and 'LEAK:' not in diagnostic
    assert journal.read_text(encoding='utf-8') == 'preserved'


def test_isolated_oracle_executes_and_classifies_candidate_failure(tmp_path):
    import json

    import pytest

    from benchmark import prefix_cache_campaign as campaign

    if not campaign.guard.worker_capabilities()['supported']:
        pytest.skip('Landlock ABI 4 is unavailable')
    config = json.loads(campaign.CONFIG.read_text(encoding='utf-8'))
    output = tmp_path / 'episode'
    (output / 'workspace').mkdir(parents=True)
    (output / 'verify-tmp').mkdir()
    (output / 'workspace' / 'bottle.py').write_text('def _parse_qsl(value): return []\n', encoding='utf-8')
    result = campaign.isolated_verify(config, 'py_query', output, 'oracle')
    assert result['passed'] is False and result['status'] == 'fail'
    for broken in ('import definitely_missing_module\n', 'def broken(:\n'):
        (output / 'workspace' / 'bottle.py').write_text(broken, encoding='utf-8')
        result = campaign.isolated_verify(config, 'py_query', output, 'oracle')
        assert result['passed'] is False and result['status'] == 'fail'


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


def test_classify_preserves_proven_visible_rejection_when_oracle_unavailable():
    import types

    from benchmark.prefix_cache_campaign import classify_result

    result = types.SimpleNamespace(state='rejected', reason='no_new_visible_diagnostic')
    failure, category = classify_result(result, {'passed': False}, {'passed': None, 'status': 'infrastructure'})
    assert (failure, category) == ('no_new_visible_diagnostic', 'model')


def test_verification_permissions_are_scoped_by_kind(monkeypatch, tmp_path):
    from benchmark import prefix_cache_campaign as campaign

    output = tmp_path / 'episode'
    (output / 'workspace').mkdir(parents=True)
    (output / 'verify-tmp').mkdir()
    (output / 'verify-visible').mkdir()
    (output / 'verify-oracle').mkdir()
    calls = []
    monkeypatch.setattr(campaign.guard, 'disable_process_inspection', lambda: None)
    monkeypatch.setattr(campaign.guard, 'restrict_candidate_process', lambda **kw: calls.append(kw))
    monkeypatch.setattr(campaign.baseline, '_check_visible', lambda *a, **kw: {'passed': False}, raising=False)
    monkeypatch.setattr(campaign.baseline, '_grade', lambda *a, **kw: {'passed': False}, raising=False)
    config = {'tasks': ['py_query'], 'node': '/usr/bin/node'}
    for kind in ('visible', 'oracle'):
        campaign.verification_worker({'output': str(output), 'config': config, 'task': 'py_query',
                                      'kind': kind, 'phase1': False})
    visible, oracle = calls
    assert visible['workspace'] == output / 'workspace'
    assert visible['writable_paths'] == [output / 'verify-tmp']
    assert campaign.CORPUS / 'oracles' / 'py_query' not in visible['helper_paths']
    assert campaign.CORPUS / 'tasks' / 'py_query' not in visible['helper_paths']
    assert output / 'verify-oracle' in oracle['helper_paths']
    assert output / 'verify-oracle' not in visible['helper_paths']


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


def test_continuation_uses_remaining_repairs_for_the_whole_episode(monkeypatch, tmp_path):
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
    assert row['repairs'] == 2 and row['generations'] == 4
    assert calls[-2:] == [('visible', False), ('oracle', False)]


def test_terminate_last_marker_restores_final_newline():
    block = 'FILE: a.py\n<<<<<<< SEARCH\nx\n=======\ny\n>>>>>>> REPLACE'
    assert terminate_last_marker(block) == block + '\n'
    assert terminate_last_marker(block + '\n\n') == block + '\n'
    assert terminate_last_marker('BLOCKED: insufficient_context') == 'BLOCKED: insufficient_context'


def test_config_selects_tasks_and_rejects_unknown_ids():
    import pytest
    from benchmark.prefix_cache_campaign import select_configured_tasks

    available = [{'id': 'old', 'host': 'h'}, {'id': 'new', 'host': 'h'}]
    assert select_configured_tasks({'tasks': ['old']}, available) == [available[0]]
    with pytest.raises(RuntimeError, match='missing'):
        select_configured_tasks({'tasks': ['missing']}, available)
