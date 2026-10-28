"""Explicitly invoked review regressions; excluded from default test discovery."""

import fcntl
import importlib.util
import json
import pytest
from contextlib import contextmanager
from pathlib import Path

from benchmark import post_audit_v9_regrade as sweep

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "known_task8_tests", ROOT / "tests/test_post_audit_v9_regrade.py"
)
helpers = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helpers)


def fixture(tmp_path):
    run_dir, _ = helpers._fake_episode_record(tmp_path, tmp_path / "out-1")
    census = helpers._census(tmp_path, [run_dir])
    return run_dir, census


@pytest.mark.parametrize("correct", [None, True])
def test_sensitivity_or_unowned_verdict_is_not_used_as_main(tmp_path, correct):
    run_dir, _ = fixture(tmp_path)
    directory = run_dir / "evaluations" / sweep.verdict_version()
    directory.mkdir(parents=True)
    (directory / "foreign.json").write_text(
        json.dumps(
            {
                "evaluated_at_utc": "9999-01-01T00:00:00Z",
                "source_hashes": {"native.jsonl": "stale"},
                "verdict": {
                    "correct": correct,
                    "task_contract_id": "m1-independent-copy-v1",
                    "verdict_profile": "sensitivity",
                },
            }
        )
    )
    assert sweep._existing_round_verdict(run_dir) is None


def test_sweep_refuses_when_global_lab_is_owned(tmp_path, monkeypatch):
    _, census = fixture(tmp_path)
    lab = tmp_path / "lab"
    (lab / "state").mkdir(parents=True)
    monkeypatch.setattr(sweep.runtime, "LAB", lab)
    calls = []
    monkeypatch.setattr(
        sweep, "_regrade_and_record", lambda outcome, prior: calls.append(outcome) or {}
    )
    with (lab / "state/practical-round.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        sweep.run_sweep(census_path=census, collection_dir=None)
    assert not calls, "CPU grading ran while the global laboratory lock was held"


def test_evidence_is_reverified_after_output_lock_acquired(tmp_path, monkeypatch):
    run_dir, census = fixture(tmp_path)
    calls = []

    @contextmanager
    def changed_after_verification(output):
        (run_dir / "native.jsonl").write_text("changed between verification and lock\n")
        yield

    monkeypatch.setattr(sweep, "output_lock", changed_after_verification)
    monkeypatch.setattr(
        sweep, "_regrade_and_record", lambda outcome, prior: calls.append(outcome) or {}
    )
    result = sweep.run_sweep(census_path=census, collection_dir=None)
    assert not calls, "Changed evidence was graded using the pre-lock verification"
    assert result["review_required"]


def test_invalid_grader_is_review_not_functional_negative(tmp_path, monkeypatch):
    _, census = fixture(tmp_path)

    def invalid_grader(run_dir, row, **kwargs):
        return {
            "task": row["task"],
            "model": row["model"],
            "correct": False,
            "task_contract_id": "historical-v2",
            "verdict_profile": "main",
            "evaluation_path": str(tmp_path / "invalid-evaluation.json"),
            "phases": [
                {
                    "phase": 1,
                    "hidden": {
                        "passed": False,
                        "infrastructure": True,
                        "reason": "grade collector report absent",
                    },
                    "authored_tests": {},
                }
            ],
        }

    monkeypatch.setattr(sweep.runtime, "_regrade_record", invalid_grader)
    result = sweep.run_sweep(census_path=census, collection_dir=None)
    assert result["review_required"], (
        "An explicitly invalid grader was accepted as a functional rejection"
    )
    assert not result["regraded"]
