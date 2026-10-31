import json
import sqlite3
from types import SimpleNamespace

from benchmark import long_tasks


def test_schedule_interleaves_marathons_and_keeps_all_listed_objectives():
    config = long_tasks.load_config()
    units = long_tasks.schedule(config)
    assert len(units) == 24
    assert [unit['marathon'] for unit in units[:8]] == ['M1', 'M2'] * 4
    assert len(config['marathons']['M1']) == 5
    assert len(config['marathons']['M2']) == 6
    assert [unit['arm'] for unit in units[:4]] == [
        'L-compact', 'L-bigctx', 'L-reset', 'L-headroom'
    ]
    assert len({(unit['arm'], unit['marathon']) for unit in units}) == 8
    assert len({(unit['arm'], unit['marathon'], unit['repetition']) for unit in units}) == 24


def test_regressions_require_a_prior_pass_and_a_later_failure():
    history = [
        {'a': True, 'b': False, 'c': None},
        {'a': False, 'b': True, 'c': False},
        {'a': False, 'b': False, 'c': True},
    ]
    assert long_tasks.regressions(history) == {'a': 1, 'b': 1, 'c': 0}


def test_context_series_preserves_missing_timings():
    rows = [{'timings': [{'prompt_n': 100, 'cache_n': 20}]},
            {'timings': []}, {'timings': [{'prompt_n': 30}]}]
    assert long_tasks.context_series(rows) == [120, None, None]


def test_config_is_independent_and_matches_control():
    config = long_tasks.load_config()
    assert config['wall_seconds'] == 1800
    assert config['steps'] == 40
    assert config['arms']['L-bigctx']['context'] == 131072
    assert all(arm['model'] == 'q4' and arm['kv_k'] == arm['kv_v'] == 'q4_0'
               and arm['cache_prompt'] and not arm['thinking']
               for arm in config['arms'].values())
    json.dumps(config)


def test_objectives_advance_after_failure_with_same_session():
    calls = []

    def execute(objective, session):
        calls.append((objective, session))
        return {'code': 1 if objective == 'first' else 0, 'session': 'session-1'}

    phases = long_tasks.run_sequence(['first', 'second'], execute, reset=False)
    assert calls == [('first', None), ('second', 'session-1')]
    assert len(phases) == 2


def test_reset_creates_new_session_per_objective():
    calls = []

    def execute(objective, session):
        calls.append(session)
        return {'code': 0, 'session': 's-' + objective}

    long_tasks.run_sequence(['first', 'second'], execute, reset=True)
    assert calls == [None, None]


def test_shared_session_missing_id_stops_instead_of_silent_reset():
    calls = []

    def execute(objective, session):
        calls.append(objective)
        return {'code': 1, 'session': None}

    phases = long_tasks.run_sequence(['first', 'second'], execute, reset=False)
    assert calls == ['first']
    assert phases[0]['session_error'] == 'missing_session'


def test_unobserved_session_stops_the_unit_without_silent_reset():
    calls = []

    def execute(objective, session):
        calls.append(session)
        return {'code': 0, 'session': None if objective == 'second' else 's1'}

    phases = long_tasks.run_sequence(['first', 'second', 'third'], execute, reset=False)
    assert calls == [None, 's1']
    assert phases[1]['session_error'] == 'session_unobserved'


def test_reset_rejects_duplicate_and_multiple_session_ids():
    def duplicate(objective, session):
        return {'code': 0, 'session': 'same', 'session_ids': ['same']}

    phases = long_tasks.run_sequence(['first', 'second'], duplicate, reset=True)
    assert phases[1]['session_error'] == 'reset_reused_session'

    def ambiguous(objective, session):
        return {'code': 0, 'session': None, 'session_ids': ['one', 'two']}

    phases = long_tasks.run_sequence(['first'], ambiguous, reset=False)
    assert phases[0]['session_error'] == 'multiple_sessions'


def test_compaction_count_from_database(tmp_path):
    db = tmp_path / '.local/share/opencode/opencode.db'
    db.parent.mkdir(parents=True)
    with sqlite3.connect(db) as conn:
        conn.execute('CREATE TABLE part (session_id TEXT, data TEXT)')
        conn.execute('CREATE TABLE message (session_id TEXT, data TEXT)')
        conn.executemany('INSERT INTO part VALUES (?, ?)', [
            ('s1', '{"type":"compaction","auto":true}'),
            ('s1', '{"type":"text"}'),
            ('s2', '{"type":"compaction","auto":true}')])
    assert long_tasks.count_compactions(tmp_path, ['s1']) == {'requested': 1, 'completed': 0}
    assert long_tasks.count_compactions(tmp_path / 'missing', ['s1']) is None


def test_material_is_released_one_objective_at_a_time(tmp_path):
    config = long_tasks.load_config()
    workspace = tmp_path / 'workspace'
    long_tasks.prepare_combined(config, ['py_query', 'recover_decode'], workspace)
    assert not (workspace / 'tool.py').exists()
    long_tasks.release_objective('recover_decode', workspace)
    assert (workspace / 'tool.py').is_file()
    assert 'byte-to-text' in (workspace / 'TASK.md').read_text()
    long_tasks.release_objective('py_query', workspace)
    assert not (workspace / 'tool.py').exists()
    assert 'query decoding' in (workspace / 'TASK.md').read_text()


def test_offline_marathon_grades_each_stage_and_reuses_session(tmp_path, monkeypatch):
    config = long_tasks.load_config()
    config['marathons'] = {'M1': ['py_query', 'py_range']}
    calls = []

    def fake_cli(_config, _workspace, _home, _prompt, session, _timeout, _headroom):
        calls.append(session)
        return {'code': 0, 'session': 'fake-session', 'events': [], 'stderr': '', 'seconds': 0}

    monkeypatch.setattr(long_tasks, 'run_cli', fake_cli)
    monkeypatch.setattr(long_tasks.baseline, 'sample_vram', lambda *_args: None)
    log = tmp_path / 'server.log'
    log.write_text('')
    server = SimpleNamespace(port=1, path=log, process=SimpleNamespace(poll=lambda: None))
    result = long_tasks.run_attempt(config, {'arm': 'L-compact', 'marathon': 'M1', 'repetition': 1},
                                    tmp_path / 'episode', server)
    assert result.get('error') is None
    assert calls == [None, 'fake-session']
    assert len(result['after_each']) == 2
    assert result['final']['py_query']['passed'] is False
    assert result['final']['py_range']['passed'] is False
    assert (tmp_path / 'episode/isolation-probe.json').is_file()


def test_grading_does_not_let_workspace_code_write_to_host(tmp_path):
    config = long_tasks.load_config()
    workspace = tmp_path / 'workspace'
    long_tasks.prepare_combined(config, ['py_query'], workspace)
    marker = tmp_path / 'escape-marker'
    (workspace / 'sitecustomize.py').write_text('from pathlib import Path\nPath('
                      + repr(str(marker)) + ').write_text("escaped")\n')
    outcome = long_tasks.grade_objective(config, 'py_query', workspace, tmp_path / 'grade', 30)
    assert not marker.exists()
    assert outcome['passed'] is not True


def test_unreleased_and_phase_one_objectives_do_not_get_private_pass(tmp_path):
    config = long_tasks.load_config()
    workspace = tmp_path / 'workspace'
    long_tasks.prepare_combined(config, ['py_query', 'cont_quote:1', 'cont_quote:2'], workspace)
    result = long_tasks.assess_all(config, ['py_query', 'cont_quote:1', 'cont_quote:2'],
                                   workspace, tmp_path / 'checks', float('inf'), released=1)
    assert result['py_query']['passed'] is False
    assert result['cont_quote:1']['status'] == 'not_started'
    assert result['cont_quote:2']['status'] == 'not_started'
    phase1 = long_tasks.grade_objective(config, 'cont_quote:1', workspace, tmp_path / 'phase1', 30)
    assert phase1 == {'passed': None, 'status': 'no_private_phase1_oracle'}


def test_three_repetitions_run_each_arm_on_both_marathons():
    config = {'arms': {'a': {}, 'b': {}, 'c': {}, 'd': {}}, 'marathons': {'M1': [], 'M2': []}, 'repetitions': 3}
    units = long_tasks.schedule(config)
    assert len(units) == 24
    assert len({(u['arm'], u['marathon'], u['repetition']) for u in units}) == 24


def test_only_finished_summaries_count_as_completed(tmp_path):
    database = tmp_path / '.local/share/opencode/opencode.db'
    database.parent.mkdir(parents=True)
    with sqlite3.connect(database) as conn:
        conn.execute('CREATE TABLE part (session_id text, data text)')
        conn.execute('CREATE TABLE message (session_id text, data text)')
        conn.executemany('INSERT INTO part VALUES (?, ?)', [('s', '{"type": "compaction"}')] * 2 + [('other', '{"type": "compaction"}')])
        rows = ['{"mode": "compaction", "summary": true, "finish": "stop"}',
                '{"mode": "compaction", "summary": true, "error": {"name": "x"}}',
                '{"mode": "build", "summary": {"diffs": []}, "finish": "stop"}']
        conn.executemany('INSERT INTO message VALUES (?, ?)', [('s', row) for row in rows])
    assert long_tasks.count_compactions(tmp_path, ['s']) == {'requested': 2, 'completed': 1}
