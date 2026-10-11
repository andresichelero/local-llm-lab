from __future__ import annotations

import os
import subprocess
from pathlib import Path


def test_unsloth_launcher_dry_run_uses_dataset_override(tmp_path):
    repository = Path(__file__).resolve().parents[1]
    script = repository / "scripts" / "24_finetune_unsloth.sh"
    storage = tmp_path / "ssd-root"
    model = tmp_path / "model"
    model.mkdir()
    (model / "model.safetensors").write_text("fixture", encoding="utf-8")
    dataset = tmp_path / "long-context.jsonl"
    dataset.write_text('{"messages": []}\n', encoding="utf-8")
    fake_python = tmp_path / "python"
    fake_python.write_text("#!/usr/bin/env bash\nprintf '%s\\n' \"$@\"\n", encoding="utf-8")
    fake_python.chmod(0o755)
    environment = os.environ | {
        "BENCH_STORAGE_ROOT": str(storage),
        "UNSLOTH_PYTHON_BIN": str(fake_python),
        "TRAINING_MODEL_DIR": str(model),
        "UNSLOTH_DATASET": str(dataset),
        "UNSLOTH_RUN_PREFIX": "pytest-context-fixture",
    }

    completed = subprocess.run(
        ["bash", str(script), "--dry-run"],
        cwd=repository,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert str(dataset) in completed.stdout
    assert "--dataset" in completed.stdout
