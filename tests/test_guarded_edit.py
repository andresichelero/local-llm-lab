"""Unit tests for Guarded Edit wrapper (Trilha B / Roadmap Tarefa 8).

Verifies deterministic pre-commit safety guards:
- Stale SHA detection
- Empty search block
- Zero and multiple (ambiguous) occurrences
- Symlink rejection
- Helper preservation via AST inspection
- Conversational markdown leak detection
- Successful clean replacement
"""
from __future__ import annotations

import hashlib
from pathlib import Path
import pytest

from benchmark.guarded_edit import (
    EditStatus,
    apply_guarded_edit,
    check_helper_preservation,
    check_syntax_leak,
)


def test_empty_search_block(tmp_path: Path) -> None:
    target = tmp_path / "target.py"
    target.write_text("def hello(): pass\n", encoding="utf-8")
    res = apply_guarded_edit(
        target,
        expected_sha256=hashlib.sha256(target.read_bytes()).hexdigest(),
        search_block="",
        replacement_block="def hello(): return 1\n",
    )
    assert not res.success
    assert res.status == EditStatus.EMPTY_SEARCH


def test_stale_sha(tmp_path: Path) -> None:
    target = tmp_path / "target.py"
    target.write_text("def hello(): pass\n", encoding="utf-8")
    res = apply_guarded_edit(
        target,
        expected_sha256="0000000000000000000000000000000000000000000000000000000000000000",
        search_block="def hello(): pass\n",
        replacement_block="def hello(): return 1\n",
    )
    assert not res.success
    assert res.status == EditStatus.STALE_SHA


def test_zero_occurrences(tmp_path: Path) -> None:
    target = tmp_path / "target.py"
    target.write_text("def hello(): pass\n", encoding="utf-8")
    sha = hashlib.sha256(target.read_bytes()).hexdigest()
    res = apply_guarded_edit(
        target,
        expected_sha256=sha,
        search_block="def non_existent(): pass\n",
        replacement_block="def non_existent(): return 1\n",
    )
    assert not res.success
    assert res.status == EditStatus.ZERO_OCCURRENCES


def test_multiple_occurrences(tmp_path: Path) -> None:
    target = tmp_path / "target.py"
    content = "x = 1\ny = 2\nx = 1\n"
    target.write_text(content, encoding="utf-8")
    sha = hashlib.sha256(target.read_bytes()).hexdigest()
    res = apply_guarded_edit(
        target,
        expected_sha256=sha,
        search_block="x = 1\n",
        replacement_block="x = 10\n",
    )
    assert not res.success
    assert res.status == EditStatus.MULTIPLE_OCCURRENCES


def test_symlink_rejection(tmp_path: Path) -> None:
    target = tmp_path / "real_file.py"
    target.write_text("def hello(): pass\n", encoding="utf-8")
    link = tmp_path / "link_file.py"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("Symlinks not supported in this environment")

    sha = hashlib.sha256(target.read_bytes()).hexdigest()
    res = apply_guarded_edit(
        link,
        expected_sha256=sha,
        search_block="def hello(): pass\n",
        replacement_block="def hello(): return 1\n",
    )
    assert not res.success
    assert res.status == EditStatus.SYMLINK_REJECTED


def test_syntax_leak_detection() -> None:
    clean_code = "def add(a, b):\n    return a + b\n"
    assert len(check_syntax_leak(clean_code)) == 0

    leaked_end_of_file = "def add(a, b):\n    return a + b\n(End of file - total 25 lines)\n"
    leaks = check_syntax_leak(leaked_end_of_file)
    assert len(leaks) > 0
    assert any("End of file" in leak for leak in leaks)

    leaked_fence = "```python\ndef add(a, b):\n    return a + b\n```\n"
    leaks2 = check_syntax_leak(leaked_fence)
    assert len(leaks2) > 0


def test_helper_deletion_prevented(tmp_path: Path) -> None:
    original = (
        "def existing_helper(x):\n"
        "    return x * 2\n\n"
        "def target_func():\n"
        "    return 1\n"
    )
    target = tmp_path / "helpers.py"
    target.write_text(original, encoding="utf-8")
    sha = hashlib.sha256(target.read_bytes()).hexdigest()

    # Replacement attempts to wipe existing_helper out
    destructive_replacement = "def target_func():\n    return 42\n"

    res = apply_guarded_edit(
        target,
        expected_sha256=sha,
        search_block=original,
        replacement_block=destructive_replacement,
        allow_helper_deletion=False,
    )
    assert not res.success
    assert res.status == EditStatus.HELPER_DELETION_VIOLATION
    assert "existing_helper" in (res.error_message or "")


def test_successful_unique_edit(tmp_path: Path) -> None:
    original = (
        "def existing_helper(x):\n"
        "    return x * 2\n\n"
        "def target_func():\n"
        "    return 1\n"
    )
    target = tmp_path / "valid.py"
    target.write_text(original, encoding="utf-8")
    sha = hashlib.sha256(target.read_bytes()).hexdigest()

    search = "def target_func():\n    return 1\n"
    replacement = "def target_func():\n    return existing_helper(21)\n"

    res = apply_guarded_edit(
        target,
        expected_sha256=sha,
        search_block=search,
        replacement_block=replacement,
    )
    assert res.success
    assert res.status == EditStatus.APPLIED
    assert res.new_sha256 is not None
    assert "existing_helper(21)" in target.read_text(encoding="utf-8")
    assert "existing_helper(x)" in target.read_text(encoding="utf-8")


def test_check_helper_preservation_direct() -> None:
    code_a = "def foo(): pass\ndef bar(): pass\n"
    code_b = "def foo(): return 1\ndef bar(): return 2\n"
    code_c = "def foo(): return 1\n"

    preserved, missing = check_helper_preservation(code_a, code_b)
    assert preserved
    assert len(missing) == 0

    preserved2, missing2 = check_helper_preservation(code_a, code_c)
    assert not preserved2
    assert "bar" in missing2

