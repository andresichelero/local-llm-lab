import json

import pytest

from benchmark import practical_campaign_v2 as campaign
from benchmark import practical_repair as repair
from test_practical_repair import source_manifest


def test_changed_baseline_does_not_inherit_historical_finalists():
    source, _ = source_manifest()
    rows = repair.changed_schedule(source, 'baseline')
    assert len(rows) == 75
    assert {r['task'] for r in rows} == {'B2', 'C2', 'M1', 'M2', 'D2'}
    assert {r['model'] for r in rows} == set(source['immutable']['models'])


def test_d2_and_h2_schedule_follow_new_finalists_and_actual_profiles():
    source, _ = source_manifest()
    finalists = ['d', 'e']
    profiles = {m: {'id': 'context_32k', 'context_tokens': 32768, 'cache_prompt': False}
                for m in finalists}
    for stage, task in [('cache_on', 'D2'), ('context_32k', 'D2'), ('holdout', 'H2')]:
        rows = repair.changed_schedule(source, stage, finalists=finalists, profiles=profiles)
        assert len(rows) == 6
        assert {r['model'] for r in rows} == set(finalists)
        assert {r['task'] for r in rows} == {task}
        assert {r['generation_seed'] for r in rows} == {101, 202, 303}
        if stage != 'cache_on':
            assert all(r['profile_config']['cache_prompt'] is False for r in rows)


def test_daily_contract_requires_complete_local_day_and_exact_commit(tmp_path):
    marker = tmp_path / 'state/runtime-updates/daily-2026-10-22.json'
    marker.parent.mkdir(parents=True)
    value = {'date': '2026-10-22', 'status': 'complete',
             'applications': {'opencode': '1.20.0'}, 'llama_cpp': {'commit': 'a' * 40}}
    marker.write_text(json.dumps(value))
    assert repair.daily_contract(tmp_path, day='2026-10-22') == {
        'opencode': '1.20.0', 'llama_revision': 'a' * 40}
    value['status'] = 'failed'
    marker.write_text(json.dumps(value))
    with pytest.raises(ValueError, match='daily'):
        repair.daily_contract(tmp_path, day='2026-10-22')


def test_recommendation_stays_empty_with_quarantine_even_if_coverage_complete(tmp_path):
    row = campaign._episode('a', 'C2', 1, campaign.BASELINE_PROFILE, stage='baseline', protocol=campaign.PROTOCOL)
    row.update(status='complete', correct=True, autonomous=True)
    manifest = {'status': 'review_required', 'task_quarantines': {'C2': {'active': True}},
                'stage_schedules': {'baseline': [{'identity': list(campaign.episode_key(row))}]},
                'holdout_advice': {'status': 'consistent', 'model': 'a'}}
    campaign._write_recommendation(tmp_path, manifest, [row])
    assert json.loads((tmp_path / 'recommendation.json').read_text())['candidate_model'] is None


def test_shared_infrastructure_stops_without_repeating_episode(tmp_path, monkeypatch):
    from types import SimpleNamespace
    calls = []

    def run_episode(*args, **kwargs):
        calls.append(args)
        return {'failure': 'infrastructure', 'correct': False, 'autonomous': False, 'seconds': 1}

    monkeypatch.setattr(campaign, '_save_record', lambda *a, **k: None)
    adapter = SimpleNamespace(stop_on_infrastructure=True, run_episode=run_episode)
    episode = campaign.baseline_schedule(('a',), tasks=('B1',))[0]
    with pytest.raises(campaign.CampaignBlocked):
        campaign._run_episode(episode, output=tmp_path, rows=[], runtime=adapter,
                              models={'a': {}}, lab=tmp_path, tasks_module=None, manifest={})
    assert len(calls) == 1


@pytest.mark.parametrize('frozen', [False, True])
def test_update_and_cpu_integration_run_before_new_round_but_not_frozen_resume(tmp_path, monkeypatch, frozen):
    from types import SimpleNamespace
    monkeypatch.setattr(repair.runtime, 'LAB', tmp_path / 'lab')
    monkeypatch.setattr(repair.runtime, '_ACTIVE_RUNTIME_CONTRACT', None)
    monkeypatch.setattr(repair, 'daily_contract', lambda lab: {
        'opencode': '1.19.4', 'llama_revision': 'a' * 40})
    calls = []
    monkeypatch.setattr(repair.subprocess, 'run', lambda command, **kw: calls.append(command))
    monkeypatch.setattr(repair, 'run', lambda *a, **kw: {'status': 'complete'})
    output = tmp_path / 'run'
    output.mkdir()
    (output / 'manifest.json').write_text(json.dumps({'runtime_versions': {'fixture': '1'} if frozen else None}))
    args = SimpleNamespace(output=output, source=tmp_path / 'source', wait_for_capacity=False)
    assert repair.execute_prepared_round(args) == 0
    assert len(calls) == (0 if frozen else 2)
    if not frozen:
        assert calls[0][0] == 'bash'
        assert 'tests/test_practical_flows_v2.py' in calls[1]


def test_explicit_review_release_can_resume_after_multiple_reviewed_attempts(tmp_path, monkeypatch):
    from types import SimpleNamespace
    episode = campaign.baseline_schedule(('a',), tasks=('B1',))[0]
    previous = {**episode, 'status': 'review_required', 'attempts': [
        {'failure': 'task_review', 'seconds': 1, 'tool_errors': 6, 'model_calls': 6}] * 2}
    calls = []

    def run_episode(*args, **kwargs):
        calls.append(args)
        return {'failure': 'passed', 'correct': True, 'autonomous': True, 'seconds': 1}

    monkeypatch.setattr(campaign, '_save_record', lambda *a, **k: None)
    result = campaign._run_episode(episode, output=tmp_path, rows=[previous],
        runtime=SimpleNamespace(stop_on_infrastructure=True, run_episode=run_episode),
        models={'a': {}}, lab=tmp_path, tasks_module=None, manifest={})
    assert len(calls) == 1 and result['status'] == 'complete'
    assert result['attempt_count'] == 3
    assert result.get('infrastructure_retried') is not True
