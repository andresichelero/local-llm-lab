"""Append-only derived evaluations; raw trajectories are never rewritten."""
from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path

# Executions that never observed the model functionally, in any protocol
# version: they are counted in the denominators but never as success.
INVALID_EXECUTION_FAILURES = frozenset({
    'infrastructure', 'contract_error', 'tool_timeout', 'task_review',
    'invalid_execution', 'configuration', 'unknown', 'interrupted'})

VALID_EXECUTION_FAILURES = frozenset({
    'passed', 'wrong_result', 'workflow', 'budget_exhausted', 'call_limit',
    'context_exhausted', 'model_tool_error', 'model_no_progress', 'timeout'})

# Authored-suite regression qualities that support a verified success claim:
# the suite detected the seeded regression, or the language carries no
# authored suite.  `weak` and `unverified` measure a real absence of proof.
VERIFIED_TEST_QUALITIES = frozenset({'regression_detected', 'not_applicable'})


def is_scoring_eligible(row: Mapping) -> bool:
    """The single gate for ranking, summaries, and exports.

    An episode contributes success only when the record is terminal, its
    execution was valid (no infrastructure, invalid contract, review, tool
    timeout, or inconclusive observation), and the explicit v2 eligibility
    flag does not exclude it.  Rows from protocols older than v2 that do
    not carry the flag are judged by this same causal contract through
    their recorded failure label; validity is never fabricated.
    """
    if not isinstance(row, Mapping):
        return False
    if row.get('status') not in (None, 'complete'):
        return False
    failure = row.get('failure')
    if failure not in VALID_EXECUTION_FAILURES:
        return False
    if row.get('execution_valid') is False or row.get('review_required') is True:
        return False
    return row.get('scoring_eligible') is not False


def mechanical_success(row: Mapping) -> bool:
    """A known terminal success, never contradictory legacy boolean flags."""
    return bool(is_scoring_eligible(row) and row.get('failure') == 'passed'
                and row.get('correct') and row.get('autonomous'))


def _outdated_scoring_flag(row: Mapping) -> bool:
    """Legacy state is exported explicitly rather than silently reinterpreted."""
    return 'scoring_eligible' not in row


def verified_success(row: Mapping) -> bool | None:
    """New, separate metric; never derived from `correct && autonomous`.

    ``True`` only when the execution was scoring eligible, the trusted
    graders concluded a functional pass, the workflow completed
    autonomously, and the authored-suite regression diagnosis ran with a
    verified outcome (``regression_detected``, or ``not_applicable`` where
    the language carries no authored suite).  A measured ``weak`` or
    ``unverified`` quality returns ``False``.  A row that never carried the
    quality field (legacy records, infrastructure paths) returns ``None``:
    its validity was never measured and is never fabricated.
    """
    if not isinstance(row, Mapping):
        return None
    quality = row.get('authored_test_quality')
    if quality is None:
        return None
    if row.get('execution_valid') is None or row.get('workflow_complete') is None:
        return None
    return bool(mechanical_success(row)
                and row.get('functional_correct')
                and row.get('workflow_complete') and row.get('failure') == 'passed'
                and quality in VERIFIED_TEST_QUALITIES)


VERDICT_GRADER_FILES = tuple(sorted({
    path.name for path in Path(__file__).parent.glob('practical_*')
    if path.suffix in {'.py', '.mjs'}
} | {'model_broker.py', 'linux_sandbox.py', 'sandbox_bootstrap.py',
     'campaign_readiness.py'}))


def verdict_grader_hashes() -> dict[str, str]:
    """The pinned grader sources whose hashes stamp every appended verdict."""
    code = Path(__file__).parent
    return {name: hashlib.sha256((code / name).read_bytes()).hexdigest()
            for name in VERDICT_GRADER_FILES}


def verdict_version() -> str:
    """Directory id for verdicts from this exact grader-source set."""
    grader_hashes = verdict_grader_hashes()
    return hashlib.sha256(json.dumps(grader_hashes, sort_keys=True).encode()).hexdigest()[:20]


def append_verdict(run_dir: Path, verdict: dict) -> Path:
    root = Path(run_dir)
    grader_hashes = verdict_grader_hashes()
    version = verdict_version()
    sources = {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
               for p in [root/'record.json', root/'native.jsonl', root/'execution.json',
                         root/'mcp-journal.json', *root.glob('.snapshot*.zip')]
               if p.is_file()}
    destination = root / 'evaluations' / version / (uuid.uuid4().hex + '.json')
    destination.parent.mkdir(parents=True, exist_ok=True)
    value = {'schema_version': 1, 'task_contract_id': str(
                 verdict.get('task_contract_id') or 'historical-v2'),
             'evaluated_at_utc': datetime.now(timezone.utc).isoformat(),
             'grader_hashes': grader_hashes, 'source_hashes': sources, 'verdict': verdict,
             'evaluation_producer':verdict.get('evaluation_producer') or {'id':'runtime-regrade'}}
    with destination.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write('\n')
    return destination


def paired_task_summary(rows):
    """Task is the unit; repeats are not additional independent tasks."""
    cells = {}
    for row in rows:
        if row.get('status') != 'complete':
            continue
        # Ineligible executions (infrastructure, invalid contract, unknown
        # observation) stay in the trial denominator with zero contribution.
        parsed = mechanical_success(row)
        measured = verified_success(row)
        key = (row.get('model'), row.get('task'))
        cells.setdefault(key, []).append((parsed, measured))
    summary = []
    for (model, task), observations in sorted(cells.items()):
        parsed_values = [value for value, _ in observations]
        measured_values = [value for _, value in observations]
        cell = {'model': model, 'task': task, 'trials': len(parsed_values),
                'mean_success': sum(parsed_values)/len(parsed_values),
                'all_trials_success': all(parsed_values)}
        if any(value is None for value in measured_values):
            # A cell mixing rows that never measured the authored-test
            # quality states no verified rate at all rather than a partial
            # number that would look like a measured result.
            cell['verified_success_rate'] = None
        else:
            cell['verified_success_rate'] = sum(measured_values)/len(measured_values)
        summary.append(cell)
    return summary


def outcome_summary(rows, scheduled):
    """Keep missing and invalid executions in the end-to-end denominator."""
    from benchmark.practical_campaign_v2 import episode_key
    planned = {episode_key(row) for row in scheduled}
    selected = {}
    duplicates = 0
    for row in rows:
        key = episode_key(row)
        if key not in planned:
            continue
        duplicates += key in selected
        selected[key] = row
    valid = [row for row in selected.values() if row.get('status') == 'complete'
             and is_scoring_eligible(row)]
    successful = sum(mechanical_success(row) for row in valid)
    measured = [row for row in valid if row.get('authored_test_quality') is not None]
    verified = sum(bool(verified_success(row)) for row in measured)
    legacy = sum(_outdated_scoring_flag(row) for row in selected.values())
    return {'scheduled': len(planned), 'recorded': len(selected), 'missing': len(planned-selected.keys()),
            'duplicate_records': duplicates, 'legacy_records': legacy, 'valid_executions': len(valid),
            'invalid_or_incomplete_executions': len(selected)-len(valid), 'successful': successful,
            'verified_success': verified,
            'quality_measured_valid_executions': len(measured),
            'quality_unmeasured_valid_executions': len(valid) - len(measured),
            'verified_success_rate_among_measured': verified/len(measured) if measured else None,
            'end_to_end_success_rate': successful/len(planned) if planned else None,
            'conditional_valid_success_rate': successful/len(valid) if valid else None}
