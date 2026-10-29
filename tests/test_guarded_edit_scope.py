"""Regression tests for guarded-edit workspace containment and atomic writes."""
from __future__ import annotations

from pathlib import Path
import stat
import subprocess
import sys

import pytest

from benchmark import guarded_edit
from benchmark.guarded_edit import apply_guarded_edit, main


def _edit(path: Path, *, workspace_root: Path | None = None):
    options = {"workspace_root": workspace_root} if workspace_root is not None else {}
    return apply_guarded_edit(
        path,
        expected_sha256=None,
        search_block="value = 1\n",
        replacement_block="value = 2\n",
        **options,
    )


def test_absolute_external_target_is_rejected_before_edit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = tmp_path / "outside.py"
    original = b"value = 1\n"
    target.write_bytes(original)
    monkeypatch.chdir(workspace)

    result = _edit(target)

    assert not result.success
    assert target.read_bytes() == original


def test_parent_traversal_target_is_rejected_before_edit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = tmp_path / "outside.py"
    original = b"value = 1\n"
    target.write_bytes(original)
    monkeypatch.chdir(workspace)

    result = _edit(Path("..") / target.name)

    assert not result.success
    assert target.read_bytes() == original


def test_parent_directory_symlink_is_rejected_before_edit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "workspace"
    external = tmp_path / "external"
    workspace.mkdir()
    external.mkdir()
    target = external / "outside.py"
    original = b"value = 1\n"
    target.write_bytes(original)
    try:
        (workspace / "linked").symlink_to(external, target_is_directory=True)
    except OSError:
        pytest.skip("Directory symlinks are not supported in this environment")
    monkeypatch.chdir(workspace)

    result = _edit(Path("linked") / target.name)

    assert not result.success
    assert target.read_bytes() == original


def test_direct_symlink_outside_workspace_remains_untouched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = tmp_path / "outside.py"
    original = b"value = 1\n"
    target.write_bytes(original)
    link = workspace / "target.py"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("Symlinks are not supported in this environment")
    monkeypatch.chdir(workspace)

    result = _edit(link)

    assert not result.success
    assert target.read_bytes() == original
    assert link.is_symlink()


def test_temporary_symlink_is_not_followed_or_replaced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = workspace / "target.py"
    target.write_bytes(b"value = 1\n")
    external_sentinel = tmp_path / "sentinel.txt"
    external_original = b"leave this sentinel alone\n"
    external_sentinel.write_bytes(external_original)
    fixed_temp = workspace / "target.py.tmp"
    try:
        fixed_temp.symlink_to(external_sentinel)
    except OSError:
        pytest.skip("Symlinks are not supported in this environment")
    monkeypatch.chdir(workspace)

    result = _edit(target)

    assert result.success
    assert target.read_bytes() == b"value = 2\n"
    assert not target.is_symlink()
    assert external_sentinel.read_bytes() == external_original
    assert fixed_temp.is_symlink()


@pytest.mark.parametrize("input_flag", ["--search-file", "--replace-file"])
def test_apply_rejects_external_block_input_files(
    input_flag: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = workspace / "target.py"
    target.write_bytes(b"value = 1\n")
    external_input = tmp_path / "block.txt"
    external_input.write_text("value = 1\n", encoding="utf-8")
    monkeypatch.chdir(workspace)
    args = ["apply", "--file", str(target)]
    if input_flag == "--search-file":
        args.extend([input_flag, str(external_input), "--replace", "value = 2\n"])
    else:
        args.extend(["--search", "value = 1\n", input_flag, str(external_input)])

    result = main(args)

    assert result == 1
    assert target.read_bytes() == b"value = 1\n"


def test_check_rejects_external_content_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = workspace / "target.py"
    target.write_text("value = 1\n", encoding="utf-8")
    external_input = tmp_path / "content.py"
    external_input.write_text("value = 2\n", encoding="utf-8")
    monkeypatch.chdir(workspace)

    result = main(["check", "--file", str(target), "--content-file", str(external_input)])

    assert result == 1


def test_api_accepts_nested_paths_with_spaces_under_explicit_root(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace with spaces"
    nested = workspace / "nested folder"
    nested.mkdir(parents=True)
    target = nested / "target.py"
    target.write_bytes(b"value = 1\n")

    result = _edit(target, workspace_root=workspace)

    assert result.success
    assert target.read_bytes() == b"value = 2\n"


def test_cli_subprocess_edits_nested_path_with_spaces_from_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "isolated workspace"
    nested = workspace / "nested folder"
    nested.mkdir(parents=True)
    target = nested / "target.py"
    target.write_bytes(b"value = 1\n")
    script = Path(guarded_edit.__file__).resolve()

    completed = subprocess.run(
        [
            sys.executable,
            str(script),
            "apply",
            "--file",
            str(target),
            "--search",
            "value = 1\n",
            "--replace",
            "value = 2\n",
            "--json",
        ],
        cwd=workspace,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert '"success": true' in completed.stdout
    assert target.read_bytes() == b"value = 2\n"


def test_cli_subprocess_rejects_absolute_external_target(tmp_path: Path) -> None:
    workspace = tmp_path / "isolated workspace"
    workspace.mkdir()
    target = tmp_path / "outside.py"
    original = b"value = 1\n"
    target.write_bytes(original)
    script = Path(guarded_edit.__file__).resolve()

    completed = subprocess.run(
        [
            sys.executable,
            str(script),
            "apply",
            "--file",
            str(target),
            "--search",
            "value = 1\n",
            "--replace",
            "value = 2\n",
            "--json",
        ],
        cwd=workspace,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 1
    assert target.read_bytes() == original


def test_target_mode_is_preserved_after_edit(tmp_path: Path) -> None:
    target = tmp_path / "target.py"
    target.write_bytes(b"value = 1\n")
    target.chmod(0o640)

    result = _edit(target, workspace_root=tmp_path)

    assert result.success
    assert stat.S_IMODE(target.stat().st_mode) == 0o640


def test_failed_replace_removes_only_its_temporary_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "target.py"
    target.write_bytes(b"value = 1\n")

    def fail_replace(_source: Path, _destination: Path) -> None:
        raise OSError("synthetic replace failure")

    monkeypatch.setattr(guarded_edit.os, "replace", fail_replace)
    with pytest.raises(OSError, match="synthetic replace failure"):
        _edit(target, workspace_root=tmp_path)

    assert not list(tmp_path.glob(".target.py.*.tmp"))
    assert not (tmp_path / "target.py.tmp").exists()
