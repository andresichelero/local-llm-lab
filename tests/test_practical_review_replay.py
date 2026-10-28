import pytest

from benchmark import practical_review_replay as replay


EXPECTATIONS = {'opencode': '1.19.4', 'llama_revision': 'a' * 40}


def _attempt(number: int, failure: str):
    return {'attempt': number, 'failure': failure, 'seconds': 5.0, 'tool_errors': 0,
            'expected_tool_errors': None, 'avoidable_tool_errors': None, 'model_calls': 2}


def _blocked_infrastructure():
    return {'status': 'blocked', 'failure': 'infrastructure', 'correct': False,
            'autonomous': False, 'scoring_eligible': False,
            'attempts': [_attempt(1, 'infrastructure'), _attempt(2, 'infrastructure')],
            'block_reason': 'infrastructure retry exhausted for this episode'}


def _fixture_rows(schedule):
    rows = []
    for episode in schedule:
        key = (episode['task'], episode['repetition'])
        row = dict(episode)
        if key == ('C2', 1):
            # A completed model-stop failure: retained, never re-executed.
            row.update({'status': 'complete', 'failure': 'model_tool_error',
                        'correct': False, 'autonomous': False, 'scoring_eligible': True,
                        'review_required': False, 'seconds': 9.0,
                        'tool_review': {'reason': 'model_tool_error_threshold'}})
        elif key in {('M1', 1), ('M1', 2), ('M1', 3), ('C2', 2), ('B2', 3)}:
            row.update(_blocked_infrastructure())
        else:
            row.update({'status': 'complete', 'failure': 'passed', 'correct': True,
                        'autonomous': True, 'seconds': 1.0})
        rows.append(row)
    return rows


class _FakeAdapter:
    stop_on_infrastructure = True

    def __init__(self, calls, *, validation=None, backup_seen=None):
        self.models = {'fixture': {}}
        self.calls = calls
        self.backup_seen = backup_seen
        self.validation = validation or {'passed': True, 'checks': {},
                                         'runtime_versions': {'python': '3.12-fixture'},
                                         'failures': []}

    def validate_environment(self, *, lab=None, **kwargs):
        return dict(self.validation)

    def probe_profile(self, model, profile, *, lab=None, output=None, **kwargs):
        return {'passed': True, 'status': 'complete'}

    def run_episode(self, model, task, profile, repetition, output, models, *, lab=None):
        self.calls.append((task, repetition))
        if self.backup_seen is not None:
            self.backup_seen.append((output.parents[1] / 'authorization-in-use.json').is_file())
        return {'failure': 'passed', 'correct': True, 'autonomous': True,
                'seconds': 2.0, 'model_calls': 3}


def _review_fixture(tmp_path, monkeypatch, *, validation=None, manifest_overrides=None):
    from types import SimpleNamespace
    from benchmark import practical_campaign_v2 as campaign

    protocol = campaign.PROTOCOL
    schedule = campaign.baseline_schedule(('fixture',), tasks=('B2', 'C2', 'M1'),
                                          protocol=protocol)
    rows = _fixture_rows(schedule)
    immutable = {
        'models': {'fixture': {}}, 'runtime_expectations': EXPECTATIONS,
        'schedule': {'maximum_episodes': len(schedule), 'review_replay_episodes': len(schedule),
                     'review_replay_tasks': ['B2', 'C2', 'M1']},
        'review_replay': {'tasks': ['B2', 'C2', 'M1'], 'episodes': len(schedule)},
    }
    manifest = {
        'protocol_id': protocol, 'immutable_sha256': 'fixture-sha', 'immutable': immutable,
        'status': 'blocked', 'error': 'profile probe failed: fixture',
        'stage_status': {'baseline': 'blocked'},
        'stage_schedules': {'baseline': [
            {'identity': list(campaign.episode_key(e)), 'profile_config': e['profile_config']}
            for e in schedule]},
    }
    if manifest_overrides:
        manifest.update(manifest_overrides)
    expected = {'protocol_id': protocol, 'immutable_sha256': manifest['immutable_sha256'],
                'immutable': immutable}
    calls: list = []
    backup_seen: list = []
    adapter = _FakeAdapter(calls, validation=validation, backup_seen=backup_seen)
    monkeypatch.setattr(replay, 'build_replay', lambda *a, **k: (expected, schedule))
    monkeypatch.setattr(replay, 'make_adapter', lambda *a, **k: adapter)
    monkeypatch.setattr(replay.runtime, 'LAB', tmp_path / 'lab')
    monkeypatch.setattr(campaign, '_load_task_quarantines',
                        lambda lab, m: m.setdefault(
                            'task_quarantines', {'M1': {'reason': 'unattributed_tool_error',
                                                        'active': True}}))
    campaign.atomic_write_json(tmp_path / 'manifest.json', manifest)
    campaign.atomic_write_json(tmp_path / 'records.json', rows)
    return SimpleNamespace(schedule=schedule, rows=rows, adapter=adapter,
                           manifest_path=tmp_path / 'manifest.json',
                           records_path=tmp_path / 'records.json', calls=calls)


def _audit_events(tmp_path):
    import json
    lines = (tmp_path / 'authorization-audit.jsonl').read_text(encoding='utf-8').splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def test_recovery_retries_only_missing_and_reviewed_not_completed_model_failures(tmp_path):
    import json
    from benchmark import practical_campaign_v2 as campaign
    models = {'fixture': {}}
    full = campaign.baseline_schedule(tuple(models), tasks=replay.REVIEW_TASKS, protocol='old')
    (tmp_path/'manifest.json').write_text(json.dumps({'protocol_id':'old', 'status':'review_required',
        'immutable':{'models':models}, 'stage_schedules':{'baseline':[
            {'identity':list(campaign.episode_key(e))} for e in full]}}))
    rows = [{**e, 'status':'complete', 'failure':'model_no_progress'} for e in full]
    rows[0]['status'] = 'review_required'
    rows[1]['status'] = 'skipped_review'
    absent = rows.pop(2)
    (tmp_path/'records.json').write_text(json.dumps(rows))
    expected, selected = replay.build_replay(models,
        runtime_expectations={'opencode':'1.19.4','llama_revision':'a'*40}, recovery_from=tmp_path,
        task_ids=replay.REVIEW_TASKS)
    assert len(selected) == 3
    assert [campaign.episode_key(e)[1:] for e in selected] == sorted(campaign.episode_key(e)[1:] for e in selected)
    assert {campaign.episode_key(e)[1:] for e in selected} == {
        campaign.episode_key(e)[1:] for e in (rows[0], rows[1], absent)}
    assert expected['immutable']['recovery']['previous_complete'] == 6
    assert expected['protocol_id'].endswith('-recovery')
    assert expected['immutable']['schedule']['maximum_episodes'] == 3
    foreign = {**rows[0], 'protocol':'foreign', 'status':'complete'}
    (tmp_path/'records.json').write_text(json.dumps(rows + [foreign]))
    import pytest
    with pytest.raises(ValueError, match='foreign episode'):
        replay.build_replay(models, runtime_expectations={
            'opencode':'1.19.4','llama_revision':'a'*40}, recovery_from=tmp_path,
            task_ids=replay.REVIEW_TASKS)


def test_recovery_refuses_running_source(tmp_path):
    import json
    import pytest
    (tmp_path/'manifest.json').write_text(json.dumps({'status':'running'}))
    with pytest.raises(ValueError, match='stopped'):
        replay.select_recovery(tmp_path, [], {})


def test_review_replay_schedules_only_flagged_tasks_for_all_models_and_repetitions():
    models = {"a": {}, "b": {}}
    expected, schedule = replay.build_replay(models, runtime_expectations={
        "opencode": "1.2.3", "llama_revision": "a" * 40,
    },task_ids=replay.REVIEW_TASKS)
    assert expected["protocol_id"].startswith('practical-agent-limits-skills-v9-taskset-')
    assert expected["immutable"]["schedule"]["review_replay_episodes"] == 18
    assert {row["task"] for row in schedule} == {"B2", "C2", "M1"}
    assert len(schedule) == 18
    assert all(row["protocol"] == expected['protocol_id'] for row in schedule)


def test_review_replay_uses_frozen_corrected_v3_model_matrix():
    assert set(replay.frozen_models()) == {
        "bonsai-2-27b", "bonsai-2-9b", "gemma-4-12b", "ornith-1.0-9b", "qwen3.5-9b",
    }


def test_preparation_keeps_engineering_and_current_gpu_capacity_separate(tmp_path, monkeypatch):
    from types import SimpleNamespace
    expected = {'protocol_id':replay.PROTOCOL, 'immutable':{
        'runtime_expectations':{}, 'models':{}, 'review_replay':{'tasks':[]}}}
    monkeypatch.setattr(replay, 'build_replay', lambda **kw: (expected, []))
    monkeypatch.setattr(replay, 'make_adapter', lambda *a: SimpleNamespace(
        models={}, validate_environment=lambda: {'passed':True}))
    monkeypatch.setattr(replay.runtime, 'configure_runtime_contract', lambda *a: None)
    monkeypatch.setattr(replay.runtime, '_model_start_preflight',
                        lambda *a: (_ for _ in ()).throw(RuntimeError('GPU busy')))
    monkeypatch.setattr(replay.campaign, '_load_task_quarantines', lambda *a: None)
    monkeypatch.setattr(replay.campaign, '_load_or_create_manifest', lambda *a: {})
    monkeypatch.setattr(replay.campaign, '_save_manifest', lambda *a, **kw: None)
    monkeypatch.setattr(replay, 'cpu_evidence_current', lambda *a: True)
    result = replay.prepare(tmp_path)
    assert result['engineering_ready'] and not result['execution_capacity_ready']
    assert result['capacity_pending'] and not result['comparison_ready']
    assert result['inference'] is False


# --- Task 3: official retry under explicit authorization ----------------------------


def test_blocked_manifest_refuses_without_explicit_authorization(tmp_path, monkeypatch):
    fixture = _review_fixture(tmp_path, monkeypatch)
    manifest_before = fixture.manifest_path.read_bytes()
    records_before = fixture.records_path.read_bytes()

    result = replay.run(tmp_path)

    assert result['status'] == 'blocked'
    assert result['error'] == 'profile probe failed: fixture'
    assert fixture.calls == []                       # nothing was executed
    assert fixture.manifest_path.read_bytes() == manifest_before
    assert fixture.records_path.read_bytes() == records_before
    events = _audit_events(tmp_path)
    assert events[0]['event'] == 'opened' and events[0]['retry_blocked'] is False
    assert any(event['event'] == 'refused' for event in events)
    assert events[-1]['event'] == 'closed'
    assert not (tmp_path / 'authorization-in-use.json').exists()


def test_authorized_retry_runs_only_blocked_episodes_and_preserves_attempts(tmp_path, monkeypatch):
    from benchmark import practical_campaign_v2 as campaign
    fixture = _review_fixture(tmp_path, monkeypatch)

    result = replay.run(tmp_path, retry_blocked=True)

    # Only the two infrastructure-blocked episodes ran; completed, model-stop
    # and quarantined (M1) entries are never repeated.
    assert result['status'] == 'review_required'
    assert sorted(fixture.calls) == [('B2', 3), ('C2', 2)]
    assert all(fixture.adapter.backup_seen)          # in-use marker during execution
    assert (tmp_path / 'authorization-in-use.json').exists() is False
    records = campaign.load_records(tmp_path)
    retried = next(row for row in records if (row['task'], row['repetition']) == ('C2', 2))
    assert retried['status'] == 'complete' and retried['correct'] is True
    assert [attempt['attempt'] for attempt in retried['attempts']] == [1, 2, 3]
    assert retried['infrastructure_retried'] is True
    retained_model_stop = next(row for row in records
                               if (row['task'], row['repetition']) == ('C2', 1))
    assert retained_model_stop['status'] == 'complete'
    assert retained_model_stop['failure'] == 'model_tool_error'
    m1_rows = [row for row in records if row['task'] == 'M1']
    assert all(row['status'] == 'skipped_review' and row['failure'] == 'task_review'
               for row in m1_rows)

    import json
    manifest = json.loads(fixture.manifest_path.read_text())
    assert manifest['error'] is None
    assert manifest['operator_retry_blocked'] is True
    assert [item['error'] for item in manifest['resolved_errors']] == ['profile probe failed: fixture']
    assert manifest['status'] == 'review_required'
    events = _audit_events(tmp_path)
    assert events[0]['event'] == 'opened' and events[0]['retry_blocked'] is True
    assert events[-1]['event'] == 'closed' and events[-1]['status'] == 'review_required'
    assert (tmp_path / 'authorization-audit.jsonl').read_text(encoding='utf-8').count('\n') >= 2


def test_environment_failure_now_records_blocked_state_and_audit_closes(tmp_path, monkeypatch):
    _review_fixture(
        tmp_path, monkeypatch,
        manifest_overrides={'status': 'review_required', 'error': 'profile probe failed: stale'},
        validation={'passed': False, 'reason': 'variant mismatch'})

    result = replay.run(tmp_path)

    assert result['status'] == 'blocked'
    assert 'review replay environment invalid' in result['error']
    events = _audit_events(tmp_path)
    assert events[0]['event'] == 'opened' and events[0]['retry_blocked'] is False
    assert events[-1]['event'] == 'closed'


def test_run_refuses_when_another_owner_holds_the_replay_lock(tmp_path, monkeypatch):
    import fcntl
    from benchmark import practical_campaign_v2 as campaign
    fixture = _review_fixture(tmp_path, monkeypatch)
    manifest_before = fixture.manifest_path.read_bytes()
    records_before = fixture.records_path.read_bytes()

    with (tmp_path / 'review-replay.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(campaign.CampaignBlocked, match='already running'):
            replay.run(tmp_path)

    assert fixture.manifest_path.read_bytes() == manifest_before
    assert fixture.records_path.read_bytes() == records_before
    assert (tmp_path / 'authorization-audit.jsonl').exists() is False


def test_execute_prepared_refuses_when_another_round_owns_the_laboratory(tmp_path, monkeypatch):
    import fcntl
    from benchmark import practical_campaign_v2 as campaign
    monkeypatch.setattr(replay.runtime, 'LAB', tmp_path)
    (tmp_path / 'state').mkdir()
    with (tmp_path / 'state' / 'practical-round.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(campaign.CampaignBlocked, match='another practical round owns the laboratory'):
            replay.execute_prepared(tmp_path / 'out')


def test_execute_prepared_expires_when_capacity_stays_unavailable(tmp_path, monkeypatch):
    fixture = _review_fixture(tmp_path, monkeypatch)
    out = tmp_path / 'out'
    monkeypatch.setattr(replay, 'prepare',
                        lambda *a, **k: {'engineering_ready': True, 'execution_capacity_ready': True})
    monkeypatch.setattr(replay, '_active_llama_servers', lambda: [])
    monkeypatch.setattr(replay.runtime, 'capacity_guard', lambda probe: False)
    monkeypatch.setattr(replay, 'run',
                        lambda *a, **k: pytest.fail('run must not start while capacity is unavailable'))

    assert replay.execute_prepared(out) == 2

    import json
    report = json.loads((out / 'capacity-wait.json').read_text())
    assert report['ready'] is False and report['outcome'] == 'probe_never_ready'
    for field in ('started_at_utc', 'finished_at_utc', 'waited_seconds', 'poll_seconds',
                  'stable_samples_required', 'note'):
        assert field in report
    assert fixture.calls == []


def test_execute_prepared_waits_for_stable_capacity_then_runs(tmp_path, monkeypatch):
    out = tmp_path / 'out'
    monkeypatch.setattr(replay.runtime, 'LAB', tmp_path)
    monkeypatch.setattr(replay, 'prepare',
                        lambda *a, **k: {'engineering_ready': True, 'execution_capacity_ready': True})
    monkeypatch.setattr(replay, '_active_llama_servers', lambda: [])
    probes: list = []

    def fake_guard(_probe) -> bool:
        probes.append(_probe)
        return True

    monkeypatch.setattr(replay.runtime, 'capacity_guard', fake_guard)
    captured = {}

    def fake_run(output, *, mode, with_skills, budget_multiplier, recovery_from, retry_blocked,
                 _admission_held=False):
        assert _admission_held is True
        captured.update(retry_blocked=retry_blocked, output=str(output))
        return {'status': 'complete'}

    monkeypatch.setattr(replay, 'run', fake_run)

    assert replay.execute_prepared(out, retry_blocked=True) == 0
    assert probes and captured['retry_blocked'] is True
    import json
    report = json.loads((out / 'capacity-wait.json').read_text())
    assert report['ready'] is True and report['outcome'] == 'ready'


def test_cli_retry_blocked_flag_reaches_execute_prepared(monkeypatch, tmp_path):
    import sys
    monkeypatch.setattr(replay, 'build_replay',
                        lambda *a, **k: ({'protocol_id': 'fixture-proto'}, []))
    captured = {}

    def fake_execute(output, *positional, **kwargs):
        captured['retry_blocked'] = kwargs.get('retry_blocked')
        return 0

    monkeypatch.setattr(replay, 'execute_prepared', fake_execute)
    monkeypatch.setattr(sys, 'argv',
                        ['prog', '--execute', '--output', str(tmp_path / 'out'), '--retry-blocked'])
    assert replay.main() == 0
    assert captured['retry_blocked'] is True

    monkeypatch.setattr(sys, 'argv', ['prog', '--execute', '--output', str(tmp_path / 'out')])
    assert replay.main() == 0
    assert captured['retry_blocked'] is False
