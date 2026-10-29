import json

from benchmark import baseline_report as report


def result(root, arm, task, rep, attempt, category, failure=None, **extra):
    path = root / 'units' / arm / f'{task}-r{rep}' / f'attempt-{attempt:02d}' / 'result.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({'unit': {'arm': arm, 'task': task, 'repetition': rep},
                               'category': category, 'failure': failure, **extra}))


def test_first_non_infrastructure_and_pairs(tmp_path):
    result(tmp_path, 'C4-q4', 'a', 1, 1, 'infrastructure', 'server_exited')
    result(tmp_path, 'C4-q4', 'a', 1, 2, 'success')
    result(tmp_path, 'C4-q4', 'b', 1, 1, 'model', 'model_oracle_failed')
    result(tmp_path, 'S', 'a', 1, 1, 'model', 'model_oracle_failed',
           total_seconds=8, usage={'prompt_tokens': 10, 'completion_tokens': 2},
           proxy_requests=[{'ttft_ms': 200, 'timings': [{'prompt_per_second': 100,
                           'predicted_per_second': 20, 'prompt_n': 4, 'cache_n': 6}]}],
           peak_vram_mib=100, taxonomy={'primary': 'oracle_only', 'secondary': []})
    result(tmp_path, 'S', 'a', 1, 2, 'success')
    result(tmp_path, 'S', 'b', 1, 1, 'success')
    selected = report.read_results([tmp_path])
    assert len(selected) == 4
    tables = report.summarize(selected)
    arm = next(row for row in tables['arms'] if row['arm'] == 'S')
    assert (arm['n'], arm['successes'], arm['wasted_prompt_tokens'], arm['wasted_seconds']) == (2, 1, 10, 8)
    assert arm['prefill_tok_s_median'] == 100
    assert arm['cache_tokens_total'] is None  # Missing timing cannot be treated as zero.
    comparison = tables['comparisons'][0]
    assert (comparison['wins'], comparison['losses'], comparison['ties']) == (1, 1, 0)
    assert comparison['mcnemar_p'] == 1.0
    assert {r['task'] for r in tables['tasks']} == {'a', 'b'}


def test_infra_only_excluded_and_wilson():
    assert report.wilson(0, 0) == (None, None)
    low, high = report.wilson(5, 10)
    assert abs(low - 0.2366) < 0.001 and abs(high - 0.7634) < 0.001
    assert report.mcnemar_exact(0, 4) == 0.125


def test_report_files_and_empty_metrics(tmp_path):
    data = tmp_path / 'data'
    result(data, 'B0', 'a', 1, 1, 'success')
    result(data, 'B-x', 'a', 1, 1, 'model', 'model_cli_failure')
    output = tmp_path / 'report.md'
    csv = tmp_path / 'report.csv'
    report.main([str(data), '--markdown', str(output), '--csv', str(csv)])
    assert 'McNemar' in output.read_text(encoding='utf-8')
    assert 'comparison' in csv.read_text(encoding='utf-8')
    assert report.summarize(report.read_results([data]))['arms'][0]['ttft_ms_median'] is None



def test_cross_directory_control_and_v5_category_bug(tmp_path):
    old, new = tmp_path / 'v5', tmp_path / 'v6'
    result(old, 'B0', 'task', 1, 1, 'infrastructure', 'harness_missing_session')
    result(old, 'B0', 'task', 1, 2, 'success')
    result(new, 'B-ctx32', 'task', 1, 1, 'success')
    rows = report.read_results([old, new])
    assert len(rows) == 2
    paired = report.summarize(rows, control='B0', control_dir=old)['comparisons']
    assert paired[0]['wins'] == 1 and paired[0]['losses'] == 0
    assert paired[0]['control_source'] == str(old.resolve())


def test_incomplete_request_timings_never_report_partial_token_total(tmp_path):
    result(tmp_path, 'B0', 'a', 1, 1, 'success', proxy_requests=[
        {'timings': [{'prompt_n': 10, 'cache_n': 4}]}, {'timings': []}])
    arm = report.summarize(report.read_results([tmp_path]))['arms'][0]
    assert arm['processed_tokens_total'] is None
    assert arm['cache_tokens_total'] is None


def test_task_stability_requires_repetition_and_compares_arms(tmp_path):
    result(tmp_path, 'B0', 'a', 1, 1, 'success')
    result(tmp_path, 'B0', 'a', 2, 1, 'model', 'model_oracle_failed')
    result(tmp_path, 'S', 'a', 1, 1, 'success')
    tables = report.summarize(report.read_results([tmp_path]))
    assert next(row for row in tables['tasks'] if row['arm'] == 'B0')['stability'] == 'mixed'
    assert next(row for row in tables['tasks'] if row['arm'] == 'S')['stability'] == 'insufficient'
    compared = tables['task_comparisons'][0]
    assert compared['task'] == 'a'
    assert json.loads(compared['arms']) == {'B0': {'n': 2, 'successes': 1}, 'S': {'n': 1, 'successes': 1}}


def test_legacy_no_model_calls_does_not_imply_zero_tokens(tmp_path):
    result(tmp_path, 'B0', 'a', 1, 1, 'model', 'model_cli_failure', total_seconds=2,
           usage={'model_calls': 0, 'prompt_tokens': 0, 'completion_tokens': 0})
    arm = report.summarize(report.read_results([tmp_path]))['arms'][0]
    assert arm['wasted_prompt_tokens'] is None
    assert arm['wasted_completion_tokens'] is None
