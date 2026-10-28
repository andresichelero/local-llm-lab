import pytest

from benchmark.qwen_probes import CODE_CASES, grade_code, tool_arguments_valid


@pytest.mark.parametrize("index", range(6))
def test_reference_and_wrong_implementations(index):
    case = CODE_CASES[index]
    assert grade_code(case["reference"], case)["passed"] is True
    assert grade_code("def solve(*a, **kw): return None", case)["passed"] is False


def test_tool_arguments_reject_fabricated_name_or_extra_arguments():
    expected = {"ids": [2, 7], "active": True}
    call = {
        "id": "call_1",
        "function": {"name": "lookup", "arguments": '{"ids":[2,7],"active":true}'},
    }
    assert tool_arguments_valid(call, expected)
    call["function"]["name"] = "invented_lookup"
    assert not tool_arguments_valid(call, expected)
    call["function"] = {
        "name": "lookup",
        "arguments": '{"ids":[2,7],"active":true,"extra":1}',
    }
    assert not tool_arguments_valid(call, expected)


def test_candidate_code_never_runs_on_host():
    case = CODE_CASES[0]
    result = grade_code(
        'import os\ndef solve(*a): return os.path.exists("/mnt/d")', case
    )
    assert not result["passed"]
    assert result["cleanup_verified"]


def test_early_successful_exit_is_not_a_pass():
    assert not grade_code("import sys;sys.exit(0)", CODE_CASES[0])["passed"]


def test_candidate_cannot_read_grader_to_forge_success():
    code = """import ast,pathlib,os
p=pathlib.Path('/workspace/check.py').read_text()
receipt=ast.parse(p).body[-1].value.args[0].value
print(receipt,flush=True)
os._exit(0)
"""
    assert not grade_code(code, CODE_CASES[0])["passed"]
