from benchmark import practical_campaign_v2 as campaign
from benchmark import practical_review_replay as replay
from benchmark import practical_tasks_v2 as tasks
from benchmark.practical_manual import manual_evidence, selected_skills


def test_coverage_requires_exact_complete_schedule_not_just_existing_rows():
    schedule=campaign.baseline_schedule(('m',), tasks=('B2',))
    manifest={'stage_schedules':{'baseline':[{'identity':list(campaign.episode_key(r))} for r in schedule]}}
    rows=[{**r,'status':'complete'} for r in schedule]
    assert campaign._all_scheduled_complete(manifest,rows)
    assert not campaign._all_scheduled_complete(manifest,rows[:1])
    assert not campaign._all_scheduled_complete(manifest,rows + [{**rows[0],'model':'unexpected'}])


def test_model_error_threshold_is_scoped_to_episode_not_global_registry(tmp_path, monkeypatch):
    monkeypatch.setattr(campaign,'_save_record',lambda out,record,rows,**kw: rows.append(record))
    class Runtime:
        stop_on_infrastructure=True
        def run_episode(self,*a,**k):
            return {'failure':'model_tool_error','review_required':True,'model_tool_errors':6,
                    'tool_review':{'reason':'model_tool_error_threshold'}}
    row=campaign._run_episode(campaign.baseline_schedule(('m',),tasks=('M1',))[0],
        output=tmp_path,rows=[],runtime=Runtime(),models={'m':{}},lab=tmp_path,
        tasks_module=tasks,manifest={})
    assert row['status']=='complete'
    assert row['failure']=='model_tool_error'
    assert not (tmp_path/'results/task-review-registry.json').exists()


def test_manual_is_model_neutral_focused_and_hashed():
    for task in tasks.ALL_TASKS:
        assert len(selected_skills(task))<=3
        assert 'CORE.md' in manual_evidence(task)


def test_replay_catalogue_adapter_probes_all_five_frozen_models():
    adapter=replay.make_adapter(replay.frozen_models())
    assert set(adapter.models)==set(replay.frozen_models())
    assert adapter.stop_on_infrastructure


def test_probe_receives_frozen_catalogue_not_legacy_defaults(monkeypatch):
    from benchmark import practical_runtime_v2 as runtime
    models=replay.frozen_models()
    seen=[]
    monkeypatch.setattr(runtime,'probe_profile',lambda *a,**k: seen.append(k['models']) or {'passed':True})
    assert replay.make_adapter(models).probe_profile('bonsai-2-27b', campaign.BASELINE_PROFILE)['passed']
    assert seen==[models]


def test_cpu_validation_is_invalidated_by_source_changes(tmp_path, monkeypatch):
    import json
    path=tmp_path/'cpu.json'
    monkeypatch.setattr(replay,'CPU_REPORT',path)
    expected={'immutable':{'source_hashes':{'code.py':'original'}},'immutable_sha256':'contract-a'}
    assert not replay.cpu_evidence_current(expected)
    path.write_text(json.dumps({'passed':True,'source_digest':campaign._hash_value(expected['immutable']['source_hashes']), 'immutable_sha256':'contract-a'}))
    assert replay.cpu_evidence_current(expected)
    expected['immutable']['source_hashes']['code.py']='changed'
    assert not replay.cpu_evidence_current(expected)


def test_calibration_variants_have_distinct_contracts_and_do_not_expose_answers():
    base, _=replay.build_replay({'m':{}}, runtime_expectations={'opencode':'1.19.4','llama_revision':'a'*40})
    core, _=replay.build_replay({'m':{}},runtime_expectations={'opencode':'1.19.4','llama_revision':'a'*40},with_skills=False,budget_multiplier=2)
    assert core['protocol_id'] != base['protocol_id']
    assert core['immutable']['policies']['M1']['main']==90
    assert core['immutable']['policies']['M1']['compaction']==3
    assert set(core['immutable']['manual_hashes']['M1'])=={'CORE.md'}
