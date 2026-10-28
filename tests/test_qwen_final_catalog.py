import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "results/reports/qwen-optimization-final/artifact-catalog-v2.json"
CONFIG = ROOT / "benchmark/configs/qwen-optimization-final.json"


def test_final_catalog_contains_only_above_four_bit_models_below_7_5_gb():
    data = json.loads(CATALOG.read_text())
    artifacts = data["artifacts"]
    assert len(artifacts) == 10
    for model, names in {
        "4B": {"Q5_K_S", "Q5_K_M", "UD-Q5_K_XL", "Q6_K", "Q8_0"},
        "9B": {"Q4_K_M", "Q5_K_S", "Q5_K_M", "UD-Q5_K_XL", "Q6_K"},
    }.items():
        rows = [row for row in artifacts if row["model_id"] == model]
        assert {row["quantfmt"] for row in rows} == names
        assert len(rows) == len(names)
        assert all(row["repo_id"] == f"unsloth/Qwen3.5-{model}-GGUF" for row in rows)
        assert all(row["engine"] == "llama.cpp" for row in rows)
        assert all(0 < row["total_bytes"] < 7_500_000_000 for row in rows)


def test_final_protocol_is_separate_and_preserves_vram_reserve():
    config = json.loads(CONFIG.read_text())
    assert config["protocol_id"] == "qwen-quant-harness-optimization-final"
    assert config["resource_limits"]["gpu_reserve_mib"] >= 512
    assert config["models"] == ["4B", "9B"]
