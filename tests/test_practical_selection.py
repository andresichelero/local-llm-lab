import io
import json
import zipfile
from types import SimpleNamespace

import pytest

from benchmark.practical_selection import extract_snapshot, rank_models, completed_keys, mcp_workflow, phase_complete, load_records


def test_rank_prefers_completion_then_all_elapsed_time():
    rows = [dict(model='fast', task='bugfix', correct=True, autonomous=True, seconds=10, vram_mib=7000),
            dict(model='fast', task='feature', correct=False, autonomous=False, seconds=300, vram_mib=7000),
            dict(model='steady', task='bugfix', correct=True, autonomous=True, seconds=40, vram_mib=7100),
            dict(model='steady', task='feature', correct=False, autonomous=False, seconds=40, vram_mib=7100),
            dict(model='bad', task='bugfix', correct=False, autonomous=False, seconds=1, vram_mib=100)]
    ranked = rank_models(rows)
    assert [r['model'] for r in ranked] == ['steady', 'fast', 'bad']
    assert ranked[0]['total_seconds'] == 80
    assert ranked[0]['median_success_seconds'] == 40


def test_resume_does_not_repeat_finished_or_score_infra_failure():
    rows = [dict(model='a', task='bugfix', failure='wrong_result'),
            dict(model='b', task='bugfix', failure='infrastructure')]
    assert completed_keys(rows) == {('a', 'bugfix')}
    assert rank_models(rows) == []


def test_archive_rejects_path_escape(tmp_path):
    data = io.BytesIO()
    with zipfile.ZipFile(data, 'w') as archive:
        archive.writestr('../escape.py', 'pass')
    with pytest.raises(ValueError):
        extract_snapshot(data.getvalue(), tmp_path)
    assert not (tmp_path.parent / 'escape.py').exists()


def test_archive_supports_arbitrary_test_names(tmp_path):
    data = io.BytesIO()
    with zipfile.ZipFile(data, 'w') as archive:
        archive.writestr('tests/test_different_name.py', 'pass')
    extract_snapshot(data.getvalue(), tmp_path)
    assert (tmp_path / 'tests/test_different_name.py').is_file()


def test_completed_records_are_json_serializable():
    assert json.loads(json.dumps(list(completed_keys([])))) == []


def test_mcp_accepts_mixed_page_sizes_and_checks_returned_data(tmp_path):
    events = []
    for cursor, ids, next_cursor in [(None, [101], '1'), ('1', [102, 103], '3'),
                                    ('3', [104, 105], '5'), ('5', [106], None)]:
        events.append({'type': 'tool_use', 'part': {'tool': 'lab_list_issues', 'state': {
            'status': 'completed', 'input': {'cursor': cursor},
            'output': json.dumps({'items': [{'id': i} for i in ids], 'next_cursor': next_cursor})}}})
    (tmp_path / '.mcp-state.json').write_text(json.dumps({'calls': []}))
    assert mcp_workflow('mcp_report', tmp_path, events)
    assert not mcp_workflow('mcp_report', tmp_path, events[:1])


def test_authored_tests_and_final_are_required_for_code_only():
    info = {'exit_code': 0, 'final_text': 'done', 'authored_tests': {'count': 1, 'passed': True}}
    assert not phase_complete(info, 'bugfix')
    assert phase_complete(info, 'mcp_report')
    info['authored_tests']['count'] = 2
    assert phase_complete(info, 'bugfix')
    info['authored_tests']['passed'] = False
    assert not phase_complete(info, 'bugfix')


def test_resume_recovers_completed_row_before_aggregate_save(tmp_path):
    record = tmp_path / 'runs' / 'one' / 'record.json'
    record.parent.mkdir(parents=True)
    record.write_text(json.dumps({'model': 'a', 'task': 'bugfix', 'failure': 'passed', 'run_dir': str(record.parent)}))
    assert completed_keys(load_records(tmp_path)) == {('a', 'bugfix')}


def test_invalid_agent_artifact_is_not_infrastructure(tmp_path, monkeypatch):
    from benchmark import practical_selection as selection

    monkeypatch.setattr(selection.safe_campaign, '_resource_monitor_start', lambda *a, **kw: (None, {}))
    monkeypatch.setattr(selection.safe_campaign, '_resource_monitor_stop', lambda *a: {})
    result = SimpleNamespace(infrastructure_error=None, cleanup_verified=True, timed_out=False,
                             workspace_outputs={'.practical.json': b'{invalid'}, broker_events=(), output=b'')
    monkeypatch.setattr(selection, 'run_agent', lambda *a, **kw: result)
    row = selection.run_task('test', 'bugfix', tmp_path, {'test': {}})
    assert row['failure'] == 'agent'
