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
