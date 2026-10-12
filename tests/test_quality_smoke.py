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
