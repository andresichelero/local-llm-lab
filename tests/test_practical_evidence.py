import hashlib
import json

from benchmark.practical_evidence import (
    append_verdict,
    paired_task_summary,
    verified_success,
)


def test_regrading_appends_without_rewriting_raw_or_original_score(tmp_path):
    native = tmp_path / "native.jsonl"
    native.write_text('{"event":"raw"}\n')
    original = tmp_path / "record.json"
    original.write_text('{"correct":false}')
    before = hashlib.sha256(native.read_bytes() + original.read_bytes()).hexdigest()
    a = append_verdict(tmp_path, {"correct": False})
    b = append_verdict(tmp_path, {"correct": True})
    assert a != b and a.exists() and b.exists()
    assert json.loads(b.read_text())["source_hashes"]["native.jsonl"]
    assert (
        hashlib.sha256(native.read_bytes() + original.read_bytes()).hexdigest()
        == before
    )


def test_reliability_is_not_best_of_trials():
    rows = [
        {
            "model": "m",
            "task": "B2",
            "status": "complete",
            "correct": c,
            "autonomous": True,
            "failure": "passed" if c else "wrong_result",
        }
        for c in (True, False, True)
    ]
    cell = paired_task_summary(rows)[0]
    assert cell["mean_success"] == 2 / 3
    assert not cell["all_trials_success"]


def test_missing_and_infrastructure_stay_in_end_to_end_denominator():
    from benchmark.practical_evidence import outcome_summary
    from benchmark.practical_campaign_v2 import baseline_schedule

    schedule = baseline_schedule(("m",), tasks=("B2",))
    rows = [
        {
            **schedule[0],
            "status": "complete",
            "correct": True,
            "autonomous": True,
            "failure": "passed",
        },
        {**schedule[1], "status": "blocked", "failure": "infrastructure"},
    ]
    result = outcome_summary(rows, schedule)
    assert result["scheduled"] == 3 and result["missing"] == 1
    assert result["valid_executions"] == 1
    assert result["end_to_end_success_rate"] == 1 / 3
    assert result["conditional_valid_success_rate"] == 1


def test_evaluator_version_includes_the_imported_mcp_oracle(tmp_path):
    path = append_verdict(tmp_path, {"correct": False})
    evaluation = json.loads(path.read_text())

    assert "practical_mcp_v2.py" in evaluation["grader_hashes"]


# --- Task 5: append-only evaluations carry the resolved contract id ----------------


def test_append_verdict_copies_the_explicit_contract_id(tmp_path):
    path = append_verdict(
        tmp_path, {"correct": True, "task_contract_id": "m1-independent-copy-v1"}
    )
    evaluation = json.loads(path.read_text())
    assert evaluation["task_contract_id"] == "m1-independent-copy-v1"
    assert evaluation["grader_hashes"]["practical_tasks_v2.py"]
    assert evaluation["source_hashes"] == {}


def test_append_verdict_snapshots_the_historical_contract_by_default(tmp_path):
    path = append_verdict(tmp_path, {"correct": False})
    evaluation = json.loads(path.read_text())
    assert evaluation["task_contract_id"] == "historical-v2"


# --- Task 6: verified_success is a distinct metric, never fabricated --------------


def _verified_row(**overrides):
    row = {
        "status": "complete",
        "correct": True,
        "functional_correct": True,
        "autonomous": True,
        "scoring_eligible": True,
        "authored_test_quality": "regression_detected",
        "model": "m",
        "task": "B1",
        "failure": "passed",
        "execution_valid": True,
        "workflow_complete": True,
    }
    row.update(overrides)
    return row


def test_verified_success_requires_eligible_function_workflow_and_a_diagnosis():
    assert verified_success(_verified_row()) is True
    assert (
        verified_success(_verified_row(authored_test_quality="not_applicable")) is True
    )
    assert verified_success(_verified_row(authored_test_quality="weak")) is False
    assert verified_success(_verified_row(authored_test_quality="unverified")) is False
    assert verified_success(_verified_row(autonomous=False)) is False
    assert verified_success(_verified_row(functional_correct=None)) is False
    assert (
        verified_success(_verified_row(correct=False, functional_correct=False))
        is False
    )
    assert verified_success(_verified_row(scoring_eligible=False)) is False
    assert verified_success(_verified_row(failure="infrastructure")) is False
    # Validity was never measured where the quality field is absent or None:
    # legacy rows stay unverifiable instead of a fabricated False or True.
    assert verified_success({"correct": True, "autonomous": True}) is None
    assert verified_success(_verified_row(authored_test_quality=None)) is None
    assert verified_success("not-a-mapping") is None


def test_paired_summary_states_no_verified_rate_for_partially_measured_cells():
    legacy = {
        "model": "m",
        "task": "B1",
        "status": "complete",
        "correct": True,
        "autonomous": True,
        "failure": "passed",
    }
    strong = _verified_row()
    failing = _verified_row(
        authored_test_quality="unverified",
        correct=False,
        functional_correct=False,
        autonomous=False,
    )
    cell = paired_task_summary([legacy, strong, failing])[0]
    assert cell["trials"] == 3
    assert cell["mean_success"] == 2 / 3
    # The legacy row never measured the quality: a partial rate is not stated.
    assert cell["verified_success_rate"] is None

    fully = paired_task_summary([strong, failing])[0]
    assert fully["verified_success_rate"] == 0.5
    all_measured_strong = paired_task_summary([strong, strong])[0]
    assert all_measured_strong["verified_success_rate"] == 1.0


def test_outcome_summary_counts_verified_and_unmeasured_separately():
    from benchmark.practical_evidence import outcome_summary
    from benchmark.practical_campaign_v2 import baseline_schedule

    schedule = baseline_schedule(("m",), tasks=("B1", "B2"))
    rows = [
        {
            **schedule[0],
            "status": "complete",
            "correct": True,
            "functional_correct": True,
            "autonomous": True,
            "authored_test_quality": "regression_detected",
            "failure": "passed",
            "execution_valid": True,
            "workflow_complete": True,
        },
        {
            **schedule[1],
            "status": "complete",
            "correct": True,
            "functional_correct": True,
            "autonomous": True,
            "failure": "passed",
        },
    ]
    result = outcome_summary(rows, schedule)
    assert result["valid_executions"] == 2
    assert result["quality_measured_valid_executions"] == 1
    assert result["quality_unmeasured_valid_executions"] == 1
    assert result["verified_success"] == 1
    assert result["verified_success_rate_among_measured"] == 1.0

    weak = [
        {
            **schedule[0],
            "status": "complete",
            "correct": True,
            "functional_correct": True,
            "autonomous": True,
            "authored_test_quality": "weak",
            "failure": "passed",
            "execution_valid": True,
            "workflow_complete": True,
        }
    ]
    outcome = outcome_summary(weak, schedule[:1])
    assert outcome["verified_success"] == 0
    assert outcome["verified_success_rate_among_measured"] == 0.0


# --- Task 2: single eligibility gate and explicit legacy export --------------------


def test_infrastructure_is_a_zero_contribution_trial_that_stays_counted():
    from benchmark.practical_evidence import is_scoring_eligible

    rows = [
        {
            "model": "m",
            "task": "B1",
            "status": "complete",
            "correct": True,
            "autonomous": True,
            "failure": "infrastructure",
            "scoring_eligible": False,
        }
    ]
    cell = paired_task_summary(rows)[0]

    assert cell["trials"] == 1
    assert cell["mean_success"] == 0
    assert cell["all_trials_success"] is False
    assert is_scoring_eligible(rows[0]) is False


def test_legacy_rows_without_the_flag_keep_v1_semantics():
    lines = [
        {
            "model": "m",
            "task": "B1",
            "status": "complete",
            "correct": True,
            "autonomous": True,
            "failure": "passed",
        },  # v1 record, no flag
        {
            "model": "m",
            "task": "B2",
            "status": "complete",
            "correct": True,
            "autonomous": True,
            "failure": "infrastructure",
        },  # legacy leak, no flag
    ]
    cells = {item["task"]: item for item in paired_task_summary(lines)}
    assert cells["B1"]["mean_success"] == 1
    assert cells["B2"]["mean_success"] == 0


def test_invalid_execution_stays_in_the_end_to_end_denominator_without_success():
    from benchmark.practical_evidence import outcome_summary
    from benchmark.practical_campaign_v2 import baseline_schedule

    schedule = baseline_schedule(("m",), tasks=("B2",))
    rows = [
        {
            **schedule[0],
            "status": "complete",
            "correct": False,
            "functional_correct": None,
            "autonomous": False,
            "failure": "invalid_execution",
            "scoring_eligible": False,
        }
    ]

    result = outcome_summary(rows, schedule)

    assert result["valid_executions"] == 0
    assert result["invalid_or_incomplete_executions"] == 1
    assert result["successful"] == 0
    assert result["end_to_end_success_rate"] == 0


def test_legacy_state_is_exported_not_reinterpreted_or_fabricated():
    from benchmark.practical_evidence import _outdated_scoring_flag, outcome_summary
    from benchmark.practical_campaign_v2 import baseline_schedule

    schedule = baseline_schedule(("m",), tasks=("B2",))
    rows = [
        {
            **schedule[0],
            "status": "complete",
            "correct": True,
            "autonomous": True,
            "failure": "passed",
        },
        {
            **schedule[1],
            "status": "complete",
            "correct": True,
            "autonomous": True,
            "failure": "infrastructure",
        },
    ]

    result = outcome_summary(rows, schedule)

    assert result["legacy_records"] == 2
    assert all(_outdated_scoring_flag(row) for row in rows)
    assert result["valid_executions"] == 1
    assert result["invalid_or_incomplete_executions"] == 1
    assert result["successful"] == 1
