from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

try:
    from benchmark.harness_eval import _verify_required_tests, grade_workspace
except ImportError:
    grade_workspace = None  # type: ignore[assignment]
    _verify_required_tests = None  # type: ignore[assignment]


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "benchmark" / "fixtures" / "harness_task"
WHITESPACE_FIXTURE = ROOT / "benchmark" / "fixtures" / "harness_whitespace"
ENV_PARSER_FIXTURE = ROOT / "benchmark" / "fixtures" / "harness_env_parser"
CONFIG_PRECEDENCE_FIXTURE = ROOT / "benchmark" / "fixtures" / "config_precedence_task"
RETRY_POLICY_FIXTURE = ROOT / "benchmark" / "fixtures" / "retry_policy_task"
PACKAGE_REFACTOR_FIXTURE = ROOT / "benchmark" / "fixtures" / "package_refactor_task"


class HarnessEvaluationTests(unittest.TestCase):
    def workspace(self) -> tuple[tempfile.TemporaryDirectory[str], Path]:
        temp = tempfile.TemporaryDirectory()
        target = Path(temp.name) / "workspace"
        shutil.copytree(FIXTURE, target)
        return temp, target

    def implement_divide(self, workspace: Path) -> None:
        (workspace / "src" / "calculator.py").write_text(
            "def add(a: float, b: float) -> float:\n"
            "    return a + b\n\n\n"
            "def multiply(a: float, b: float) -> float:\n"
            "    return a * b\n\n\n"
            "def divide(a: float, b: float) -> float:\n"
            "    if b == 0:\n"
            "        raise ValueError(\"division by zero\")\n"
            "    return a / b\n",
            encoding="utf-8",
        )
        (workspace / "tests" / "test_calculator.py").write_text(
            "import unittest\n\n"
            "from src.calculator import add, multiply, divide\n\n\n"
            "class CalculatorTests(unittest.TestCase):\n"
            "    def test_add(self):\n        self.assertEqual(add(2, 3), 5)\n\n"
            "    def test_multiply(self):\n        self.assertEqual(multiply(2, 3), 6)\n\n"
            "    def test_divide_positive(self):\n        self.assertEqual(divide(10, 2), 5)\n\n"
            "    def test_divide_negative(self):\n        self.assertEqual(divide(-10, 2), -5)\n\n"
            "    def test_divide_by_zero(self):\n"
            "        with self.assertRaisesRegex(ValueError, 'division by zero'):\n"
            "            divide(10, 0)\n",
            encoding="utf-8",
        )

    def test_grade_workspace_is_callable(self) -> None:
        self.assertTrue(callable(grade_workspace), "grade_workspace is not implemented")

    def test_correct_change_passes_tests_and_behavior_probe(self) -> None:
        self.assertTrue(callable(grade_workspace), "grade_workspace is not implemented")
        temp, workspace = self.workspace()
        self.addCleanup(temp.cleanup)
        self.implement_divide(workspace)

        result = grade_workspace(workspace, FIXTURE)

        self.assertTrue(result["unit_tests_passed"])
        self.assertTrue(result["behavioral_probe_passed"])
        self.assertTrue(result["divide_tests_present"])
        self.assertTrue(result["unchanged_helpers"])
        self.assertTrue(result["changes_scoped"])
        self.assertTrue(result["success"])

    def test_unexpected_file_change_fails_scope_check(self) -> None:
        self.assertTrue(callable(grade_workspace), "grade_workspace is not implemented")
        temp, workspace = self.workspace()
        self.addCleanup(temp.cleanup)
        self.implement_divide(workspace)
        (workspace / "unrequested.txt").write_text("outside task\n", encoding="utf-8")

        result = grade_workspace(workspace, FIXTURE)

        self.assertFalse(result["changes_scoped"])
        self.assertFalse(result["success"])

    def implement_normalize_whitespace(self, workspace: Path, canonical_names: bool = True) -> None:
        (workspace / "src" / "text_utils.py").write_text(
            "def word_count(text: str) -> int:\n"
            "    return len(text.split())\n\n\n"
            "def normalize_whitespace(text: str) -> str:\n"
            "    return ' '.join(text.split())\n",
            encoding="utf-8",
        )
        positive_name = "test_collapses_mixed_whitespace" if canonical_names else "test_collapses_spaces"
        negative_name = "test_preserves_unicode_text" if canonical_names else "test_unicode"
        (workspace / "tests" / "test_text_utils.py").write_text(
            "import unittest\n\n"
            "from src.text_utils import normalize_whitespace, word_count\n\n\n"
            "class TextUtilsTests(unittest.TestCase):\n"
            "    def test_word_count(self):\n"
            "        self.assertEqual(word_count('two\\twords'), 2)\n\n"
            "    def test_empty_input(self):\n"
            "        self.assertEqual(normalize_whitespace('  \\t\\n'), '')\n\n"
            f"    def {positive_name}(self):\n"
            "        self.assertEqual(normalize_whitespace('  alpha\\tbeta\\n gamma  '), 'alpha beta gamma')\n\n"
            f"    def {negative_name}(self):\n"
            "        self.assertEqual(normalize_whitespace('\\u00a0café\\u2003x'), 'café x')\n",
            encoding="utf-8",
        )

    def test_whitespace_task_checks_behavior_scope_and_preserved_helper(self) -> None:
        self.assertTrue(callable(grade_workspace), "grade_workspace is not implemented")
        with tempfile.TemporaryDirectory() as temp:
            workspace = Path(temp) / "workspace"
            shutil.copytree(WHITESPACE_FIXTURE, workspace)
            self.implement_normalize_whitespace(workspace)

            result = grade_workspace(workspace, WHITESPACE_FIXTURE, task="whitespace_normalization")

        self.assertTrue(result["unit_tests_passed"])
        self.assertTrue(result["behavioral_probe_passed"])
        self.assertTrue(result["required_tests_present"])
        self.assertTrue(result["unchanged_helpers"])
        self.assertTrue(result["changes_scoped"])
        self.assertTrue(result["success"])

    def test_whitespace_task_rejects_noncanonical_test_names(self) -> None:
        self.assertTrue(callable(grade_workspace), "grade_workspace is not implemented")
        with tempfile.TemporaryDirectory() as temp:
            workspace = Path(temp) / "workspace"
            shutil.copytree(WHITESPACE_FIXTURE, workspace)
            self.implement_normalize_whitespace(workspace, canonical_names=False)

            result = grade_workspace(workspace, WHITESPACE_FIXTURE, task="whitespace_normalization")

        self.assertTrue(result["unit_tests_passed"])
        self.assertTrue(result["behavioral_probe_passed"])
        self.assertFalse(result["required_tests_present"])
        self.assertFalse(result["success"])

    def implement_env_parser(self, workspace: Path, canonical_names: bool = True) -> None:
        (workspace / "src" / "config_parser.py").write_text(
            "def normalize_key(key: str) -> str:\n"
            "    return key.strip().upper()\n\n\n"
            "def parse_assignment(line: str) -> tuple[str, str] | None:\n"
            "    stripped = line.strip()\n"
            "    if not stripped or stripped.startswith('#') or '=' not in stripped:\n"
            "        return None\n"
            "    key, value = stripped.split('=', 1)\n"
            "    key, value = key.strip(), value.strip()\n"
            "    if not key:\n"
            "        return None\n"
            "    if len(value) >= 2 and value[0] == value[-1] and value[0] in '\\\"\\'':\n"
            "        value = value[1:-1]\n"
            "    return key, value\n",
            encoding="utf-8",
        )
        if canonical_names:
            return
        tests = workspace / "tests" / "test_config_parser.py"
        tests.write_text(
            "import unittest\nfrom src.config_parser import parse_assignment\n"
            "class ConfigParserTests(unittest.TestCase):\n"
            "    def test_comments(self): self.assertIsNone(parse_assignment('# x'))\n"
            "    def test_splits(self): self.assertEqual(parse_assignment('a=b'), ('a','b'))\n"
            "    def test_quotes(self): self.assertEqual(parse_assignment('a=\"b\"'), ('a','b'))\n",
            encoding="utf-8",
        )

    def test_env_parser_task_checks_behavior_scope_and_preserved_helper(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            workspace = Path(temp) / "workspace"
            shutil.copytree(ENV_PARSER_FIXTURE, workspace)
            self.implement_env_parser(workspace)

            result = grade_workspace(workspace, ENV_PARSER_FIXTURE, task="dotenv_line_parser")

        self.assertTrue(result["unit_tests_passed"])
        self.assertTrue(result["behavioral_probe_passed"])
        self.assertTrue(result["required_tests_present"])
        self.assertTrue(result["unchanged_helpers"])
        self.assertTrue(result["changes_scoped"])
        self.assertTrue(result["success"])

    def test_env_parser_task_rejects_noncanonical_test_names(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            workspace = Path(temp) / "workspace"
            shutil.copytree(ENV_PARSER_FIXTURE, workspace)
            self.implement_env_parser(workspace, canonical_names=False)

            result = grade_workspace(workspace, ENV_PARSER_FIXTURE, task="dotenv_line_parser")

        self.assertTrue(result["unit_tests_passed"])
        self.assertTrue(result["behavioral_probe_passed"])
        self.assertFalse(result["required_tests_present"])
        self.assertFalse(result["success"])


    def implement_config_precedence(
        self,
        workspace: Path,
        canonical_names: bool = True,
        falsy_bug: bool = False,
        mutate_input: bool = False,
        alter_helper: bool = False,
    ) -> None:
        helper_body = (
            '    """Validate that config is a non-empty dictionary; preserved helper."""\n'
            '    return isinstance(config, dict) and len(config) > 0'
        )
        if alter_helper:
            helper_body = "    return bool(config)"

        loop_file = (
            "        for k, v in file_config.items():\n"
            "            if v:\n"
            "                result[k] = v\n"
        ) if falsy_bug else (
            "        for k, v in file_config.items():\n"
            "            if v is not None:\n"
            "                result[k] = v\n"
        )

        init_res = "    result = defaults\n" if mutate_input else "    result = dict(defaults)\n"

        (workspace / "src" / "config.py").write_text(
            f"def validate_schema(config: dict) -> bool:\n"
            f"{helper_body}\n\n\n"
            f"def resolve_config(defaults: dict, file_config: dict | None = None, cli_args: dict | None = None) -> dict:\n"
            f"{init_res}"
            f"    if file_config:\n{loop_file}"
            f"    if cli_args:\n"
            f"        for k, v in cli_args.items():\n"
            f"            if v is not None:\n"
            f"                result[k] = v\n"
            f"    return result\n",
            encoding="utf-8",
        )
        t_cli = "test_cli_overrides_file_and_defaults" if canonical_names else "test_cli_overrides"
        (workspace / "tests" / "test_config.py").write_text(
            f"import unittest\nfrom src.config import resolve_config, validate_schema\n\n"
            f"class ConfigPrecedenceTests(unittest.TestCase):\n"
            f"    def test_validate_schema_helper(self):\n"
            f"        self.assertTrue(validate_schema({{'a': 1}}))\n\n"
            f"    def {t_cli}(self):\n"
            f"        self.assertEqual(resolve_config({{'a': 1}}, {{'a': 2}}, {{'a': 3}}), {{'a': 3}})\n\n"
            f"    def test_preserves_falsy_values(self):\n"
            f"        self.assertEqual(resolve_config({{'a': 1}}, {{'a': 0}}), {{'a': 0}})\n\n"
            f"    def test_does_not_mutate_inputs(self):\n"
            f"        d = {{'a': 1}}\n"
            f"        resolve_config(d, {{'b': 2}})\n"
            f"        self.assertEqual(d, {{'a': 1}})\n",
            encoding="utf-8",
        )

    def test_config_precedence_unmodified_fixture_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            workspace = Path(temp) / "workspace"
            shutil.copytree(CONFIG_PRECEDENCE_FIXTURE, workspace)
            result = grade_workspace(workspace, CONFIG_PRECEDENCE_FIXTURE, task="config_precedence")
        self.assertFalse(result["success"])
        self.assertFalse(result["unit_tests_passed"])

    def test_config_precedence_reference_passes(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            workspace = Path(temp) / "workspace"
            shutil.copytree(CONFIG_PRECEDENCE_FIXTURE, workspace)
            self.implement_config_precedence(workspace)
            result = grade_workspace(workspace, CONFIG_PRECEDENCE_FIXTURE, task="config_precedence")
        self.assertTrue(result["unit_tests_passed"], f"Unit tests failed: {result['test_output']}")
        self.assertTrue(result["behavioral_probe_passed"], f"Probe failed: {result['behavioral_probe_stderr']}")
        self.assertTrue(result["required_tests_present"])
        self.assertTrue(result["unchanged_helpers"])
        self.assertTrue(result["changes_scoped"])
        self.assertTrue(result["success"])

    def test_config_precedence_mutant_falsy_bug_fails_probe(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            workspace = Path(temp) / "workspace"
            shutil.copytree(CONFIG_PRECEDENCE_FIXTURE, workspace)
            self.implement_config_precedence(workspace, falsy_bug=True)
            result = grade_workspace(workspace, CONFIG_PRECEDENCE_FIXTURE, task="config_precedence")
        self.assertFalse(result["behavioral_probe_passed"])
        self.assertFalse(result["success"])

    def test_config_precedence_mutant_altered_helper_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            workspace = Path(temp) / "workspace"
            shutil.copytree(CONFIG_PRECEDENCE_FIXTURE, workspace)
            self.implement_config_precedence(workspace, alter_helper=True)
            result = grade_workspace(workspace, CONFIG_PRECEDENCE_FIXTURE, task="config_precedence")
        self.assertFalse(result["unchanged_helpers"])
        self.assertFalse(result["success"])

    def implement_retry_policy(
        self,
        workspace: Path,
        canonical_names: bool = True,
        ignore_exc_filter: bool = False,
        alter_helper: bool = False,
    ) -> None:
        helper_body = (
            '    """Calculate exponential backoff delay in seconds; preserved helper."""\n'
            "    if attempt < 1:\n"
            "        return 0.0\n"
            "    return base * (factor ** (attempt - 1))\n"
        )
        if alter_helper:
            helper_body = "    return base * factor\n"

        catch_clause = "except Exception as exc:\n" if ignore_exc_filter else "except retryable_exceptions as exc:\n"

        (workspace / "src" / "retry.py").write_text(
            f"from __future__ import annotations\n\n"
            f"def calculate_backoff(attempt: int, base: float = 1.0, factor: float = 2.0) -> float:\n"
            f"{helper_body}\n\n"
            f"def execute_with_retry(operation, retryable_exceptions, max_attempts=3, on_retry=None):\n"
            f"    if max_attempts <= 0:\n"
            f"        raise ValueError('max_attempts must be >= 1')\n"
            f"    for attempt in range(1, max_attempts + 1):\n"
            f"        try:\n"
            f"            return operation()\n"
            f"        {catch_clause}"
            f"            if attempt == max_attempts:\n"
            f"                raise\n"
            f"            if on_retry is not None:\n"
            f"                on_retry(attempt, exc)\n",
            encoding="utf-8",
        )
        t_first = "test_succeeds_on_first_attempt" if canonical_names else "test_first_try"
        (workspace / "tests" / "test_retry.py").write_text(
            f"import unittest\nfrom src.retry import calculate_backoff, execute_with_retry\n\n"
            f"class RetryPolicyTests(unittest.TestCase):\n"
            f"    def test_calculate_backoff_helper(self):\n"
            f"        self.assertEqual(calculate_backoff(1), 1.0)\n\n"
            f"    def {t_first}(self):\n"
            f"        self.assertEqual(execute_with_retry(lambda: 42, (IOError,)), 42)\n\n"
            f"    def test_retries_transient_and_calls_callback(self):\n"
            f"        calls = []\n"
            f"        def op():\n"
            f"            calls.append(1)\n"
            f"            if len(calls) < 2:\n"
            f"                raise ConnectionError('fail')\n"
            f"            return 'ok'\n"
            f"        cb_calls = []\n"
            f"        res = execute_with_retry(op, (ConnectionError,), on_retry=lambda a, e: cb_calls.append(a))\n"
            f"        self.assertEqual(res, 'ok')\n"
            f"        self.assertEqual(cb_calls, [1])\n\n"
            f"    def test_raises_immediately_on_permanent_error(self):\n"
            f"        with self.assertRaises(KeyError):\n"
            f"            execute_with_retry(lambda: {{}}['x'], (ValueError,))\n\n"
            f"    def test_exhausts_retries_and_reraises(self):\n"
            f"        with self.assertRaises(ValueError):\n"
            f"            execute_with_retry(lambda: int('bad'), (ValueError,), max_attempts=2)\n",
            encoding="utf-8",
        )

    def test_retry_policy_unmodified_fixture_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            workspace = Path(temp) / "workspace"
            shutil.copytree(RETRY_POLICY_FIXTURE, workspace)
            result = grade_workspace(workspace, RETRY_POLICY_FIXTURE, task="retry_policy")
        self.assertFalse(result["success"])
        self.assertFalse(result["unit_tests_passed"])

    def test_retry_policy_reference_passes(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            workspace = Path(temp) / "workspace"
            shutil.copytree(RETRY_POLICY_FIXTURE, workspace)
            self.implement_retry_policy(workspace)
            result = grade_workspace(workspace, RETRY_POLICY_FIXTURE, task="retry_policy")
        self.assertTrue(result["unit_tests_passed"], f"Unit tests failed: {result['test_output']}")
        self.assertTrue(result["behavioral_probe_passed"], f"Probe failed: {result['behavioral_probe_stderr']}")
        self.assertTrue(result["required_tests_present"])
        self.assertTrue(result["unchanged_helpers"])
        self.assertTrue(result["changes_scoped"])
        self.assertTrue(result["success"])

    def test_retry_policy_mutant_catches_all_exceptions_fails_probe(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            workspace = Path(temp) / "workspace"
            shutil.copytree(RETRY_POLICY_FIXTURE, workspace)
            self.implement_retry_policy(workspace, ignore_exc_filter=True)
            result = grade_workspace(workspace, RETRY_POLICY_FIXTURE, task="retry_policy")
        self.assertFalse(result["behavioral_probe_passed"])
        self.assertFalse(result["success"])

    def test_retry_policy_mutant_altered_helper_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            workspace = Path(temp) / "workspace"
            shutil.copytree(RETRY_POLICY_FIXTURE, workspace)
            self.implement_retry_policy(workspace, alter_helper=True)
            result = grade_workspace(workspace, RETRY_POLICY_FIXTURE, task="retry_policy")
        self.assertFalse(result["unchanged_helpers"])
        self.assertFalse(result["success"])

    def implement_package_refactor(
        self,
        workspace: Path,
        canonical_names: bool = True,
        break_reexport: bool = False,
        alter_helper: bool = False,
    ) -> None:
        (workspace / "src" / "metrics.py").write_text(
            "def summarize_metrics(data: list[float]) -> dict[str, float]:\n"
            "    if not data:\n"
            "        return {'count': 0.0, 'mean': 0.0, 'min': 0.0, 'max': 0.0}\n"
            "    return {\n"
            "        'count': float(len(data)),\n"
            "        'mean': float(sum(data) / len(data)),\n"
            "        'min': float(min(data)),\n"
            "        'max': float(max(data)),\n"
            "    }\n",
            encoding="utf-8",
        )
        helper_body = (
            '    """Sanitize input record by stripping string values; preserved helper."""\n'
            "    return {k: v.strip() if isinstance(v, str) else v for k, v in record.items()}\n"
        )
        if alter_helper:
            helper_body = "    return record\n"

        reexport = "" if break_reexport else "from src.metrics import summarize_metrics\n"
        (workspace / "src" / "service.py").write_text(
            f"from __future__ import annotations\n\n"
            f"{reexport}"
            f"def sanitize_record(record: dict) -> dict:\n"
            f"{helper_body}\n\n"
            f"def generate_service_summary(records: list[dict]) -> dict[str, float]:\n"
            f"    from src.metrics import summarize_metrics\n"
            f"    latencies = [\n"
            f"        float(r['latency'])\n"
            f"        for r in records\n"
            f"        if 'latency' in r and r['latency'] is not None and isinstance(r['latency'], (int, float))\n"
            f"    ]\n"
            f"    return summarize_metrics(latencies)\n",
            encoding="utf-8",
        )
        t_summary = "test_summarize_metrics_empty_and_normal" if canonical_names else "test_summary"
        (workspace / "tests" / "test_service.py").write_text(
            f"import unittest\nfrom src.service import generate_service_summary, sanitize_record\n\n"
            f"class ServiceTests(unittest.TestCase):\n"
            f"    def test_sanitize_record_helper(self):\n"
            f"        self.assertEqual(sanitize_record({{'a': ' x '}}), {{'a': 'x'}})\n\n"
            f"    def {t_summary}(self):\n"
            f"        from src.service import summarize_metrics\n"
            f"        self.assertEqual(summarize_metrics([])['count'], 0.0)\n"
            f"        self.assertEqual(summarize_metrics([1.0, 3.0])['mean'], 2.0)\n\n"
            f"    def test_generate_service_summary_filters_missing(self):\n"
            f"        res = generate_service_summary([{{'latency': 5.0}}, {{}}])\n"
            f"        self.assertEqual(res['count'], 1.0)\n\n"
            f"    def test_service_reexports_metrics(self):\n"
            f"        import src.service, src.metrics\n"
            f"        self.assertIs(src.service.summarize_metrics, src.metrics.summarize_metrics)\n",
            encoding="utf-8",
        )

    def test_package_refactor_unmodified_fixture_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            workspace = Path(temp) / "workspace"
            shutil.copytree(PACKAGE_REFACTOR_FIXTURE, workspace)
            result = grade_workspace(workspace, PACKAGE_REFACTOR_FIXTURE, task="package_refactor")
        self.assertFalse(result["success"])
        self.assertFalse(result["unit_tests_passed"])

    def test_package_refactor_reference_passes(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            workspace = Path(temp) / "workspace"
            shutil.copytree(PACKAGE_REFACTOR_FIXTURE, workspace)
            self.implement_package_refactor(workspace)
            result = grade_workspace(workspace, PACKAGE_REFACTOR_FIXTURE, task="package_refactor")
        self.assertTrue(result["unit_tests_passed"], f"Unit tests failed: {result['test_output']}")
        self.assertTrue(result["behavioral_probe_passed"], f"Probe failed: {result['behavioral_probe_stderr']}")
        self.assertTrue(result["required_tests_present"])
        self.assertTrue(result["unchanged_helpers"])
        self.assertTrue(result["changes_scoped"])
        self.assertTrue(result["success"])

    def test_package_refactor_mutant_broken_reexport_fails_probe(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            workspace = Path(temp) / "workspace"
            shutil.copytree(PACKAGE_REFACTOR_FIXTURE, workspace)
            self.implement_package_refactor(workspace, break_reexport=True)
            result = grade_workspace(workspace, PACKAGE_REFACTOR_FIXTURE, task="package_refactor")
        self.assertFalse(result["behavioral_probe_passed"])
        self.assertFalse(result["success"])

    def test_package_refactor_mutant_altered_helper_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            workspace = Path(temp) / "workspace"
            shutil.copytree(PACKAGE_REFACTOR_FIXTURE, workspace)
            self.implement_package_refactor(workspace, alter_helper=True)
            result = grade_workspace(workspace, PACKAGE_REFACTOR_FIXTURE, task="package_refactor")
        self.assertFalse(result["unchanged_helpers"])
        self.assertFalse(result["success"])

    def test_verify_required_tests_semantic_variants(self) -> None:
        self.assertIsNotNone(_verify_required_tests)
        # 1. Canonical recommended names
        canonical = {"test_divide_positive", "test_divide_negative", "test_divide_by_zero"}
        self.assertTrue(_verify_required_tests(canonical))

        # 2. Mistral Vibe variants
        vibe_variants = {
            "test_divide_positive_operands",
            "test_divide_negative_operand",
            "test_divide_by_zero",
        }
        self.assertTrue(_verify_required_tests(vibe_variants))

        # 3. Pi variants
        pi_variants = {
            "test_positive_operands",
            "test_negative_operand",
            "test_division_by_zero",
        }
        self.assertTrue(_verify_required_tests(pi_variants))

        # 4. Incomplete sets
        self.assertFalse(_verify_required_tests({"test_divide_positive", "test_divide_negative"}))
        self.assertFalse(_verify_required_tests({"test_divide_positive", "test_divide_by_zero"}))
        self.assertFalse(_verify_required_tests({"test_divide_negative", "test_divide_by_zero"}))
        self.assertFalse(_verify_required_tests(set()))

    def test_calculator_division_accepts_vibe_and_pi_test_name_variants(self) -> None:
        for variant_names in (
            ("test_divide_positive_operands", "test_divide_negative_operand", "test_divide_by_zero"),
            ("test_positive_operands", "test_negative_operand", "test_division_by_zero"),
        ):
            pos_name, neg_name, zero_name = variant_names
            temp, workspace = self.workspace()
            self.addCleanup(temp.cleanup)
            (workspace / "src" / "calculator.py").write_text(
                "def add(a: float, b: float) -> float:\n"
                "    return a + b\n\n\n"
                "def multiply(a: float, b: float) -> float:\n"
                "    return a * b\n\n\n"
                "def divide(a: float, b: float) -> float:\n"
                "    if b == 0:\n"
                "        raise ValueError(\"division by zero\")\n"
                "    return a / b\n",
                encoding="utf-8",
            )
            (workspace / "tests" / "test_calculator.py").write_text(
                "import unittest\n\n"
                "from src.calculator import add, multiply, divide\n\n\n"
                "class CalculatorTests(unittest.TestCase):\n"
                "    def test_add(self):\n        self.assertEqual(add(2, 3), 5)\n\n"
                "    def test_multiply(self):\n        self.assertEqual(multiply(2, 3), 6)\n\n"
                f"    def {pos_name}(self):\n        self.assertEqual(divide(10, 2), 5)\n\n"
                f"    def {neg_name}(self):\n        self.assertEqual(divide(-10, 2), -5)\n\n"
                f"    def {zero_name}(self):\n"
                "        with self.assertRaisesRegex(ValueError, 'division by zero'):\n"
                "            divide(10, 0)\n",
                encoding="utf-8",
            )
            result = grade_workspace(workspace, FIXTURE)
            self.assertTrue(result["divide_tests_present"], f"Failed for variants: {variant_names}")
            self.assertTrue(result["required_tests_present"])
            self.assertTrue(result["unit_tests_passed"])
            self.assertTrue(result["behavioral_probe_passed"])
            self.assertTrue(result["unchanged_helpers"])
            self.assertTrue(result["changes_scoped"])
            self.assertTrue(result["success"], f"Failed for variants: {variant_names}")


if __name__ == "__main__":
    unittest.main()
