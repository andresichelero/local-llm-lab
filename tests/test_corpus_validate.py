"""Tests for corpus integrity and outcome classification."""

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest


def load_validator():
    path = Path(__file__).resolve().parents[1] / "corpus" / "validate_corpus.py"
    if str(path.parent) not in sys.path:
        sys.path.insert(0, str(path.parent))
    spec = importlib.util.spec_from_file_location("corpus_validate", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_manifest_detects_changed_and_extra_files(tmp_path):
    validator = load_validator()
    (tmp_path / "item.txt").write_text("initial", encoding="utf-8")
    expected = validator.hash_tree(tmp_path)
    assert validator.check_manifest(tmp_path, expected) == []
    (tmp_path / "item.txt").write_text("changed", encoding="utf-8")
    (tmp_path / "extra.txt").write_text("extra", encoding="utf-8")
    assert set(validator.check_manifest(tmp_path, expected)) == {"item.txt", "extra.txt"}


def test_changed_paths_includes_additions_deletions_and_changes():
    validator = load_validator()
    assert validator.changed_paths({"a": "old", "removed": "x"}, {"a": "new", "added": "x"}) == {
        "a", "removed", "added"
    }


@pytest.mark.parametrize(
    ("code", "evidence", "expected"),
    [(0, {"assertions": 0, "errors": 0}, 0),
     (1, {"assertions": 1, "errors": 0}, 1),
     (1, {"assertions": 0, "errors": 1}, 2),
     (1, {"assertions": 1, "errors": 1}, 2),
     (2, {"assertions": 0, "errors": 0}, 2)],
)
def test_pytest_classification_rejects_errors(code, evidence, expected):
    assert load_validator().classify_pytest(code, evidence) == expected


def test_prefix_masks_all_original_solution_lines():
    validator = load_validator()
    prefix = validator.masked_prefix(validator.ROOT, "bottle-0.13.2")
    assert "min(int(end) + 1, maxlen)" not in prefix
    assert "task-specific line withheld" in prefix
    assert 40000 < len(prefix) / 3.5 < 100000


@pytest.mark.parametrize(
    ("statement", "expected"), [("assert False", 1), ("pytest.fail('failure')", 1), ("raise RuntimeError('error')", 2), ("pass", 0)]
)
def test_pytest_probe_classifies_real_failures(tmp_path, statement, expected):
    validator = load_validator()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    oracle = tmp_path / "oracle.py"
    oracle.write_text(f"import pytest\n\ndef test_probe():\n    {statement}\n", encoding="utf-8")
    support = str(validator.ROOT / "support")
    env = dict(os.environ, PYTHONPATH=str(workspace) + os.pathsep + support, CORPUS_SUPPORT=support)
    assert validator.run_oracle(oracle, workspace, env, "test") == expected


def test_visible_verifier_runs_without_pythonpath():
    validator = load_validator()
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    env.pop("PYTHONPATH", None)
    task = validator.ROOT / "tasks" / "py_range" / "verify.py"
    host = validator.ROOT / "hosts" / "bottle-0.13.2"
    assert subprocess.run([sys.executable, str(task)], cwd=host, env=env, capture_output=True, check=False).returncode == 0


def test_javascript_import_failure_is_infrastructure(tmp_path):
    validator = load_validator()
    node = Path("/home/foxtrot/.nvm/versions/node/v25.5.0/bin/node")
    if not node.exists():
        pytest.skip("the designated WSL node is unavailable")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    support = str(validator.ROOT / "support")
    env = dict(os.environ, PYTHONPATH=str(workspace) + os.pathsep + support,
               CORPUS_SUPPORT=support, CORPUS_NODE=str(node))
    oracle = validator.ROOT / "oracles" / "js_sign" / "oracle.py"
    assert validator.run_oracle(oracle, workspace, env, "js-infra") == 2


def test_continuation_keeps_followup_out_of_first_metadata():
    import json

    validator = load_validator()
    for task in ("cont_path", "cont_quote"):
        folder = validator.ROOT / "tasks" / task
        first = json.loads((folder / "task.json").read_text(encoding="utf-8"))
        second = json.loads((folder / "followup.json").read_text(encoding="utf-8"))
        assert first["phase"] == 1 and second["phase"] == 2
        assert second["objective"] not in json.dumps(first)


@pytest.mark.parametrize(
    ("bug", "reference", "visible", "original", "expected"),
    [(1, 0, 0, 0, True), (0, 0, 0, 0, False), (1, 1, 0, 0, False),
     (1, 0, 1, 0, False), (1, 0, 0, 1, False), (2, 0, 0, 0, False)],
)
def test_outcomes_require_assertion_failure_not_infrastructure_error(
    bug, reference, visible, original, expected
):
    validator = load_validator()
    assert validator.valid_outcomes(bug, reference, visible, original) is expected
