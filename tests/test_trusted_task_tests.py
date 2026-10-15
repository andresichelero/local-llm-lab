from __future__ import annotations

import ast
import shutil
import tempfile
import unittest
from pathlib import Path

from benchmark.harness_eval import grade_workspace
from benchmark.pristine_grading import REPO_ROOT, TASK_POLICIES


IMPLEMENTATIONS = {
    "calculator_division": {
        "src/calculator.py": """
def divide(a, b):
    if b == 0:
        raise ValueError('division by zero')
    return a / b
""",
    },
    "whitespace_normalization": {
        "src/text_utils.py": """
def normalize_whitespace(text):
    return ' '.join(text.split())
""",
    },
    "dotenv_line_parser": {
        "src/config_parser.py": """
def parse_assignment(line):
    text = line.strip()
    if not text or text.startswith('#') or '=' not in text:
        return None
    key, value = text.split('=', 1)
    key = key.strip()
    value = value.strip()
    if not key:
        return None
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
        value = value[1:-1]
    return key, value
""",
    },
    "config_precedence": {
        "src/config.py": """
def resolve_config(defaults, file_config=None, cli_args=None):
    resolved = {}
    for layer in (defaults, file_config, cli_args):
        if layer is not None:
            for key, value in layer.items():
                if value is not None:
                    resolved[key] = value
    return resolved
""",
    },
    "retry_policy": {
        "src/retry.py": """
def execute_with_retry(operation, retryable_exceptions, max_attempts=3, on_retry=None):
    if max_attempts < 1:
        raise ValueError('max_attempts must be >= 1')
    for attempt in range(1, max_attempts + 1):
        try:
            return operation()
        except retryable_exceptions as error:
            if attempt == max_attempts:
                raise
            if on_retry is not None:
                on_retry(attempt, error)
""",
    },
    "package_refactor": {
        "src/metrics.py": """
def summarize_metrics(data):
    if not data:
        return {'count': 0.0, 'mean': 0.0, 'min': 0.0, 'max': 0.0}
    return {
        'count': float(len(data)),
        'mean': float(sum(data) / len(data)),
        'min': float(min(data)),
        'max': float(max(data)),
    }
""",
        "src/service.py": """
from src.metrics import summarize_metrics

def generate_service_summary(records):
    latencies = []
    for record in records:
        if 'latency' in record and record['latency'] is not None:
            latencies.append(record['latency'])
    return summarize_metrics(latencies)
""",
    },
}


NOOPS = {
    "calculator_division": {"src/calculator.py": "def divide(a, b): return 0.0\n"},
    "whitespace_normalization": {"src/text_utils.py": "def normalize_whitespace(text): return text\n"},
    "dotenv_line_parser": {"src/config_parser.py": "def parse_assignment(line): return None\n"},
    "config_precedence": {"src/config.py": "def resolve_config(defaults, file_config=None, cli_args=None): return defaults\n"},
    "retry_policy": {
        "src/retry.py": """
def execute_with_retry(operation, retryable_exceptions, max_attempts=3, on_retry=None):
    return operation()
"""
    },
    "package_refactor": {
        "src/metrics.py": """
def summarize_metrics(data):
    return {'count': 0.0, 'mean': 0.0, 'min': 0.0, 'max': 0.0}
""",
        "src/service.py": """
from src.metrics import summarize_metrics
def generate_service_summary(records):
    return summarize_metrics([])
""",
    },
}


MUTANTS = {
    "calculator_division": {"src/calculator.py": "def divide(a, b): return a // b\n"},
    "whitespace_normalization": {"src/text_utils.py": "def normalize_whitespace(text): return text.strip()\n"},
    "dotenv_line_parser": {
        "src/config_parser.py": """
def parse_assignment(line):
    text = line.strip()
    if not text or text.startswith('#') or '=' not in text:
        return None
    key, value = text.split('=', 1)
    key = key.strip()
    if not key:
        return None
    return key, value.strip()
"""
    },
    "config_precedence": {
        "src/config.py": """
def resolve_config(defaults, file_config=None, cli_args=None):
    resolved = {}
    for layer in (defaults, file_config, cli_args):
        if layer is not None:
            for key, value in layer.items():
                if value:
                    resolved[key] = value
    return resolved
"""
    },
    "retry_policy": {
        "src/retry.py": """
def execute_with_retry(operation, retryable_exceptions, max_attempts=3, on_retry=None):
    if max_attempts < 1:
        raise ValueError('max_attempts must be >= 1')
    for attempt in range(1, max_attempts + 1):
        try:
            return operation()
        except retryable_exceptions:
            if attempt == max_attempts:
                raise
"""
    },
    "package_refactor": {
        "src/metrics.py": IMPLEMENTATIONS["package_refactor"]["src/metrics.py"],
        "src/service.py": """
from src.metrics import summarize_metrics
def generate_service_summary(records):
    latencies = []
    for record in records:
        latencies.append(record['latency'])
    return summarize_metrics(latencies)
""",
    },
}


def _merge_candidate_module(fixture_source: str, candidate_source: str) -> str:
    """Keep the real fixture module imports/signatures and replace only bodies."""
    original = ast.parse(fixture_source)
    candidate = ast.parse(candidate_source)
    original_functions = {
        node.name: node
        for node in original.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    additions: list[ast.stmt] = []
    for node in candidate.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            if not any(ast.dump(node, include_attributes=False) == ast.dump(existing, include_attributes=False)
                       for existing in original.body if isinstance(existing, (ast.Import, ast.ImportFrom))):
                additions.append(node)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            prior = original_functions.get(node.name)
            if prior is None:
                additions.append(node)
            else:
                docstring = (
                    prior.body[0]
                    if prior.body and isinstance(prior.body[0], ast.Expr)
                    and isinstance(prior.body[0].value, ast.Constant)
                    and isinstance(prior.body[0].value.value, str)
                    else None
                )
                prior.body = ([docstring] if docstring is not None else []) + node.body
                prior.type_comment = node.type_comment or prior.type_comment
    if additions:
        insert_at = next(
            (index for index, node in enumerate(original.body)
             if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))),
            len(original.body),
        )
        original.body[insert_at:insert_at] = additions
    ast.fix_missing_locations(original)
    return ast.unparse(original) + "\n"


def _candidate_test_source(task: str) -> str:
    names = [group[0] for group in TASK_POLICIES[task]["required_test_groups"]]
    return "class CandidateTests:\n" + "".join(f"    def {name}(self): pass\n" for name in names)


def _prepare_grade_workspace(task: str, implementation: dict[str, str], workspace: Path) -> None:
    policy = TASK_POLICIES[task]
    fixture = REPO_ROOT / policy["fixture"]
    shutil.copytree(fixture, workspace)
    for relative, candidate_source in implementation.items():
        target = workspace / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.is_file():
            original = target.read_text(encoding="utf-8")
            merged = _merge_candidate_module(original, candidate_source)
        else:
            merged = candidate_source
        target.write_text(merged, encoding="utf-8")
    for relative in policy["test_files"]:
        (workspace / relative).write_text(_candidate_test_source(task), encoding="utf-8")


def _grade_case(task: str, implementation: dict[str, str]) -> dict[str, object]:
    policy = TASK_POLICIES[task]
    fixture = REPO_ROOT / policy["fixture"]
    with tempfile.TemporaryDirectory() as temporary:
        workspace = Path(temporary) / "workspace"
        _prepare_grade_workspace(task, implementation, workspace)
        return grade_workspace(workspace, fixture, task)


class TrustedTaskEvaluationTests(unittest.TestCase):
    def test_all_six_reference_implementations_pass_the_trusted_fixture_and_probe(self) -> None:
        for task, implementation in IMPLEMENTATIONS.items():
            with self.subTest(task=task):
                result = _grade_case(task, implementation)
                self.assertTrue(result["regression_pass"], result)
                self.assertTrue(result["functional_pass"], result)
                self.assertTrue(result["runtime_result_authenticated"], result)
                self.assertEqual(result["candidate_language_contract"], "restricted-python-workspace-v2")
                self.assertFalse(result["candidate_tests_executed"], result)
                self.assertFalse(result["private_holdout"], result)
                self.assertFalse(result["aggregate_is_security_proof"], result)
                self.assertTrue(result["success"], result)

    def test_all_six_noop_implementations_fail_the_trusted_checks(self) -> None:
        for task, implementation in NOOPS.items():
            with self.subTest(task=task):
                result = _grade_case(task, implementation)
                self.assertFalse(result["success"], result)
                self.assertFalse(result["functional_pass"], result)
                self.assertTrue(result["runtime_result_authenticated"], result)

    def test_all_six_behavioral_mutants_fail_the_trusted_checks(self) -> None:
        for task, implementation in MUTANTS.items():
            with self.subTest(task=task):
                result = _grade_case(task, implementation)
                self.assertFalse(result["success"], result)
                self.assertFalse(result["functional_pass"], result)
                self.assertTrue(result["runtime_result_authenticated"], result)

    def test_real_input_mutation_is_detected_by_the_fingerprinted_fixture(self) -> None:
        mutating = {
            "src/config.py": """
def resolve_config(defaults, file_config=None, cli_args=None):
    if file_config is not None:
        defaults.update(file_config)
    if cli_args is not None:
        defaults.update(cli_args)
    return defaults
"""
        }
        result = _grade_case("config_precedence", mutating)
        self.assertFalse(result["regression_pass"], result)
        self.assertTrue(result["runtime_result_authenticated"], result)
        self.assertIn("test_does_not_mutate_inputs", result["test_output"])

    def test_trusted_retry_tests_observe_actual_callback_invocations(self) -> None:
        result = _grade_case("retry_policy", IMPLEMENTATIONS["retry_policy"])
        self.assertTrue(result["regression_pass"], result)
        self.assertTrue(result["functional_pass"], result)
        self.assertTrue(result["runtime_result_authenticated"], result)

    def test_package_refactor_probe_observes_imported_function_identity(self) -> None:
        result = _grade_case("package_refactor", IMPLEMENTATIONS["package_refactor"])
        self.assertTrue(result["functional_pass"], result)
        self.assertTrue(result["runtime_result_authenticated"], result)

    def test_equivalent_but_distinct_metric_function_fails_reexport_identity(self) -> None:
        distinct_copy = {
            "src/metrics.py": IMPLEMENTATIONS["package_refactor"]["src/metrics.py"],
            "src/service.py": """
from src.metrics import summarize_metrics

def summarize_metrics(data):
    if not data:
        return {'count': 0.0, 'mean': 0.0, 'min': 0.0, 'max': 0.0}
    return {
        'count': float(len(data)),
        'mean': float(sum(data) / len(data)),
        'min': float(min(data)),
        'max': float(max(data)),
    }

def generate_service_summary(records):
    latencies = []
    for record in records:
        if 'latency' in record and record['latency'] is not None:
            latencies.append(record['latency'])
    return summarize_metrics(latencies)
""",
        }
        result = _grade_case("package_refactor", distinct_copy)
        self.assertFalse(result["success"], result)
        self.assertFalse(result["regression_pass"], result)
        self.assertFalse(result["functional_pass"], result)
        self.assertTrue(result["runtime_result_authenticated"], result)


if __name__ == "__main__":
    unittest.main()
