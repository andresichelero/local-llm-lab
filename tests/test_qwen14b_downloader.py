from __future__ import annotations

import importlib.util
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "benchmark" / "download_qwen25_coder14b_gguf.py"
SPEC = importlib.util.spec_from_file_location("download_qwen25_coder14b_gguf", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_hybrid_download_dry_run_preflights_without_creating_model(tmp_path: Path, capsys) -> None:
    MODULE.download(tmp_path, dry_run=True)

    output = capsys.readouterr().out
    assert MODULE.MODEL["revision"] in output
    assert MODULE.MODEL["sha256"] in output
    assert str(MODULE.MODEL["size_bytes"]) in output
    assert not (tmp_path / MODULE.MODEL["filename"]).exists()
    assert not (tmp_path / f"{MODULE.MODEL['filename']}.part").exists()


def test_hybrid_download_refuses_to_overwrite_unverified_model(tmp_path: Path) -> None:
    target = tmp_path / MODULE.MODEL["filename"]
    target.write_bytes(b"existing content")

    try:
        MODULE.download(tmp_path, dry_run=False)
    except RuntimeError as exc:
        assert "Refusing to overwrite unverified" in str(exc)
    else:
        raise AssertionError("unverified existing model should be preserved and rejected")
    assert target.read_bytes() == b"existing content"
