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


def _verify_required_tests(test_names: set[str]) -> bool:
    """Verify that calculator test names satisfy the required test coverage resiliently."""
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
    zero_variants = {
        "test_divide_by_zero",
        "test_division_by_zero",
        "test_divide_zero",
    }

    has_positive = bool(test_names & positive_variants) or any(
        "positive" in name for name in test_names
    )
    has_negative = bool(test_names & negative_variants) or any(
        "negative" in name for name in test_names
    )
    has_zero = bool(test_names & zero_variants) or any(
        "zero" in name for name in test_names
    )
    return has_positive and has_negative and has_zero


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


EVAL_SUITES_DIR = Path(__file__).resolve().parent / "eval_suites"

TASK_SUITE_MAP: dict[str, str] = {
    "calculator_division": "calculator_division",
    "whitespace_normalization": "whitespace_normalization",
    "dotenv_line_parser": "dotenv_line_parser",
    "config_precedence": "config_precedence",
    "config_precedence_task": "config_precedence",
    "retry_policy": "retry_policy",
    "retry_policy_task": "retry_policy",
    "package_refactor": "package_refactor",
    "package_refactor_task": "package_refactor",
}

INLINE_PROBES: dict[str, str] = {
    "calculator_division": (
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
    ),
    "whitespace_normalization": (
        "from src.text_utils import normalize_whitespace, word_count\n"
        "assert normalize_whitespace('  alpha\\tbeta\\n gamma  ') == 'alpha beta gamma'\n"
        "assert normalize_whitespace('\\u00a0café\\u2003x') == 'café x'\n"
        "assert normalize_whitespace(' \\t\\n') == ''\n"
        "assert word_count('two\\twords') == 2\n"
    ),
    "dotenv_line_parser": (
        "from src.config_parser import normalize_key, parse_assignment\n"
        "assert parse_assignment('  api_key = a=b  ') == ('api_key', 'a=b')\n"
        "assert parse_assignment('name=\"two words\"') == ('name', 'two words')\n"
        "assert parse_assignment(\"name='two words'\") == ('name', 'two words')\n"
        "assert parse_assignment('  # ignored=x') is None\n"
        "assert parse_assignment(' = empty key') is None\n"
        "assert normalize_key(' api_key ') == 'API_KEY'\n"
    ),
    "config_precedence": (
        "from src.config import resolve_config, validate_schema\n"
        "assert validate_schema({'k': 'v'}) is True\n"
        "assert validate_schema({}) is False\n"
        "d = {'a': 1, 'b': 2, 'flag': True}\n"
        "f = {'b': 20, 'flag': False, 'empty': ''}\n"
        "c = {'b': 200, 'count': 0}\n"
        "res = resolve_config(d, f, c)\n"
        "assert res == {'a': 1, 'b': 200, 'flag': False, 'empty': '', 'count': 0}\n"
        "assert d == {'a': 1, 'b': 2, 'flag': True}\n"
        "assert f == {'b': 20, 'flag': False, 'empty': ''}\n"
        "assert c == {'b': 200, 'count': 0}\n"
        "assert resolve_config({'x': 10}, None, None) == {'x': 10}\n"
        "assert resolve_config({'x': 10}, {'x': None}, None) == {'x': 10}\n"
    ),
    "retry_policy": (
        "from src.retry import calculate_backoff, execute_with_retry\n"
        "assert calculate_backoff(1) == 1.0\n"
        "assert calculate_backoff(3) == 4.0\n"
        "attempts = 0\n"
        "def op():\n"
        "    global attempts\n"
        "    attempts += 1\n"
        "    if attempts < 2:\n"
        "        raise ConnectionResetError('drop')\n"
        "    return 42\n"
        "log = []\n"
        "def on_retry(att, exc):\n"
        "    log.append((att, type(exc).__name__))\n"
        "res = execute_with_retry(op, (ConnectionResetError,), max_attempts=3, on_retry=on_retry)\n"
        "assert res == 42\n"
        "assert attempts == 2\n"
        "assert log == [(1, 'ConnectionResetError')]\n"
        "unhandled_attempts = 0\n"
        "def unhandled_op():\n"
        "    global unhandled_attempts\n"
        "    unhandled_attempts += 1\n"
        "    raise ZeroDivisionError('boom')\n"
        "try:\n"
        "    execute_with_retry(unhandled_op, (ConnectionResetError,), max_attempts=3)\n"
        "except ZeroDivisionError:\n"
        "    assert unhandled_attempts == 1\n"
        "else:\n"
        "    raise AssertionError('Did not raise ZeroDivisionError')\n"
        "try:\n"
        "    execute_with_retry(lambda: 1, (Exception,), max_attempts=0)\n"
        "except ValueError as e:\n"
        "    assert str(e) == 'max_attempts must be >= 1'\n"
        "else:\n"
        "    raise AssertionError('Did not raise ValueError on max_attempts=0')\n"
    ),
    "package_refactor": (
        "import src.metrics\n"
        "import src.service\n"
        "assert src.service.summarize_metrics is src.metrics.summarize_metrics\n"
        "assert src.metrics.summarize_metrics([]) == {'count': 0.0, 'mean': 0.0, 'min': 0.0, 'max': 0.0}\n"
        "res = src.metrics.summarize_metrics([10.0, 30.0])\n"
        "assert res == {'count': 2.0, 'mean': 20.0, 'min': 10.0, 'max': 30.0}\n"
        "records = [{'latency': 5.0}, {'latency': None}, {'no_latency': 1}, {'latency': 15.0}]\n"
        "summary = src.service.generate_service_summary(records)\n"
        "assert summary == {'count': 2.0, 'mean': 10.0, 'min': 5.0, 'max': 15.0}\n"
        "assert src.service.sanitize_record({' a ': ' b '}) == {' a ': 'b'}\n"
    ),
}


def run_held_out_tests(workspace: Path, task: str) -> tuple[bool, str, str]:
    """Execute isolated held-out test suite or fallback to inline probe."""
    suite_name = TASK_SUITE_MAP.get(task, task)
    probe_path = EVAL_SUITES_DIR / suite_name / "test_probe.py"
    env = os.environ.copy()
    env["PYTHONPATH"] = str(workspace.resolve())

    if probe_path.is_file():
        try:
            probe_run = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "unittest",
                    "discover",
                    "-s",
                    str(probe_path.parent),
                    "-p",
                    probe_path.name,
                    "-v",
                ],
                cwd=workspace.resolve(),
                env=env,
                capture_output=True,
                text=True,
                timeout=30,
            )
            return probe_run.returncode == 0, probe_run.stdout, probe_run.stderr
        except subprocess.TimeoutExpired as exc:
            return False, "", f"Probe execution timed out: {exc}"
        except OSError as exc:
            return False, "", str(exc)

    inline_code = INLINE_PROBES.get(suite_name)
    if inline_code:
        try:
            probe_run = subprocess.run(
                [sys.executable, "-c", inline_code],
                cwd=workspace.resolve(),
                env=env,
                capture_output=True,
                text=True,
                timeout=15,
            )
            return probe_run.returncode == 0, probe_run.stdout, probe_run.stderr
        except subprocess.TimeoutExpired as exc:
            return False, "", f"Inline probe timed out: {exc}"
        except OSError as exc:
            return False, "", str(exc)

    return False, "", f"No evaluation suite or inline probe found for task: {task}"


def run_baseline_tests(workspace: Path, baseline: Path) -> tuple[bool, str]:
    """Execute baseline reference test suite against candidate workspace."""
    baseline_tests_dir = baseline.resolve() / "tests"
    if not baseline_tests_dir.is_dir():
        return True, ""
    env = os.environ.copy()
    env["PYTHONPATH"] = str(workspace.resolve())
    try:
        run = subprocess.run(
            [sys.executable, "-m", "unittest", "discover", "-s", str(baseline_tests_dir), "-v"],
            cwd=workspace.resolve(),
            env=env,
            capture_output=True,
            text=True,
            timeout=45,
        )
        return run.returncode == 0, f"{run.stdout}{run.stderr}"
    except (subprocess.TimeoutExpired, OSError) as exc:
        return False, str(exc)


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
    if task in ("config_precedence", "config_precedence_task"):
        return _grade_config_precedence(workspace, baseline)
    if task in ("retry_policy", "retry_policy_task"):
        return _grade_retry_policy(workspace, baseline)
    if task in ("package_refactor", "package_refactor_task"):
        return _grade_package_refactor(workspace, baseline)
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
    workspace_tests_passed = test_run.returncode == 0
    test_output = f"{test_run.stdout}{test_run.stderr}"

    baseline_tests_passed, baseline_test_output = run_baseline_tests(workspace, baseline)
    if not baseline_tests_passed:
        test_output = f"{test_output}\n--- Baseline Tests ---\n{baseline_test_output}".strip()

    held_out_tests_passed, probe_stdout, probe_stderr = run_held_out_tests(
        workspace, "calculator_division"
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
    divide_tests_present = _verify_required_tests(test_names)
    unit_tests_passed = workspace_tests_passed and baseline_tests_passed
    behavioral_probe_passed = held_out_tests_passed
    behavioral_probe_stderr = "" if behavioral_probe_passed else (probe_stderr or probe_stdout)
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
        "workspace_tests_passed": workspace_tests_passed,
        "baseline_tests_passed": baseline_tests_passed,
        "held_out_tests_passed": held_out_tests_passed,
        "divide_tests_present": divide_tests_present,
        "required_tests_present": divide_tests_present,
        "unchanged_helpers": unchanged_helpers,
        "changes_scoped": changes_scoped,
        "changed_files": changed_files,
        "test_output": test_output,
        "behavioral_probe_stderr": behavioral_probe_stderr,
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
    workspace_tests_passed = test_run.returncode == 0
    test_output = f"{test_run.stdout}{test_run.stderr}"

    baseline_tests_passed, baseline_test_output = run_baseline_tests(workspace, baseline)
    if not baseline_tests_passed:
        test_output = f"{test_output}\n--- Baseline Tests ---\n{baseline_test_output}".strip()

    held_out_tests_passed, probe_stdout, probe_stderr = run_held_out_tests(
        workspace, "whitespace_normalization"
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
    unit_tests_passed = workspace_tests_passed and baseline_tests_passed
    behavioral_probe_passed = held_out_tests_passed
    behavioral_probe_stderr = "" if behavioral_probe_passed else (probe_stderr or probe_stdout)
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
        "workspace_tests_passed": workspace_tests_passed,
        "baseline_tests_passed": baseline_tests_passed,
        "held_out_tests_passed": held_out_tests_passed,
        "required_tests_present": required_tests_present,
        "unchanged_helpers": unchanged_helpers,
        "changes_scoped": changes_scoped,
        "changed_files": changed_files,
        "test_output": test_output,
        "behavioral_probe_stderr": behavioral_probe_stderr,
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
    workspace_tests_passed = test_run.returncode == 0
    test_output = f"{test_run.stdout}{test_run.stderr}"

    baseline_tests_passed, baseline_test_output = run_baseline_tests(workspace, baseline)
    if not baseline_tests_passed:
        test_output = f"{test_output}\n--- Baseline Tests ---\n{baseline_test_output}".strip()

    held_out_tests_passed, probe_stdout, probe_stderr = run_held_out_tests(
        workspace, "dotenv_line_parser"
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
    unit_tests_passed = workspace_tests_passed and baseline_tests_passed
    behavioral_probe_passed = held_out_tests_passed
    behavioral_probe_stderr = "" if behavioral_probe_passed else (probe_stderr or probe_stdout)
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
        "workspace_tests_passed": workspace_tests_passed,
        "baseline_tests_passed": baseline_tests_passed,
        "held_out_tests_passed": held_out_tests_passed,
        "required_tests_present": required_tests_present,
        "unchanged_helpers": unchanged_helpers,
        "changes_scoped": changes_scoped,
        "changed_files": changed_files,
        "test_output": test_output,
        "behavioral_probe_stderr": behavioral_probe_stderr,
    }


def _grade_config_precedence(workspace: Path, baseline: Path) -> dict[str, Any]:
    workspace = workspace.resolve()
    baseline = baseline.resolve()
    test_run = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
        cwd=workspace,
        capture_output=True,
        text=True,
        timeout=45,
    )
    workspace_tests_passed = test_run.returncode == 0
    test_output = f"{test_run.stdout}{test_run.stderr}"

    baseline_tests_passed, baseline_test_output = run_baseline_tests(workspace, baseline)
    if not baseline_tests_passed:
        test_output = f"{test_output}\n--- Baseline Tests ---\n{baseline_test_output}".strip()

    held_out_tests_passed, probe_stdout, probe_stderr = run_held_out_tests(
        workspace, "config_precedence"
    )
    try:
        candidate_source = (workspace / "src/config.py").read_text(encoding="utf-8")
        original_source = (baseline / "src/config.py").read_text(encoding="utf-8")
        candidate_tests = ast.parse(
            (workspace / "tests/test_config.py").read_text(encoding="utf-8")
        )
        test_names = {
            node.name
            for node in ast.walk(candidate_tests)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        unchanged_helpers = _functions(candidate_source, {"validate_schema"}) == _functions(
            original_source, {"validate_schema"}
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
        "src/config.py",
        "tests/test_config.py",
    }
    required_tests_present = {
        "test_cli_overrides_file_and_defaults",
        "test_preserves_falsy_values",
        "test_does_not_mutate_inputs",
    } <= test_names
    unit_tests_passed = workspace_tests_passed and baseline_tests_passed
    behavioral_probe_passed = held_out_tests_passed
    behavioral_probe_stderr = "" if behavioral_probe_passed else (probe_stderr or probe_stdout)
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
        "workspace_tests_passed": workspace_tests_passed,
        "baseline_tests_passed": baseline_tests_passed,
        "held_out_tests_passed": held_out_tests_passed,
        "required_tests_present": required_tests_present,
        "unchanged_helpers": unchanged_helpers,
        "changes_scoped": changes_scoped,
        "changed_files": changed_files,
        "test_output": test_output,
        "behavioral_probe_stderr": behavioral_probe_stderr,
    }


def _grade_retry_policy(workspace: Path, baseline: Path) -> dict[str, Any]:
    workspace = workspace.resolve()
    baseline = baseline.resolve()
    test_run = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
        cwd=workspace,
        capture_output=True,
        text=True,
        timeout=45,
    )
    workspace_tests_passed = test_run.returncode == 0
    test_output = f"{test_run.stdout}{test_run.stderr}"

    baseline_tests_passed, baseline_test_output = run_baseline_tests(workspace, baseline)
    if not baseline_tests_passed:
        test_output = f"{test_output}\n--- Baseline Tests ---\n{baseline_test_output}".strip()

    held_out_tests_passed, probe_stdout, probe_stderr = run_held_out_tests(
        workspace, "retry_policy"
    )
    try:
        candidate_source = (workspace / "src/retry.py").read_text(encoding="utf-8")
        original_source = (baseline / "src/retry.py").read_text(encoding="utf-8")
        candidate_tests = ast.parse(
            (workspace / "tests/test_retry.py").read_text(encoding="utf-8")
        )
        test_names = {
            node.name
            for node in ast.walk(candidate_tests)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        unchanged_helpers = _functions(candidate_source, {"calculate_backoff"}) == _functions(
            original_source, {"calculate_backoff"}
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
        "src/retry.py",
        "tests/test_retry.py",
    }
    required_tests_present = {
        "test_succeeds_on_first_attempt",
        "test_retries_transient_and_calls_callback",
        "test_raises_immediately_on_permanent_error",
        "test_exhausts_retries_and_reraises",
    } <= test_names
    unit_tests_passed = workspace_tests_passed and baseline_tests_passed
    behavioral_probe_passed = held_out_tests_passed
    behavioral_probe_stderr = "" if behavioral_probe_passed else (probe_stderr or probe_stdout)
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
        "workspace_tests_passed": workspace_tests_passed,
        "baseline_tests_passed": baseline_tests_passed,
        "held_out_tests_passed": held_out_tests_passed,
        "required_tests_present": required_tests_present,
        "unchanged_helpers": unchanged_helpers,
        "changes_scoped": changes_scoped,
        "changed_files": changed_files,
        "test_output": test_output,
        "behavioral_probe_stderr": behavioral_probe_stderr,
    }


def _grade_package_refactor(workspace: Path, baseline: Path) -> dict[str, Any]:
    workspace = workspace.resolve()
    baseline = baseline.resolve()
    test_run = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
        cwd=workspace,
        capture_output=True,
        text=True,
        timeout=45,
    )
    workspace_tests_passed = test_run.returncode == 0
    test_output = f"{test_run.stdout}{test_run.stderr}"

    baseline_tests_passed, baseline_test_output = run_baseline_tests(workspace, baseline)
    if not baseline_tests_passed:
        test_output = f"{test_output}\n--- Baseline Tests ---\n{baseline_test_output}".strip()

    held_out_tests_passed, probe_stdout, probe_stderr = run_held_out_tests(
        workspace, "package_refactor"
    )
    try:
        candidate_source = (workspace / "src/service.py").read_text(encoding="utf-8")
        original_source = (baseline / "src/service.py").read_text(encoding="utf-8")
        candidate_tests = ast.parse(
            (workspace / "tests/test_service.py").read_text(encoding="utf-8")
        )
        test_names = {
            node.name
            for node in ast.walk(candidate_tests)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        unchanged_helpers = _functions(candidate_source, {"sanitize_record"}) == _functions(
            original_source, {"sanitize_record"}
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
        "src/service.py",
        "src/metrics.py",
        "tests/test_service.py",
    }
    required_tests_present = {
        "test_summarize_metrics_empty_and_normal",
        "test_generate_service_summary_filters_missing",
        "test_service_reexports_metrics",
    } <= test_names
    unit_tests_passed = workspace_tests_passed and baseline_tests_passed
    behavioral_probe_passed = held_out_tests_passed
    behavioral_probe_stderr = "" if behavioral_probe_passed else (probe_stderr or probe_stdout)
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
        "workspace_tests_passed": workspace_tests_passed,
        "baseline_tests_passed": baseline_tests_passed,
        "held_out_tests_passed": held_out_tests_passed,
        "required_tests_present": required_tests_present,
        "unchanged_helpers": unchanged_helpers,
        "changes_scoped": changes_scoped,
        "changed_files": changed_files,
        "test_output": test_output,
        "behavioral_probe_stderr": behavioral_probe_stderr,
    }
