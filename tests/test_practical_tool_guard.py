import sys
import time

from benchmark.practical_tool_guard import ToolErrorGuard
from benchmark.practical_driver_v2 import run_guarded


def error(message, ident='x', tool='edit', arguments=None):
    return {'type': 'tool_use', 'part': {'callID': ident, 'tool': tool, 'state': {
        'status': 'error', 'error': message, 'input': arguments or {}}}}


def test_sixth_attributed_error_stops_but_five_do_not_and_ids_are_deduplicated():
    guard = ToolErrorGuard('B1')
    for i in range(5):
        guard.observe(error('No changes to apply: oldString and newString are identical.', str(i)))
    assert guard.reason is None
    guard.observe(error('No changes to apply: oldString and newString are identical.', '4'))
    assert guard.model_errors == 5
    guard.observe(error('No changes to apply: oldString and newString are identical.', '5'))
    assert guard.reason == 'model_tool_error_threshold'


def test_unknown_and_transport_faults_require_review_without_model_blame():
    for message, category in [('Transport error (GET https://opencode.ai)', 'infrastructure'),
                              ('unrecognized failure', 'unattributed')]:
        guard = ToolErrorGuard('C2')
        guard.observe(error(message, tool='webfetch'))
        assert guard.model_errors == 0
        assert guard.reason == category + '_tool_error'


def test_known_edit_and_mcp_argument_rejections_are_attributed_to_model():
    cases = [
        ('B2', 'edit', 'Could not find oldString in the file. It must match exactly, including whitespace, indentation, and line endings.'),
        ('M1', 'edit', 'Could not find oldString in the file. It must match exactly, including whitespace, indentation, and line endings.'),
        ('C2', 'lab_list_issues', 'page_size must be an integer from 1 through 2'),
        ('C2', 'lab_write_report', 'report must contain open_ids as an integer array and total_estimate as an integer'),
    ]
    for task, tool, message in cases:
        guard = ToolErrorGuard(task)
        guard.observe(error(message, tool=tool))
        assert guard.model_errors == 1
        assert guard.unattributed_errors == 0
        assert guard.reason is None


def test_exact_cursor_validation_is_model_error_only_for_lab_list_tools():
    message = 'cursor must be null or a returned numeric cursor'
    cases = [
        ('lab_list_issues', message, 'model'),
        ('lab_write_report', message, 'unattributed'),
        ('lab_list_issues', message + '.', 'unattributed'),
    ]
    for index, (tool, error_message, category) in enumerate(cases):
        guard = ToolErrorGuard('C2')
        guard.observe(error(error_message, str(index), tool, {'cursor': 'not-returned'}))
        assert guard.model_errors == (1 if category == 'model' else 0)
        assert guard.unattributed_errors == (1 if category == 'unattributed' else 0)
        assert guard.evidence[-1]['category'] == category
        assert guard.evidence[-1]['message'] == error_message
        if index == 0:
            assert guard.as_dict()['policy'] == 'task-tool-review-v8'


def test_protected_baseline_write_error_requires_write_tool_and_normalized_test_path():
    message = 'Unknown: FileSystem.writeFile (/workspace/tests/test_existing.test.js)'
    cases = [
        ('write', message, 'model'),
        ('edit', message, 'model'),
        ('bash', message, 'unattributed'),
        ('write', 'Unknown: FileSystem.writeFile (/workspace/tests/../src/test_existing.test.js)',
         'unattributed'),
        ('write', 'Unknown: FileSystem.writeFile /workspace/tests/test_existing.test.js',
         'unattributed'),
    ]
    for index, (tool, error_message, category) in enumerate(cases):
        guard = ToolErrorGuard('B2')
        guard.observe(error(error_message, str(index), tool))
        assert guard.model_errors == (1 if category == 'model' else 0)
        assert guard.unattributed_errors == (1 if category == 'unattributed' else 0)
        assert guard.evidence[-1]['category'] == category
        assert guard.evidence[-1]['message'] == error_message


def test_unavailable_model_tool_is_scoped_to_exact_hallucinated_name():
    exact = "Model tried to call unavailable tool 'invalid'. Available tools: bash, edit, glob, grep, read, write."
    cases = [('write', exact, 'model'),
             ('write', exact.replace("'invalid'", "'mcp'"), 'model'),
             ('write', exact.replace('Available tools:', 'Available tool list:'), 'unattributed'),
             ('webfetch', exact, 'unattributed')]
    for index, (tool, message, category) in enumerate(cases):
        guard = ToolErrorGuard('M1')
        guard.observe(error(message, str(index), tool))
        assert guard.evidence[-1]['category'] == category
        assert guard.model_errors == (1 if category == 'model' else 0)
        assert guard.unattributed_errors == (1 if category == 'unattributed' else 0)


def test_denied_runtime_config_escape_is_model_error_only_for_workspace_read():
    prefix = 'The user has specified a rule which prevents you from using this specific tool call. Here are some of the relevant rules []'
    cases = [('read', '/workspace/../opt/practical/driver.json', 'model'),
             ('read', '/workspace/src/index.js', 'unattributed'),
             ('edit', '/workspace/../opt/practical/driver.json', 'unattributed'),
             ('read', '/etc/passwd', 'unattributed')]
    for index, (tool, path, category) in enumerate(cases):
        guard = ToolErrorGuard('C2')
        guard.observe(error(prefix, str(index), tool, {'filePath':path}))
        assert guard.evidence[-1]['category'] == category
        assert guard.model_errors == (1 if category == 'model' else 0)
        assert guard.unattributed_errors == (1 if category == 'unattributed' else 0)


def test_exact_unavailable_tool_error_is_attributed_only_for_candidate_tool_requests():
    message = "Model tried to call unavailable tool 'invalid'. Available tools: bash, edit, glob, grep, read, write."
    candidates = ('bash', 'edit', 'glob', 'grep', 'read', 'write')
    for index, tool in enumerate(candidates):
        guard = ToolErrorGuard('B1')
        guard.observe(error(message, str(index), tool))
        assert guard.model_errors == 1
        assert guard.unattributed_errors == 0
        assert guard.evidence[-1]['category'] == 'model'

    near_misses = [
        ('invalid', message),
        ('write', "Model tried to call unavailable tool 'invalid'. Available tools: bash, edit, grep, glob, read, write."),
        ('write', message + ' Check the tool list.'),
    ]
    for index, (tool, error_message) in enumerate(near_misses, len(candidates)):
        guard = ToolErrorGuard('B1')
        guard.observe(error(error_message, str(index), tool))
        assert guard.model_errors == 0
        assert guard.unattributed_errors == 1
        assert guard.evidence[-1]['category'] == 'unattributed'


def test_read_permission_escape_is_model_error_only_for_opencode_denial_outside_workspace():
    prefix = 'The user has specified a rule which prevents you from using this specific tool call. Here are some of the relevant rules'
    message = prefix + ': read denied by configured permission rules'
    arguments = {'filePath': '/workspace/../opt/practical/driver.json'}
    cases = [
        ('read', message, arguments, 'model'),
        ('write', message, arguments, 'unattributed'),
        ('read', message, {'filePath': '/workspace/project/../driver.json'}, 'unattributed'),
        ('read', 'Permission denied: read denied by configured permission rules', arguments, 'unattributed'),
    ]
    for index, (tool, error_message, tool_input, category) in enumerate(cases):
        guard = ToolErrorGuard('B2')
        guard.observe(error(error_message, str(index), tool, tool_input))
        assert guard.model_errors == (1 if category == 'model' else 0)
        assert guard.unattributed_errors == (1 if category == 'unattributed' else 0)
        assert guard.evidence[-1]['category'] == category


def test_denied_bash_first_outside_workspace_write_is_model_error():
    denial = ('The user has specified a rule which prevents you from using this specific tool call. '
              'Here are some of the relevant rules: bash is restricted to the workspace')
    commands = [
        "cp /workspace/tests/test_existing.test.js /scratch/tmp/opencode/test_existing.test.js && "
        "cat > /scratch/tmp/opencode/test_existing.test.js << 'EOF'\n"
        "test('authored by the model', () => expect(true).toBe(true));\nEOF",
        "cp /workspace/tests/test_existing.test.js /scratch/tmp/test_existing.test.js && "
        "cat > /scratch/tmp/test_existing.test.js << 'EOF'\n"
        "test('authored by the model', () => expect(true).toBe(true));\nEOF",
        "cp '/workspace/tests/test existing.test.js' '/scratch/tmp/test existing.test.js' && "
        "cat > '/scratch/tmp/test existing.test.js' << 'DONE'\n"
        "example = '&& ; $HOME'\nDONE",
        "mkdir -p /scratch/tmp/opencode/tests && "
        "cp /workspace/tests/test_existing.test.js /scratch/tmp/opencode/tests/",
        "cp /workspace/tests/test_existing.test.js /scratch/tmp/test_existing.test.js",
        "cat > '/scratch/tmp/cat only.test.js' << 'EOF'\ntest('authored', () => true);\nEOF",
        'mkdir -- /scratch/tmp/one /scratch/tmp/two',
        # The first cp already writes outside /workspace; later command shape does not undo it.
        "cp /workspace/tests/test_existing.test.js /scratch/tmp/test_existing.test.js && "
        "cat > /scratch/tmp/another.test.js << 'EOF'\ntest('authored', () => true);\nEOF",
        "cp /workspace/tests/test_existing.test.js /scratch/tmp/test_existing.test.js ; echo done",
        "cp /workspace/tests/test_existing.test.js /scratch/tmp/test_existing.test.js && cat <<",
    ]
    guard = ToolErrorGuard('B2')
    for index, command in enumerate(commands):
        event = error(denial, f'bash-denial-{index}', 'bash', {'command': command})
        guard.observe(event)
        guard.observe(event)

    assert guard.model_errors == len(commands)
    assert guard.unattributed_errors == 0
    assert [item['message'] for item in guard.evidence] == [denial] * len(commands)
    assert guard.as_dict()['policy'] == 'task-tool-review-v8'


def test_other_bash_permission_denials_remain_unattributed():
    denial = ('The user has specified a rule which prevents you from using this specific tool call. '
              'Here are some of the relevant rules: bash is restricted to the workspace')
    outside_request = (
        "cp /workspace/tests/test_existing.test.js /scratch/tmp/test_existing.test.js && "
        "cat > /scratch/tmp/test_existing.test.js << 'EOF'\n"
        "test('authored by the model', () => expect(true).toBe(true));\nEOF"
    )
    cases = [
        ('edit', outside_request),
        ('bash', outside_request.replace('/scratch/tmp/', '/workspace/tmp/')),
        ('bash', outside_request.replace(
            '/workspace/tests/test_existing.test.js',
            '/workspace/tests/../src/test_existing.test.js')),
        ('bash', outside_request.replace('/scratch/tmp/', 'scratch/tmp/')),
        ('bash', outside_request.replace(
            '/scratch/tmp/test_existing.test.js', '/scratch/tmp/$OUT.test.js')),
        ('bash', outside_request.replace(
            '/workspace/tests/test_existing.test.js', '/workspace/tests/*.test.js')),
        ('bash', "mkdir -p /workspace/tmp && cp /workspace/tests/test_existing.test.js /scratch/tmp/test_existing.test.js"),
        ('bash', "mkdir -p /scratch/tmp/../../workspace/tmp && cp /workspace/tests/test_existing.test.js /scratch/tmp/test_existing.test.js"),
        ('bash', "mkdir -p /scratch/tmp /workspace/tmp"),
        ('bash', 'echo ready && ' + outside_request),
        ('bash', 'cp /workspace/tests/test_existing.test.js'),
        ('bash', 'mkdir -p'),
        ('bash', "cat > /scratch/tmp/test_existing.test.js <<"),
        ('bash', outside_request),
    ]
    for index, (tool, command) in enumerate(cases):
        message = denial if index < len(cases) - 1 else 'Permission denied: bash is restricted'
        guard = ToolErrorGuard('B2')
        guard.observe(error(message, str(index), tool, {'command': command}))
        assert guard.model_errors == 0
        assert guard.unattributed_errors == 1
        assert guard.evidence[-1]['category'] == 'unattributed'
        assert guard.evidence[-1]['message'] == message


def test_deliberate_recovery_errors_are_exempt_only_once():
    guard = ToolErrorGuard('M2')
    args = {'version': 1, 'change_id': 'C-17', 'idempotency_key': 'C-17-v2'}
    event = error('stale or invalid version; read current change and retry', '1', 'lab_apply_change', args)
    guard.observe(event)
    assert guard.reason is None
    assert guard.expected_errors == 1
    guard.observe(error('stale or invalid version; read current change and retry', '2', 'lab_apply_change', args))
    assert guard.model_errors == 1


def test_real_opencode_json_encoded_state_error_is_normalized():
    import json
    guard = ToolErrorGuard('M2')
    for version, message in (
        (1, 'stale or invalid version; read current change and retry'),
        (2, 'temporary service failure; retry the same request and key'),
    ):
        guard.observe(error(json.dumps({'error': message}), str(version), 'lab_apply_change', {
            'version': version, 'change_id': 'C-17', 'idempotency_key': 'C-17-v2'}))
    assert guard.reason is None
    assert guard.expected_errors == 2
    assert guard.model_errors == 0


def test_completed_python_test_failure_is_not_a_tool_transport_error():
    guard = ToolErrorGuard('B1')
    guard.observe({'type': 'tool_use', 'part': {'tool': 'bash', 'state': {
        'status': 'completed', 'output': 'FAILED (failures=1)'}}})
    assert guard.reason is None
    assert guard.model_errors == 0


def test_trusted_tool_start_deadline_stops_a_stalled_child():
    code = "import json,time;print(json.dumps({'_practical_driver':'policy_tool_start','call_id':'a','timeout_seconds':0.2}),flush=True);time.sleep(10)"
    guard = ToolErrorGuard('B2')
    started = time.monotonic()
    _, _, rc = run_guarded([sys.executable, '-c', code], 5, guard)
    assert time.monotonic() - started < 2
    assert rc == 85 and guard.reason == 'tool_timeout'


def test_streaming_guard_stops_child_before_deadline():
    import json
    events = [error('No changes to apply: oldString and newString are identical.', str(i)) for i in range(6)]
    code = 'import time; print(' + repr('\n'.join(json.dumps(e) for e in events)) + ', flush=True); time.sleep(20)'
    guard = ToolErrorGuard('B1')
    started = time.monotonic()
    raw, stderr, rc = run_guarded([sys.executable, '-c', code], 10, guard)
    assert time.monotonic() - started < 4
    assert rc == 86
    assert guard.model_errors == 6
    assert len(raw.splitlines()) == 6


def test_task_quarantine_persists_across_outputs_and_skips_other_models(tmp_path, monkeypatch):
    from benchmark import practical_campaign_v2 as c
    from types import SimpleNamespace
    def save_record(output, record, rows, **kwargs):
        rows[:] = [row for row in rows if c.episode_key(row) != c.episode_key(record)] + [record]
    monkeypatch.setattr(c, '_save_record', save_record)
    monkeypatch.setattr(c, '_save_manifest', lambda *a, **k: None)
    monkeypatch.setattr(c, '_profile_probe', lambda *a, **k: True)
    class Runtime:
        calls = []
        def run_episode(self, model, task, *args, **kwargs):
            self.calls.append((model, task))
            return {'failure': 'task_review', 'review_required': True,
                    'tool_review': {'reason': 'unattributed_tool_error', 'unattributed_tool_errors': 1},
                    'model_tool_errors': 0, 'correct': False, 'autonomous': False}
    runtime = Runtime()
    models = {'a': {}, 'b': {}}
    rows = []
    schedule = c.baseline_schedule(tuple(models), tasks=('B1',))[:2]
    output = tmp_path / 'run1'
    output.mkdir()
    manifest = {'stage_status': {}}
    c._run_stage('baseline', schedule, output=output, rows=rows, manifest=manifest,
                 runtime=runtime, models=models, lab=tmp_path, tasks_module=SimpleNamespace())
    assert runtime.calls == [('a', 'B1')]
    assert rows[0]['status'] == 'review_required'
    assert rows[1]['status'] == 'skipped_review'
    assert 'B1' in manifest['task_quarantines']
    second = tmp_path / 'run2'
    second.mkdir()
    c._run_stage('baseline', schedule, output=second, rows=[], manifest={'stage_status': {}},
                 runtime=runtime, models=models, lab=tmp_path, tasks_module=SimpleNamespace())
    assert runtime.calls == [('a', 'B1')]


def test_quarantined_task_successes_are_excluded_for_every_model():
    from benchmark import practical_campaign_v2 as c
    rows = [{'protocol': c.PROTOCOL, 'stage': 'baseline', 'model': 'a', 'profile': 'baseline',
             'task': 'B1', 'repetition': 1, 'status': 'complete', 'correct': True, 'autonomous': True},
            {'protocol': c.PROTOCOL, 'stage': 'baseline', 'model': 'b', 'profile': 'baseline',
             'task': 'B1', 'repetition': 1, 'status': 'review_required', 'review_required': True}]
    ranking = c.rank_models(rows, ('a', 'b'), metric_tasks=('B1',), required_tasks=('B1',), repetitions=(1,))
    assert all(item['core_completed'] == 0 and not item['eligible'] for item in ranking)


def test_mcp_content_envelope_detects_intentional_error_and_schema_error():
    import json
    guard = ToolErrorGuard('M2')
    event = {'type': 'tool_use', 'part': {'tool': 'lab_apply_change', 'callID': '1', 'state': {
        'status': 'completed', 'input': {'version': 1, 'change_id': 'C-17', 'idempotency_key': 'C-17-v2'},
        'output': {'isError': True, 'content': [{'type': 'text', 'text': json.dumps({
            'error': 'stale or invalid version; read current change and retry'})}]}}}}
    guard.observe(event)
    assert guard.expected_errors == 1
    assert guard.reason is None
    event['part']['callID'] = '2'
    event['part']['state']['output']['content'][0]['text'] = json.dumps({'error': 'Invalid arguments: version'})
    guard.observe(event)
    assert guard.model_errors == 1


def test_arbitrary_shell_json_error_output_is_not_tool_failure():
    guard = ToolErrorGuard('B1')
    guard.observe({'type': 'tool_use', 'part': {'tool': 'bash', 'state': {
        'status': 'completed', 'output': '{"error":"ordinary application test result"}'}}})
    assert guard.reason is None


def test_review_release_in_registry_overrides_stale_manifest_copy(tmp_path):
    from benchmark import practical_campaign_v2 as c
    manifest = {'task_quarantines': {'B1': {'active': True}}}
    c.atomic_write_json(tmp_path / 'results/task-review-registry.json', {
        'B1': {'active': False, 'review_reason': 'fixture repaired and regression passed'}})
    c._load_task_quarantines(tmp_path, manifest)
    assert 'B1' not in manifest['task_quarantines']


def test_malformed_registry_entries_block_before_model_load(tmp_path):
    import pytest
    from benchmark import practical_campaign_v2 as c
    c.atomic_write_json(tmp_path / 'results/task-review-registry.json', {'B1': 'invalid'})
    with pytest.raises(c.CampaignBlocked, match='registry'):
        c._load_task_quarantines(tmp_path, {})


def test_closed_output_streams_do_not_bypass_timeout():
    code = 'import os,time; os.close(1); os.close(2); time.sleep(20)'
    _, _, rc = run_guarded([sys.executable, '-c', code], 0.2, ToolErrorGuard('B1'))
    assert rc == 124


def test_repair_comparison_excludes_previous_success_on_quarantined_task(tmp_path):
    from benchmark import practical_repair as repair
    old = {'stage': 'baseline', 'model': 'a', 'task': 'C2', 'status': 'complete',
           'correct': True, 'autonomous': True, 'seconds': 1}
    review = {'stage': 'baseline', 'model': 'b', 'task': 'C2', 'status': 'review_required',
              'review_required': True}
    repair._write_comparison(tmp_path, [], [old, review])
    report = (tmp_path / 'comparison.md').read_text()
    assert '| a |' not in report
    assert 'C2' in report


# --- Task 2: the terminal budget halt reaches the driver, never the model text ------


def test_budget_halt_trusts_only_harness_error_events():
    import json  # noqa: F401
    from benchmark.practical_driver_v2 import budget_halt

    trusted = {'type': 'error', 'part': {'message': 'budget_exhausted:compaction'}}
    assert budget_halt(trusted) == 'budget_exhausted:compaction'
    assert budget_halt({'type': 'error', 'message': 'budget_exhausted:wall'}) == 'budget_exhausted:wall'
    # model-authored shapes cannot trigger the halt
    assert (budget_halt({'type': 'error', 'part': {'message': 'Sorry budget_exhausted:main'}})
            is None)
    tool_output = {'type': 'tool_use', 'part': {'tool': 'bash', 'state': {
        'status': 'completed', 'output': 'budget_exhausted:main'}}}
    assert budget_halt(tool_output) is None
    assert budget_halt({'type': 'tool_use', 'part': {'state': {'status': 'completed'}}}) is None


def test_budget_error_event_finalizes_the_generation_phase_with_reserved_code():
    import json as json_module
    event = json_module.dumps({'type': 'error',
                               'part': {'message': 'budget_exhausted:compaction'}})
    code = 'import time; print(' + repr(event) + ', flush=True); time.sleep(20)'
    guard = ToolErrorGuard('B2')
    started = time.monotonic()
    raw, stderr, rc = run_guarded([sys.executable, '-c', code], 10, guard)

    assert rc == 88 and guard.reason is None
    assert time.monotonic() - started < 4
    assert 'budget_exhausted:compaction' in raw.decode()
