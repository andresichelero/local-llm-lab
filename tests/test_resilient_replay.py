"""A model-local block cannot starve the remaining frozen models."""
from types import SimpleNamespace

from benchmark import practical_campaign_v2 as campaign


def test_probe_and_episode_blocks_still_attempt_all_five_models(tmp_path, monkeypatch):
    models = {name:{} for name in ('probe-bad','episode-bad','good-c','good-d','good-e')}
    schedule = campaign.baseline_schedule(tuple(models), tasks=('M1',))
    manifest = {'immutable':{}, 'stage_status':{}}
    rows, probes, calls = [], [], []
    monkeypatch.setattr(campaign, '_save_manifest', lambda *a, **k: None)
    monkeypatch.setattr(campaign, '_load_task_quarantines', lambda *a: {})

    def probe(model, *a, **k):
        probes.append(model)
        return model != 'probe-bad'

    def episode(item, **kwargs):
        calls.append((item['model'],item['repetition']))
        if item['model'] == 'episode-bad':
            rows.append({**item,'status':'blocked','failure':'infrastructure'})
            raise campaign.CampaignBlocked('fixture transport unavailable')
        rows.append({**item,'status':'complete','failure':'passed'})

    monkeypatch.setattr(campaign, '_profile_probe', probe)
    monkeypatch.setattr(campaign, '_run_episode', episode)
    kwargs = dict(output=tmp_path, rows=rows, manifest=manifest,
        runtime=SimpleNamespace(), models=models, lab=tmp_path, tasks_module=None,
        continue_model_blocks=True)
    assert campaign._run_stage('baseline', schedule, **kwargs) is False
    assert set(probes) == set(models)
    assert len([r for r in rows if r['status']=='complete']) == 9
    assert len([c for c in calls if c[0]=='episode-bad']) == 1
    assert set(manifest['model_blocks']) == {'probe-bad','episode-bad'}
    complete_calls = [c for c in calls if c[0].startswith('good')]
    assert campaign._run_stage('baseline', schedule, **kwargs) is False
    assert [c for c in calls if c[0].startswith('good')] == complete_calls
    assert len([c for c in calls if c[0]=='episode-bad']) == 1


def test_shared_unsafe_server_is_recorded_for_all_without_loading(tmp_path, monkeypatch):
    models = {name:{} for name in ('a','b','c','d','e')}
    schedule = campaign.baseline_schedule(tuple(models), tasks=('M1',))
    manifest = {'immutable':{}, 'stage_status':{}}
    checks = []
    def unsafe():
        checks.append(True)
        raise campaign.CampaignBlocked('a model server remains active')
    monkeypatch.setattr(campaign, '_save_manifest', lambda *a, **k: None)
    monkeypatch.setattr(campaign, '_load_task_quarantines', lambda *a: {})
    monkeypatch.setattr(campaign, '_profile_probe', lambda *a, **k: (_ for _ in ()).throw(
        AssertionError('unsafe probe started')))
    assert campaign._run_stage('baseline', schedule, output=tmp_path, rows=[],
        manifest=manifest, runtime=SimpleNamespace(check_model_admission=unsafe),
        models=models, lab=tmp_path, tasks_module=None, continue_model_blocks=True) is False
    assert len(checks) == 5
    assert set(manifest['model_blocks']) == set(models)
