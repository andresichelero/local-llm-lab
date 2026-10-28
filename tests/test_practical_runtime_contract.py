import pytest

from benchmark import practical_runtime_v2 as runtime


def test_new_campaign_accepts_daily_runtime_contract_without_changing_legacy(monkeypatch):
    monkeypatch.setattr(runtime, '_ACTIVE_RUNTIME_CONTRACT', None, raising=False)
    old = runtime.resolve_server({}, runtime.LAB)[1]
    runtime.configure_runtime_contract({'opencode': '1.20.0', 'llama_revision': 'a' * 40})
    assert runtime.resolve_server({}, runtime.LAB)[1] == 'aaaaaaa'
    custom = {'runtime': {'server': '/tmp/llama-server', 'version_prefix': 'bbbbbbb', 'sha256': 'c' * 64}}
    assert runtime.resolve_server(custom, runtime.LAB)[1] == 'bbbbbbb'
    runtime.configure_runtime_contract(None)
    assert runtime.resolve_server({}, runtime.LAB)[1] == old


@pytest.mark.parametrize('value', [{}, {'opencode': '1.20.0', 'llama_revision': 'latest'}])
def test_invalid_daily_contract_rejected(value):
    with pytest.raises(ValueError, match='runtime contract'):
        runtime.configure_runtime_contract(value)


def test_model_calls_include_title_and_compaction_as_separate_diagnostics(tmp_path):
    import json
    broker = tmp_path / 'broker'
    broker.mkdir()
    events = []
    for index, system in enumerate(('You are a title generator.',
                                    'You are a context summarization agent.', 'You are OpenCode, a coding agent.')):
        name = f'request-{index}.bin'
        (broker / name).write_text(json.dumps({'messages': [{'role': 'system', 'content': system}]}))
        events.append({'method': 'POST', 'files': {'client_request': {'name': name}},
                       'upstream_started_utc': '2026-10-23T00:00:00Z'})
    events.append({'method': 'POST', 'files': {}})
    (broker / 'transcript.jsonl').write_text('\n'.join(json.dumps(e) for e in events))
    assert runtime.model_call_breakdown(tmp_path) == {'main': 1, 'title': 1, 'compaction': 1, 'unknown': 0}
    assert runtime.model_call_evidence(tmp_path)['model_call_request_breakdown'] == {
        'main': 1, 'title': 1, 'compaction': 1, 'unknown': 1}


def test_model_call_evidence_separates_forwarded_calls_from_post_attempts(tmp_path):
    import json
    broker = tmp_path / 'broker'
    broker.mkdir()
    events = []
    requests = (
        ('You are OpenCode, a coding agent.', True),
        ('You are OpenCode, a coding agent.', False),
        ('You are a title generator.', True),
    )
    for index, (system, forwarded) in enumerate(requests):
        name = f'request-{index}.bin'
        (broker / name).write_text(json.dumps({'messages': [{'role': 'system', 'content': system}]}))
        events.append({'method': 'POST', 'files': {'client_request': {'name': name}},
                       'upstream_started_utc': '2026-10-23T00:00:00Z' if forwarded else None})
    (broker / 'transcript.jsonl').write_text('\n'.join(json.dumps(e) for e in events))

    assert runtime.model_call_evidence(tmp_path) == {
        'model_calls': 2,
        'model_call_breakdown': {'main': 1, 'title': 1, 'compaction': 0, 'unknown': 0},
        'model_call_requests': 3,
        'model_call_request_breakdown': {'main': 2, 'title': 1, 'compaction': 0, 'unknown': 0},
    }


def test_recovery_only_clears_no_progress_within_its_phase_and_before_later_events():
    import json

    def line(value):
        return json.dumps(value).encode() + b'\n'

    no_progress = {'type': 'tool_use', 'part': {
        'tool': 'bash', 'callID': 'phase1',
        'state': {'status': 'error', 'error': 'LAB_POLICY_STOP:model_no_progress'}}}
    phase1_recovery = {'_practical_driver': 'recovery', 'phase': 1,
                       'exit_code': 0, 'stop_reason': None}
    phase2_no_progress = {'type': 'tool_use', 'part': {
        'tool': 'bash', 'callID': 'phase2',
        'state': {'status': 'error', 'error': 'LAB_POLICY_STOP:model_no_progress'}}}
    later_phase = b''.join((line(no_progress), line(phase1_recovery),
                            line({'_practical_driver': 'phase', 'phase': 1}),
                            line(phase2_no_progress)))
    guard, recoveries = runtime._tool_guard_from_output('M1', later_phase, 'operational')
    assert [event['phase'] for event in recoveries] == [1]
    assert guard.reason == 'model_no_progress'

    recovered_in_phase = b''.join((line(no_progress), line(phase1_recovery)))
    guard, _ = runtime._tool_guard_from_output('M1', recovered_in_phase, 'operational')
    assert guard.reason is None


def test_host_watchdog_timeout_without_infrastructure_error_is_budget_exhaustion():
    from types import SimpleNamespace

    run = SimpleNamespace(infrastructure_error=None, timed_out=True)
    assert runtime._failure_for(run, []) == 'budget_exhausted'


def test_runtime_protocol_is_independent_m1_v9():
    from benchmark import practical_campaign_v2 as campaign
    from benchmark import practical_review_replay as replay
    previous = campaign.PROTOCOL, runtime.PROTOCOL
    try:
        expected, _ = replay.build_replay(
            {'fixture':{}}, runtime_expectations={'opencode':'1.19.4','llama_revision':'a'*40})
        assert expected['protocol_id'] == 'practical-agent-limits-skills-v9-m1-independent'
        assert runtime.PROTOCOL == expected['protocol_id']
    finally:
        campaign.PROTOCOL, runtime.PROTOCOL = previous


def test_recovery_evidence_is_parsed_as_trusted_driver_event():
    native, driver = runtime._events(b'{"_practical_driver":"recovery","exit_code":0}\n')
    assert native == [] and driver[0]['_practical_driver'] == 'recovery'
