import pytest

from benchmark import quality_smoke


def test_quality_smoke_records_runtime_configuration_from_environment(monkeypatch):
    monkeypatch.setenv("LAB_CONTEXT_TOKENS", "2048")
    monkeypatch.setenv("LAB_GPU_LAYERS", "32")
    monkeypatch.setenv("LAB_KV_CACHE_K", "q8_0")
    monkeypatch.setenv("LAB_KV_CACHE_V", "q8_0")

    item = quality_smoke.record("structured_json", "qwen-coder-14b", 1.2, True)

    assert item["context_tokens"] == 2048
    assert item["gpu_layers"] == 32
    assert item["kv_cache_k"] == "q8_0"
    assert item["kv_cache_v"] == "q8_0"


def test_missing_tool_call_error_preserves_model_response():
    with pytest.raises(RuntimeError, match='finish_reason.*stop'):
        quality_smoke.get_required_tool_call({"content": "I cannot call tools", "tool_calls": [], "finish_reason": "stop"})


def test_strict_json_validator_accepts_exact_bool_and_int_values():
    assert quality_smoke.is_valid_strict_json_response({"ok": True, "count": 3})


@pytest.mark.parametrize("parsed", [
    {"ok": 1, "count": 3},
    {"ok": True, "count": 3.0},
    {"ok": "true", "count": 3},
    {"ok": None, "count": 3},
    {"ok": True, "count": "3"},
    {"ok": True, "count": None},
    {"ok": True, "count": 3, "extra": False},
])
def test_strict_json_validator_rejects_wrong_types_and_keys(parsed):
    assert not quality_smoke.is_valid_strict_json_response(parsed)


def test_multiple_tool_calls_are_rejected_as_not_one_round_trip():
    add_call = {"id": "call_1", "function": {"name": "add"}}
    second_call = {"id": "call_2", "function": {"name": "add"}}
    assert quality_smoke.get_required_tool_call({"tool_calls": [add_call]}) is add_call
    with pytest.raises(RuntimeError, match="exactly one"):
        quality_smoke.get_required_tool_call({"content": None,
                                               "tool_calls": [add_call, second_call],
                                               "finish_reason": "tool_calls"})


def test_tool_call_requires_valid_id_and_function_dict():
    with pytest.raises(RuntimeError, match="exactly one"):
        quality_smoke.get_required_tool_call({"tool_calls": [{"function": {"name": "add"}}]})
    with pytest.raises(RuntimeError, match="exactly one"):
        quality_smoke.get_required_tool_call({"tool_calls": [{"id": "", "function": {"name": "add"}}]})
    with pytest.raises(RuntimeError, match="exactly one"):
        quality_smoke.get_required_tool_call({"tool_calls": [{"id": "call_1", "function": None}]})


def test_validate_add_arguments_accepts_exact_19_and_23():
    assert quality_smoke.validate_add_arguments({"a": 19, "b": 23})


@pytest.mark.parametrize("adversarial_args", [
    {"a": 20, "b": 22},          # sum is 42, but wrong values!
    {"a": True, "b": 41},        # boolean as int
    {"a": 19.0, "b": 23.0},      # float
    {"a": 19, "b": 23, "extra": 1}, # extra keys
    {"a": 19},                   # missing b
    {"b": 23},                   # missing a
    {"a": "19", "b": "23"},      # string
    None,                        # None
    [19, 23],                    # list
    "a=19, b=23",                # string
])
def test_validate_add_arguments_rejects_adversarial_inputs(adversarial_args):
    assert not quality_smoke.validate_add_arguments(adversarial_args)


def test_validate_add_final_accepts_exact_json_result():
    assert quality_smoke.validate_add_final('{"result": 42}')
    assert quality_smoke.validate_add_final('{\n  "result": 42\n}')


@pytest.mark.parametrize("adversarial_final", [
    'The result of adding 19 and 23 is 42.',  # free text
    'The answer is not 42',                  # free text with negation
    '{"result": 42, "extra": 1}',            # extra keys
    '{"result": "42"}',                      # string value
    '{"result": 42.0}',                      # float value
    '{"result": true}',                      # bool value
    '{"result": 41}',                        # wrong answer
    '{"answer": 42}',                        # wrong key
    '{"result": 42} and more text',          # trailing text outside JSON
    '',                                      # empty string
    None,                                    # None
])
def test_validate_add_final_rejects_adversarial_inputs(adversarial_final):
    assert not quality_smoke.validate_add_final(adversarial_final)
