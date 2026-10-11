import json

import pytest

from benchmark.qlora_quality import load_tasks, run_generated_code, strip_code_fence


TASK = {
    "function": "difference_of_cubes",
    "arguments": ["a", "b"],
    "tests": [
        {"inputs": [3, 2], "expected": 19},
        {"inputs": [2, 3], "expected": -19},
    ],
}


def test_valid_function_passes_multiple_held_out_cases():
    passed, count, error = run_generated_code(
        "def difference_of_cubes(a, b):\n    return a ** 3 - b ** 3", TASK
    )
    assert (passed, count, error) == (True, 2, None)


def test_function_with_wrong_behavior_fails_exact_cases():
    passed, count, error = run_generated_code(
        "def difference_of_cubes(a, b):\n    return a ** 3 + b ** 3", TASK
    )
    assert passed is False
    assert count == 0
    assert error is None


@pytest.mark.parametrize("source", [
    "import os\ndef difference_of_cubes(a, b):\n    return a - b",
    "def difference_of_cubes(a, b):\n    return __import__('os').system('true')",
    "def difference_of_cubes(a, b):\n    return a.real - b",
])
def test_rejects_imports_calls_and_attribute_access(source):
    passed, count, error = run_generated_code(source, TASK)
    assert passed is False
    assert count == 0
    assert error and ("unsupported syntax" in error or "output must" in error)


def test_rejects_signature_mismatch():
    passed, count, error = run_generated_code(
        "def difference_of_cubes(a):\n    return a ** 3", TASK
    )
    assert passed is False
    assert count == 0
    assert error == "function arguments do not match the task signature"


def test_strips_only_closed_code_fences():
    assert strip_code_fence("```python\nreturn 1\n```") == "return 1"
    assert strip_code_fence("```python\nreturn 1") == "```python\nreturn 1"


def test_loads_jsonl_tasks_and_rejects_empty_dataset(tmp_path):
    path = tmp_path / "tasks.jsonl"
    path.write_text(json.dumps({"task_id": "one", **TASK, "prompt": "do task", "tests": TASK["tests"]}) + "\n", encoding="utf-8")
    assert load_tasks(path)[0]["task_id"] == "one"
    path.write_text("\n", encoding="utf-8")
    with pytest.raises(ValueError, match="empty"):
        load_tasks(path)


def test_quality_fixture_has_disjoint_task_ids_and_nonempty_cases():
    from pathlib import Path

    fixture = Path(__file__).parents[1] / "benchmark/data/qlora-quality-heldout.jsonl"
    tasks = load_tasks(fixture)
    assert len(tasks) == 5
    assert len({task["task_id"] for task in tasks}) == len(tasks)
    assert all(task["tests"] for task in tasks)
