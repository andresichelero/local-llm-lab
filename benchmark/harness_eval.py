"""Independent grader for the deterministic coding-agent harness task."""
from __future__ import annotations

import ast
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


ALLOWED_CHANGES = {"src/calculator.py", "tests/test_calculator.py"}
REQUIRED_TESTS = {
    "test_divide_positive",
    "test_divide_negative",
    "test_divide_by_zero",
}


def _source_files(root: Path) -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    for path in root.rglob("*"):
        if not path.is_file() or ".git" in path.parts or "__pycache__" in path.parts:
            continue
        if path.suffix == ".pyc":
            continue
        files[path.relative_to(root).as_posix()] = path.read_bytes()
    return files


def _functions(source: str, names: set[str]) -> dict[str, str]:
    tree = ast.parse(source)
    return {
        node.name: ast.dump(node, include_attributes=False)
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names
    }


def grade_workspace(workspace: Path, baseline: Path) -> dict[str, Any]:
    """Run tests and behavior probes, then check task scope and preserved helpers."""
    workspace = workspace.resolve()
    baseline = baseline.resolve()
    test_run = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
        cwd=workspace,
        capture_output=True,
        text=True,
        timeout=45,
    )
    test_output = f"{test_run.stdout}{test_run.stderr}"

    probe_code = (
        "from src.calculator import add, divide, multiply\n"
        "assert divide(10, 2) == 5\n"
        "assert divide(-10, 2) == -5\n"
        "assert divide(10, -2) == -5\n"
        "try:\n"
        "    divide(10, 0)\n"
        "except ValueError as error:\n"
        "    assert str(error) == 'division by zero'\n"
        "else:\n"
        "    raise AssertionError('divide(10, 0) must raise ValueError')\n"
        "assert add(2, 3) == 5\n"
        "assert multiply(2, 3) == 6\n"
    )
    probe_env = os.environ.copy()
    probe_env["PYTHONPATH"] = str(workspace)
    probe_run = subprocess.run(
        [sys.executable, "-c", probe_code],
        cwd=workspace,
        env=probe_env,
        capture_output=True,
        text=True,
        timeout=15,
    )

    try:
        candidate_source = (workspace / "src/calculator.py").read_text(encoding="utf-8")
        original_source = (baseline / "src/calculator.py").read_text(encoding="utf-8")
        candidate_tests = ast.parse(
            (workspace / "tests/test_calculator.py").read_text(encoding="utf-8")
        )
        test_names = {
            node.name
            for node in ast.walk(candidate_tests)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        unchanged_helpers = _functions(candidate_source, {"add", "multiply"}) == _functions(
            original_source, {"add", "multiply"}
        )
    except (OSError, SyntaxError):
        test_names = set()
        unchanged_helpers = False

    original_files = _source_files(baseline)
    candidate_files = _source_files(workspace)
    changed_files = sorted(
        path
        for path in original_files.keys() | candidate_files.keys()
        if original_files.get(path) != candidate_files.get(path)
    )
    changes_scoped = bool(changed_files) and set(changed_files) <= ALLOWED_CHANGES
    divide_tests_present = REQUIRED_TESTS <= test_names
    unit_tests_passed = test_run.returncode == 0
    behavioral_probe_passed = probe_run.returncode == 0
    success = all(
        (
            unit_tests_passed,
            behavioral_probe_passed,
            divide_tests_present,
            unchanged_helpers,
            changes_scoped,
        )
    )
    return {
        "success": success,
        "unit_tests_passed": unit_tests_passed,
        "behavioral_probe_passed": behavioral_probe_passed,
        "divide_tests_present": divide_tests_present,
        "unchanged_helpers": unchanged_helpers,
        "changes_scoped": changes_scoped,
        "changed_files": changed_files,
        "test_output": test_output,
        "behavioral_probe_stderr": probe_run.stderr,
    }
