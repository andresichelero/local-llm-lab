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


def grade_workspace(
    workspace: Path,
    baseline: Path,
    task: str = "calculator_division",
) -> dict[str, Any]:
    """Run tests and behavior probes, then check task scope and preserved helpers."""
    if task == "whitespace_normalization":
        return _grade_whitespace_normalization(workspace, baseline)
    if task == "dotenv_line_parser":
        return _grade_env_parser(workspace, baseline)
    if task != "calculator_division":
        raise ValueError(f"Unsupported task: {task}")

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
        "required_tests_present": divide_tests_present,
        "unchanged_helpers": unchanged_helpers,
        "changes_scoped": changes_scoped,
        "changed_files": changed_files,
        "test_output": test_output,
        "behavioral_probe_stderr": probe_run.stderr,
    }


def _grade_whitespace_normalization(workspace: Path, baseline: Path) -> dict[str, Any]:
    workspace = workspace.resolve()
    baseline = baseline.resolve()
    test_run = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
        cwd=workspace,
        capture_output=True,
        text=True,
        timeout=45,
    )
    probe_code = (
        "from src.text_utils import normalize_whitespace, word_count\n"
        "assert normalize_whitespace('  alpha\\tbeta\\n gamma  ') == 'alpha beta gamma'\n"
        "assert normalize_whitespace('\\u00a0café\\u2003x') == 'café x'\n"
        "assert normalize_whitespace(' \\t\\n') == ''\n"
        "assert word_count('two\\twords') == 2\n"
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
        candidate_source = (workspace / "src/text_utils.py").read_text(encoding="utf-8")
        original_source = (baseline / "src/text_utils.py").read_text(encoding="utf-8")
        candidate_tests = ast.parse(
            (workspace / "tests/test_text_utils.py").read_text(encoding="utf-8")
        )
        test_names = {
            node.name
            for node in ast.walk(candidate_tests)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        unchanged_helpers = _functions(candidate_source, {"word_count"}) == _functions(
            original_source, {"word_count"}
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
    changes_scoped = bool(changed_files) and set(changed_files) <= {
        "src/text_utils.py",
        "tests/test_text_utils.py",
    }
    required_tests_present = {
        "test_empty_input",
        "test_collapses_mixed_whitespace",
        "test_preserves_unicode_text",
    } <= test_names
    unit_tests_passed = test_run.returncode == 0
    behavioral_probe_passed = probe_run.returncode == 0
    success = all(
        (
            unit_tests_passed,
            behavioral_probe_passed,
            required_tests_present,
            unchanged_helpers,
            changes_scoped,
        )
    )
    return {
        "success": success,
        "unit_tests_passed": unit_tests_passed,
        "behavioral_probe_passed": behavioral_probe_passed,
        "required_tests_present": required_tests_present,
        "unchanged_helpers": unchanged_helpers,
        "changes_scoped": changes_scoped,
        "changed_files": changed_files,
        "test_output": f"{test_run.stdout}{test_run.stderr}",
        "behavioral_probe_stderr": probe_run.stderr,
    }


def _grade_env_parser(workspace: Path, baseline: Path) -> dict[str, Any]:
    workspace = workspace.resolve()
    baseline = baseline.resolve()
    test_run = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
        cwd=workspace,
        capture_output=True,
        text=True,
        timeout=45,
    )
    probe_code = (
        "from src.config_parser import normalize_key, parse_assignment\n"
        "assert parse_assignment('  api_key = a=b  ') == ('api_key', 'a=b')\n"
        "assert parse_assignment('name=\"two words\"') == ('name', 'two words')\n"
        "assert parse_assignment(\"name='two words'\") == ('name', 'two words')\n"
        "assert parse_assignment('  # ignored=x') is None\n"
        "assert parse_assignment(' = empty key') is None\n"
        "assert normalize_key(' api_key ') == 'API_KEY'\n"
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
        candidate_source = (workspace / "src/config_parser.py").read_text(encoding="utf-8")
        original_source = (baseline / "src/config_parser.py").read_text(encoding="utf-8")
        candidate_tests = ast.parse(
            (workspace / "tests/test_config_parser.py").read_text(encoding="utf-8")
        )
        test_names = {
            node.name
            for node in ast.walk(candidate_tests)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        unchanged_helpers = _functions(candidate_source, {"normalize_key"}) == _functions(
            original_source, {"normalize_key"}
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
    changes_scoped = bool(changed_files) and set(changed_files) <= {
        "src/config_parser.py",
        "tests/test_config_parser.py",
    }
    required_tests_present = {
        "test_ignores_blank_and_comment_lines",
        "test_splits_on_first_equals_and_trims",
        "test_strips_matching_quotes",
    } <= test_names
    unit_tests_passed = test_run.returncode == 0
    behavioral_probe_passed = probe_run.returncode == 0
    success = all(
        (
            unit_tests_passed,
            behavioral_probe_passed,
            required_tests_present,
            unchanged_helpers,
            changes_scoped,
        )
    )
    return {
        "success": success,
        "unit_tests_passed": unit_tests_passed,
        "behavioral_probe_passed": behavioral_probe_passed,
        "required_tests_present": required_tests_present,
        "unchanged_helpers": unchanged_helpers,
        "changes_scoped": changes_scoped,
        "changed_files": changed_files,
        "test_output": f"{test_run.stdout}{test_run.stderr}",
        "behavioral_probe_stderr": probe_run.stderr,
    }
