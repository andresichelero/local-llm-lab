"""Public grading entry points for the local coding-agent harness."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from benchmark.pristine_grading import (
    GRADER_PROTOCOL_VERSION as GRADER_PROTOCOL_VERSION,
    REPO_ROOT,
    TASK_ALIASES,
    TASK_POLICIES,
    _canonical_task,
    grade_pristine_workspace,
)


REQUIRED_TESTS = {
    "test_divide_positive",
    "test_divide_negative",
    "test_divide_by_zero",
}

TASK_SUITE_MAP = {
    task: policy["suite"]
    for task, policy in TASK_POLICIES.items()
}
TASK_SUITE_MAP.update({alias: TASK_POLICIES[canonical]["suite"] for alias, canonical in TASK_ALIASES.items()})


def _verify_required_tests(test_names: set[str]) -> bool:
    """Check the historical calculator test-name groups used by callers."""
    positive_variants = {
        "test_divide_positive",
        "test_divide_positive_operands",
        "test_positive_operands",
        "test_divide_positives",
        "test_divide_positive_numbers",
    }
    negative_variants = {
        "test_divide_negative",
        "test_divide_negative_operand",
        "test_divide_negative_operands",
        "test_negative_operand",
        "test_negative_operands",
        "test_divide_negatives",
        "test_divide_negative_numbers",
    }
    zero_variants = {"test_divide_by_zero", "test_division_by_zero", "test_divide_zero"}
    has_positive = bool(test_names & positive_variants) or any("positive" in name for name in test_names)
    has_negative = bool(test_names & negative_variants) or any("negative" in name for name in test_names)
    has_zero = bool(test_names & zero_variants) or any("zero" in name for name in test_names)
    return has_positive and has_negative and has_zero


def run_held_out_tests(workspace: Path, task: str) -> tuple[bool, str, str]:
    """Compatibility wrapper backed by the fingerprinted restricted grader."""
    try:
        canonical = _canonical_task(task)
    except ValueError:
        return False, "", f"No evaluation suite or inline probe found for task: {task}"
    fixture = REPO_ROOT / TASK_POLICIES[canonical]["fixture"]
    result = grade_pristine_workspace(workspace, fixture, canonical)
    return (
        result.get("functional_pass") is True,
        "",
        str(result.get("behavioral_probe_stderr") or result.get("functional_details", {}).get("reason") or ""),
    )


def run_baseline_tests(workspace: Path, baseline: Path) -> tuple[bool, str]:
    """Run only fingerprinted fixture checks over interpreted candidate source."""
    baseline_path = Path(baseline).resolve(strict=False)
    task = next(
        (
            name
            for name, policy in TASK_POLICIES.items()
            if (REPO_ROOT / policy["fixture"]).resolve(strict=False) == baseline_path
        ),
        None,
    )
    if task is None:
        return False, "baseline_path_does_not_match_fixed_task_fixture"
    result = grade_pristine_workspace(workspace, baseline, task)
    return result.get("regression_pass") is True, str(result.get("test_output", ""))


def grade_workspace(
    workspace: Path,
    baseline: Path,
    task: str = "calculator_division",
    artifact_dir: Path | None = None,
) -> dict[str, Any]:
    """Grade a workspace with fingerprinted trusted tests and restricted source."""
    return grade_pristine_workspace(workspace, baseline, task=task, artifact_dir=artifact_dir)


def grade_workspace_legacy(
    workspace: Path,
    baseline: Path,
    task: str = "calculator_division",
) -> dict[str, Any]:
    """Return an explicit unavailable result for historical v1 grading.

    Re-executing the old grader here would silently mix v1 native-run results
    with the restricted-python-v2 protocol. The historical implementation is
    preserved at pre-v2 commit 1808da3; this compatibility name performs no
    grading and does not inspect either path.
    """
    del workspace, baseline
    return {
        "grader_protocol_version": "pristine-workspace-v1",
        "task": task,
        "success": False,
        "functional_pass": None,
        "regression_pass": None,
        "evaluation_status": "historical_only_unavailable",
        "legacy_native_execution": False,
        "legacy_reference_commit": "1808da3",
        "legacy_execution_available": False,
        "skip_reasons": ["historical_v1_grader_not_available_for_reexecution"],
        "error": "Historical v1 grading is unavailable in this v2 runner; reference pre-v2 commit 1808da3.",
    }
