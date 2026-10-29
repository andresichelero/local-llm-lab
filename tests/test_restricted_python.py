from __future__ import annotations

import unittest
from pathlib import Path

from benchmark.restricted_python import (
    ExecutionLimitError,
    UnsupportedSyntaxError,
    load_modules,
)


class RestrictedPythonTests(unittest.TestCase):
    def load_one(self, source: str, **limits: int):
        return load_modules({"src.candidate": source}, **limits)["src.candidate"]

    def test_six_reference_shapes_run_in_the_interpreter(self) -> None:
        sources = {
            "src.calculator": """
def add(a: float, b: float) -> float:
    return a + b
def multiply(a: float, b: float) -> float:
    return a * b
def divide(a: float, b: float) -> float:
    if b == 0:
        raise ValueError('division by zero')
    return a / b
""",
            "src.text_utils": """
def word_count(text: str) -> int:
    return len(text.split())
def normalize_whitespace(text: str) -> str:
    return ' '.join(text.split())
""",
            "src.config_parser": """
def normalize_key(key: str) -> str:
    return key.strip().upper()
def parse_assignment(line: str) -> tuple[str, str] | None:
    stripped = line.strip()
    if not stripped or stripped.startswith('#') or '=' not in stripped:
        return None
    key, value = stripped.split('=', 1)
    key, value = key.strip(), value.strip()
    if not key:
        return None
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        value = value[1:-1]
    return key, value
""",
            "src.config": """
def validate_schema(config: dict) -> bool:
    return isinstance(config, dict) and len(config) > 0
def resolve_config(defaults: dict, file_config: dict | None = None, cli_args: dict | None = None) -> dict:
    result = dict(defaults)
    if file_config:
        for k, v in file_config.items():
            if v is not None:
                result[k] = v
    if cli_args:
        for k, v in cli_args.items():
            if v is not None:
                result[k] = v
    return result
""",
            "src.retry": """
from __future__ import annotations
def calculate_backoff(attempt: int, base: float = 1.0, factor: float = 2.0) -> float:
    if attempt < 1:
        return 0.0
    return base * (factor ** (attempt - 1))
def execute_with_retry(operation, retryable_exceptions, max_attempts=3, on_retry=None):
    if max_attempts <= 0:
        raise ValueError('max_attempts must be >= 1')
    for attempt in range(1, max_attempts + 1):
        try:
            return operation()
        except retryable_exceptions as exc:
            if attempt == max_attempts:
                raise
            if on_retry is not None:
                on_retry(attempt, exc)
""",
            "src.metrics": """
def summarize_metrics(data: list[float]) -> dict[str, float]:
    if not data:
        return {'count': 0.0, 'mean': 0.0, 'min': 0.0, 'max': 0.0}
    return {
        'count': float(len(data)),
        'mean': float(sum(data) / len(data)),
        'min': float(min(data)),
        'max': float(max(data)),
    }
""",
            "src.service": """
from __future__ import annotations
from src.metrics import summarize_metrics
def sanitize_record(record: dict) -> dict:
    return {k: v.strip() if isinstance(v, str) else v for k, v in record.items()}
def generate_service_summary(records: list[dict]) -> dict[str, float]:
    from src.metrics import summarize_metrics
    latencies = [
        float(r['latency'])
        for r in records
        if 'latency' in r and r['latency'] is not None and isinstance(r['latency'], (int, float))
    ]
    return summarize_metrics(latencies)
""",
        }
        modules = load_modules(sources)
        self.assertEqual(modules["src.calculator"].divide(12, 3), 4)
        with self.assertRaisesRegex(ValueError, "division by zero"):
            modules["src.calculator"].divide(1, 0)
        self.assertEqual(modules["src.text_utils"].word_count(" a\t b\n"), 2)
        self.assertEqual(modules["src.text_utils"].normalize_whitespace(" a\t b\n"), "a b")
        self.assertEqual(modules["src.config_parser"].parse_assignment(" TOKEN = 'a=b' "), ("TOKEN", "a=b"))
        self.assertEqual(
            modules["src.config"].resolve_config({"x": 1}, {"x": 2}, {"x": 0}),
            {"x": 0},
        )
        self.assertEqual(modules["src.retry"].calculate_backoff(4), 8.0)
        self.assertEqual(modules["src.metrics"].summarize_metrics([10.0, 30.0])["mean"], 20.0)
        self.assertEqual(
            modules["src.service"].generate_service_summary(
                [{"latency": 1}, {"latency": None}, {}, {"latency": "2"}, {"latency": 3.0}]
            )["count"],
            2.0,
        )
        self.assertIs(
            modules["src.service"].summarize_metrics,
            modules["src.metrics"].summarize_metrics,
        )

    def test_actual_fixture_sources_load_without_stripping_module_globals(self) -> None:
        fixture_root = Path(__file__).parents[1] / "benchmark" / "fixtures"
        sources: dict[str, str] = {}
        for path in sorted(fixture_root.glob("*/src/*.py")):
            module_name = f"src.{path.stem}"
            self.assertNotIn(module_name, sources, f"duplicate fixture module {module_name}")
            sources[module_name] = path.read_text(encoding="utf-8")

        modules = load_modules(sources)
        self.assertEqual(modules["src.retry"].calculate_backoff(4), 8.0)
        self.assertEqual(modules["src.calculator"].add(2, 3), 5)
        self.assertEqual(modules["src.text_utils"].word_count(" a  b "), 2)

    def test_mutable_arguments_keep_the_original_identity(self) -> None:
        module = self.load_one(
            "def mutate(values, mapping):\n"
            "    values.append('seen')\n"
            "    mapping.update({'seen': True})\n"
            "    return values, mapping\n"
        )
        values = [1]
        mapping = {"x": 1}
        result_values, result_mapping = module.mutate(values, mapping)
        self.assertIs(result_values, values)
        self.assertIs(result_mapping, mapping)
        self.assertEqual(values, [1, "seen"])
        self.assertEqual(mapping, {"x": 1, "seen": True})

    def test_callbacks_and_exception_identity_are_preserved(self) -> None:
        module = self.load_one(
            "def execute(operation, retryable_exceptions, max_attempts=3, on_retry=None):\n"
            "    for attempt in range(1, max_attempts + 1):\n"
            "        try:\n"
            "            return operation()\n"
            "        except retryable_exceptions as exc:\n"
            "            if attempt == max_attempts:\n"
            "                raise\n"
            "            if on_retry is not None:\n"
            "                on_retry(attempt, exc)\n"
        )
        error = TimeoutError("later")
        calls: list[int] = []
        seen: list[tuple[int, BaseException]] = []

        def operation():
            calls.append(1)
            if len(calls) == 1:
                raise error
            return "done"

        def on_retry(attempt: int, caught: BaseException) -> None:
            seen.append((attempt, caught))

        result = module.execute(operation, (TimeoutError,), on_retry=on_retry)
        self.assertEqual(result, "done")
        self.assertEqual(len(calls), 2)
        self.assertEqual(seen[0][0], 1)
        self.assertIs(seen[0][1], error)

    def test_unmatched_callback_exception_is_reraised_by_identity(self) -> None:
        module = self.load_one(
            "def execute(operation, retryable_exceptions):\n"
            "    try:\n"
            "        return operation()\n"
            "    except retryable_exceptions:\n"
            "        return 'caught'\n"
        )
        error = LookupError("permanent")

        def operation():
            raise error

        with self.assertRaises(LookupError) as caught:
            module.execute(operation, (TimeoutError,))
        self.assertIs(caught.exception, error)

    def test_candidate_cannot_patch_unittest_or_import_native_modules(self) -> None:
        attacks = (
            "import unittest\nfrom unittest.mock import patch\n"
            "patch('unittest.TestCase.assertEqual', lambda *a: None)\n"
            "def run(): return 1\n",
            "import os\ndef run(): return os.system('true')\n",
            "import re\ndef run(): return 1\n",
        )
        for source in attacks:
            with self.subTest(source=source[:24]):
                with self.assertRaises(UnsupportedSyntaxError):
                    self.load_one(source)

    def test_reflection_and_dynamic_call_escapes_fail_closed(self) -> None:
        attacks = (
            "def run(callback): return callback.__globals__\n",
            "def run(value): return value.__class__.__mro__\n",
            "def run(value): return getattr(value, '__class__')\n",
            "def run(source): return __import__('builtins').eval(source)\n",
            "def run(callback): return callback.__closure__\n",
            "def run(value): return value.format('{0.__class__}', value)\n",
        )
        for source in attacks:
            with self.subTest(source=source):
                with self.assertRaises(UnsupportedSyntaxError):
                    module = self.load_one(source)
                    if "format(" in source:
                        module.run("x")

    def test_loops_and_large_allocations_are_bounded(self) -> None:
        loop = self.load_one("def run():\n    while True:\n        pass\n", step_limit=40)
        with self.assertRaises(ExecutionLimitError):
            loop.run()

        for expression in (
            "'x' * 1000000000",
            "[0] * 1000000000",
            "2 ** 1000000000",
            "1 << 1000000000",
            "list(range(1000000000))",
        ):
            with self.subTest(expression=expression):
                module = self.load_one(f"def run(): return {expression}\n")
                with self.assertRaises(ExecutionLimitError):
                    module.run()

    def test_invalid_numeric_conversions_in_loops_consume_work_budget(self) -> None:
        module = self.load_one(
            "def count_int_failures(values):\n"
            "    failures = 0\n"
            "    for value in values:\n"
            "        try: int(value)\n"
            "        except ValueError: failures += 1\n"
            "    return failures\n"
            "def count_float_failures(values):\n"
            "    failures = 0\n"
            "    for value in values:\n"
            "        try: float(value)\n"
            "        except ValueError: failures += 1\n"
            "    return failures\n",
            step_limit=250,
        )
        invalid_values = ["x" * 100] * 4
        for conversion in (module.count_int_failures, module.count_float_failures):
            with self.subTest(conversion=conversion.name), self.assertRaises(ExecutionLimitError):
                conversion(invalid_values)

    def test_parser_rejects_unbounded_ast_and_unsupported_callable_shapes(self) -> None:
        with self.assertRaises(ExecutionLimitError):
            self.load_one("def f():\n    return [" + ",".join("0" for _ in range(22_000)) + "]\n")
        oversized = self.load_one("def f():\n    return [" + ",".join("0" for _ in range(10_001)) + "]\n")
        with self.assertRaises(ExecutionLimitError):
            oversized.f()
        for source in (
            "class Candidate:\n    pass\n",
            "def run(): return (lambda: 1)()\n",
            "@staticmethod\ndef run(): return 1\n",
            "def run(*args): return 1\n",
        ):
            with self.subTest(source=source):
                with self.assertRaises(UnsupportedSyntaxError):
                    self.load_one(source)

    def test_trusted_callback_is_opaque_and_not_representable(self) -> None:
        module = self.load_one("def reveal(callback): return repr(callback)\n")
        with self.assertRaises(TypeError):
            module.reveal(lambda: None)

    def test_numeric_equality_matches_python_for_mixed_numeric_types(self) -> None:
        module = self.load_one(
            "def divide(a, b):\n"
            "    if b == 0:\n"
            "        raise ValueError('division by zero')\n"
            "    return a / b\n"
            "def same(): return 1 == True\n"
            "def ordered(): return 1 < 1.5 and 2.0 >= True\n"
        )
        with self.assertRaisesRegex(ValueError, "division by zero"):
            module.divide(1, 0.0)
        self.assertTrue(module.same())
        self.assertTrue(module.ordered())

    def test_invalid_control_flow_and_misplaced_future_imports_are_rejected(self) -> None:
        for source in (
            "return 1\n",
            "break\n",
            "continue\n",
            "def f():\n    break\n",
            "def f():\n    continue\n",
            "value = 1\nfrom __future__ import annotations\n",
            "if True:\n    from __future__ import annotations\n",
        ):
            with self.subTest(source=source), self.assertRaises(UnsupportedSyntaxError):
                self.load_one(source)

        module = self.load_one(
            "def sum_until(value):\n"
            "    total = 0\n"
            "    for item in range(value):\n"
            "        if item == 3: break\n"
            "        total += item\n"
            "    return total\n"
        )
        self.assertEqual(module.sum_until(8), 3)

    def test_cumulative_allocations_and_native_ordering_are_bounded(self) -> None:
        module = self.load_one(
            "def allocate(count):\n"
            "    return ['x' * 80000 for _ in range(count)]\n"
            "def smallest(values): return min(values)\n"
        )
        with self.assertRaisesRegex(ExecutionLimitError, "allocation budget"):
            module.allocate(100)
        self.assertEqual(module.allocate(1), ["x" * 80000])
        with self.assertRaisesRegex(TypeError, "scalar values"):
            module.smallest([[0], [1]])

    def test_exception_messages_are_bounded_and_keep_normal_scalar_text(self) -> None:
        module = self.load_one(
            "def message(): return str(ValueError('bad input'))\n"
            "def nested(): raise ValueError([1, 2, 3])\n"
        )
        self.assertEqual(module.message(), "bad input")
        with self.assertRaisesRegex(TypeError, "scalar arguments"):
            module.nested()

    def test_signature_forms_outside_the_subset_are_rejected(self) -> None:
        for source in (
            "def positional_only(value, /): return value\n",
            "def keyword_only(*, value): return value\n",
        ):
            with self.subTest(source=source), self.assertRaises(UnsupportedSyntaxError):
                self.load_one(source)

    def test_expanded_alias_graphs_are_rejected_at_trusted_boundaries(self) -> None:
        module = self.load_one(
            "def build():\n"
            "    value = ['x']\n"
            "    for _ in range(30):\n"
            "        value = [value, value]\n"
            "    return value\n"
            "def mutate(value):\n"
            "    nested = ['x']\n"
            "    for _ in range(30):\n"
            "        nested = [nested, nested]\n"
            "    value.append(nested)\n"
            "def invoke(callback):\n"
            "    nested = ['x']\n"
            "    for _ in range(30):\n"
            "        nested = [nested, nested]\n"
            "    callback(nested)\n"
            "def callback_mutate(callback, value): return callback(value)\n"
        )
        with self.assertRaisesRegex(ExecutionLimitError, "expanded value"):
            module.build()

        original: list[object] = []
        with self.assertRaisesRegex(ExecutionLimitError, "expanded value"):
            module.mutate(original)
        self.assertEqual(len(original), 1)

        error_path: list[object] = []
        def mutate_then_raise(value):
            nested: object = "x"
            for _ in range(30):
                nested = [nested, nested]
            value.append(nested)
            raise LookupError("callback failed")

        with self.assertRaisesRegex(ExecutionLimitError, "expanded value"):
            module.callback_mutate(mutate_then_raise, error_path)
        self.assertEqual(len(error_path), 1)

        callback_calls: list[int] = []
        with self.assertRaisesRegex(ExecutionLimitError, "expanded value"):
            module.invoke(lambda value: callback_calls.append(1))
        self.assertEqual(callback_calls, [])


if __name__ == "__main__":
    unittest.main()
