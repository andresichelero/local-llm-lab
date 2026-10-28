"""The next campaign is a new task contract, never a historical recovery."""
import json

import pytest

from benchmark import practical_campaign_v2 as campaign
from benchmark import practical_review_replay as replay
from benchmark import practical_tasks_v2 as tasks


def test_default_campaign_is_fifteen_independent_m1_episodes():
    expected,schedule=replay.build_replay()
    assert expected['protocol_id']=='practical-agent-limits-skills-v9-m1-independent'
    assert len(schedule)==15
    assert len({campaign.episode_key(row) for row in schedule})==15
    assert {row['task'] for row in schedule}=={'M1'}
    assert {row['task_contract_id'] for row in schedule}=={tasks.M1_INDEPENDENT_CONTRACT}
    assert {row['generation_seed'] for row in schedule}=={101,202,303}
    assert expected['immutable']['task_contracts']=={'M1':tasks.M1_INDEPENDENT_CONTRACT}
    assert set(expected['immutable']['task_data'])=={'M1'}
    assert expected['immutable']['policies']['M1']=={
        'main':45,'wall_seconds':480,'title':1,'compaction':3,'metadata':10,
        'mode':'benchmark','version':'limits-skills-v2'}
    assert expected['immutable']['test_reserve_seconds']=={'M1':25}
    assert expected['immutable']['schedule']['maximum_episodes']==15
    assert expected['immutable']['schedule']['maximum_seconds']==7200


def test_new_contract_cannot_recover_old_completed_m1(tmp_path):
    models={'fixture':{}}
    old_schedule=campaign.baseline_schedule(tuple(models),tasks=('M1',),protocol='old')
    (tmp_path/'manifest.json').write_text(json.dumps({'protocol_id':'old','status':'complete',
        'immutable':{'models':models},'stage_schedules':{'baseline':[
            {'identity':list(campaign.episode_key(row))} for row in old_schedule]}}))
    (tmp_path/'records.json').write_text(json.dumps([{**row,'status':'complete'} for row in old_schedule]))
    with pytest.raises(ValueError,match='matching task contracts'):
        replay.build_replay(models,recovery_from=tmp_path)


def test_cpu_evidence_is_tied_to_immutable_task_and_policy(tmp_path,monkeypatch):
    expected,_=replay.build_replay({'fixture':{}})
    path=tmp_path/'cpu.json'
    monkeypatch.setattr(replay,'CPU_REPORT',path)
    source=campaign._hash_value(expected['immutable']['source_hashes'])
    path.write_text(json.dumps({'passed':True,'source_digest':source}))
    assert not replay.cpu_evidence_current(expected)
    path.write_text(json.dumps({'passed':True,'source_digest':source,
                               'immutable_sha256':expected['immutable_sha256']}))
    assert replay.cpu_evidence_current(expected)
    another,_=replay.build_replay({'fixture':{}},task_ids=('M1',),
                                 task_contracts={'M1':tasks.HISTORICAL_CONTRACT})
    assert not replay.cpu_evidence_current(another)


def test_strict_c2_contract_is_a_real_seedable_contract(tmp_path):
    contract='mcp-no-confirmed-replay-v1'
    assert tasks.resolve_task_contract('C2',contract)==contract
    prompt=tasks.seed_task('C2',tmp_path,task_contract_id=contract)
    assert 'exactly one successful write_report' in prompt


def test_prepare_refuses_global_owner_before_environment_checks(tmp_path, monkeypatch):
    import fcntl
    lab = tmp_path / 'lab'
    (lab / 'state').mkdir(parents=True)
    monkeypatch.setattr(replay.runtime, 'LAB', lab)
    monkeypatch.setattr(replay, 'build_replay', lambda **k: pytest.fail('entered preparation'))
    output = tmp_path / 'output'
    with (lab / 'state/practical-round.lock').open('a') as owner:
        fcntl.flock(owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(campaign.CampaignBlocked, match='owns the laboratory'):
            replay.prepare(output)
    assert not output.exists()


def test_prepare_refuses_active_server_without_loading_or_stopping_it(tmp_path, monkeypatch):
    monkeypatch.setattr(replay.runtime, 'LAB', tmp_path / 'lab')
    monkeypatch.setattr(replay, '_active_llama_servers', lambda: ['fixture'])
    monkeypatch.setattr(replay, 'build_replay', lambda **k: pytest.fail('entered preparation'))
    with pytest.raises(campaign.CampaignBlocked, match='server is active'):
        replay.prepare(tmp_path / 'output')
    assert not (tmp_path / 'output').exists()
