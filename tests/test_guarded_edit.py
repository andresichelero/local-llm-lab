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
import json
from pathlib import Path
import pytest

from benchmark.guarded_edit import (
    EditStatus,
    apply_guarded_edit,
    check_helper_preservation,
    check_syntax_leak,
    main,
)


@pytest.fixture(autouse=True)
def _use_temporary_workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)


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


def test_whitespace_tolerance_trailing_spaces_in_file(tmp_path: Path) -> None:
    # Target file has trailing spaces on lines, search block has clean lines
    target = tmp_path / "trailing_in_file.py"
    target.write_text("def compute():   \n    return 40 + 2  \n", encoding="utf-8")
    sha = hashlib.sha256(target.read_bytes()).hexdigest()

    search = "def compute():\n    return 40 + 2\n"
    replacement = "def compute():\n    return 100\n"

    res = apply_guarded_edit(
        target,
        expected_sha256=sha,
        search_block=search,
        replacement_block=replacement,
    )
    assert res.success
    assert res.status == EditStatus.APPLIED
    assert "return 100" in target.read_text(encoding="utf-8")


def test_whitespace_tolerance_trailing_spaces_in_search(tmp_path: Path) -> None:
    # Target file has clean lines, search block has trailing spaces
    target = tmp_path / "trailing_in_search.py"
    target.write_text("def compute():\n    return 40 + 2\n", encoding="utf-8")
    sha = hashlib.sha256(target.read_bytes()).hexdigest()

    search = "def compute():  \n    return 40 + 2   \n"
    replacement = "def compute():\n    return 100\n"

    res = apply_guarded_edit(
        target,
        expected_sha256=sha,
        search_block=search,
        replacement_block=replacement,
    )
    assert res.success
    assert res.status == EditStatus.APPLIED
    assert "return 100" in target.read_text(encoding="utf-8")


def test_whitespace_tolerance_crlf_file_lf_search(tmp_path: Path) -> None:
    # Target file has CRLF endings, search block has LF endings
    target = tmp_path / "crlf_file.py"
    target.write_bytes(b"def compute():\r\n    return 42\r\n")
    sha = hashlib.sha256(target.read_bytes()).hexdigest()

    search = "def compute():\n    return 42\n"
    replacement = "def compute():\n    return 99\n"

    res = apply_guarded_edit(
        target,
        expected_sha256=sha,
        search_block=search,
        replacement_block=replacement,
    )
    assert res.success
    assert res.status == EditStatus.APPLIED
    assert "return 99" in target.read_text(encoding="utf-8")


def test_whitespace_tolerance_lf_file_crlf_search(tmp_path: Path) -> None:
    # Target file has LF endings, search block has CRLF endings
    target = tmp_path / "lf_file.py"
    target.write_bytes(b"def compute():\n    return 42\n")
    sha = hashlib.sha256(target.read_bytes()).hexdigest()

    search = "def compute():\r\n    return 42\r\n"
    replacement = "def compute():\n    return 99\n"

    res = apply_guarded_edit(
        target,
        expected_sha256=sha,
        search_block=search,
        replacement_block=replacement,
    )
    assert res.success
    assert res.status == EditStatus.APPLIED
    assert "return 99" in target.read_text(encoding="utf-8")


def test_whitespace_tolerance_multiple_fuzzy_matches(tmp_path: Path) -> None:
    # Two blocks match normalized lines, but exact string match count is 0
    target = tmp_path / "ambiguous.py"
    target.write_text("x = 1  \ny = 2\nx = 1    \n", encoding="utf-8")
    sha = hashlib.sha256(target.read_bytes()).hexdigest()

    search = "x = 1\n"
    replacement = "x = 10\n"

    res = apply_guarded_edit(
        target,
        expected_sha256=sha,
        search_block=search,
        replacement_block=replacement,
    )
    assert not res.success
    assert res.status == EditStatus.MULTIPLE_OCCURRENCES
    assert "occurs 2 times" in (res.error_message or "")


def test_cli_apply_search_and_replace_strings(tmp_path: Path) -> None:
    target = tmp_path / "cli_target.py"
    target.write_text("def hello(): pass\n", encoding="utf-8")

    code = main([
        "apply",
        "--file", str(target),
        "--search", "def hello(): pass\n",
        "--replace", "def hello(): return 42\n",
    ])
    assert code == 0
    assert "return 42" in target.read_text(encoding="utf-8")


def test_cli_apply_search_file_and_replace_file(tmp_path: Path) -> None:
    target = tmp_path / "cli_target.py"
    target.write_text("def hello(): pass\n", encoding="utf-8")
    sf = tmp_path / "search.txt"
    sf.write_text("def hello(): pass\n", encoding="utf-8")
    rf = tmp_path / "replace.txt"
    rf.write_text("def hello(): return 100\n", encoding="utf-8")

    code = main([
        "apply",
        "--file", str(target),
        "--search-file", str(sf),
        "--replace-file", str(rf),
    ])
    assert code == 0
    assert "return 100" in target.read_text(encoding="utf-8")


def test_cli_apply_json_output(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    target = tmp_path / "cli_target.py"
    target.write_text("def hello(): pass\n", encoding="utf-8")

    code = main([
        "apply",
        "--file", str(target),
        "--search", "def hello(): pass\n",
        "--replace", "def hello(): return 1\n",
        "--json",
    ])
    assert code == 0
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["success"] is True
    assert payload["status"] == "applied"
    assert payload["new_sha256"] is not None


def test_cli_apply_failure_exit_code(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    target = tmp_path / "cli_target.py"
    target.write_text("def hello(): pass\n", encoding="utf-8")

    code = main([
        "apply",
        "--file", str(target),
        "--search", "def non_existent(): pass\n",
        "--replace", "def non_existent(): return 1\n",
        "--json",
    ])
    assert code == 1
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["success"] is False
    assert payload["status"] == "zero_occurrences"


def test_cli_apply_expected_sha_match_and_mismatch(tmp_path: Path) -> None:
    target = tmp_path / "cli_target.py"
    target.write_text("def hello(): pass\n", encoding="utf-8")
    actual_sha = hashlib.sha256(target.read_bytes()).hexdigest()

    # Mismatch returns 1
    code_mismatch = main([
        "apply",
        "--file", str(target),
        "--search", "def hello(): pass\n",
        "--replace", "def hello(): return 1\n",
        "--expected-sha", "0" * 64,
    ])
    assert code_mismatch == 1

    # Match returns 0
    code_match = main([
        "apply",
        "--file", str(target),
        "--search", "def hello(): pass\n",
        "--replace", "def hello(): return 1\n",
        "--expected-sha", actual_sha,
    ])
    assert code_match == 0


def test_cli_apply_allow_helper_deletion(tmp_path: Path) -> None:
    original = "def helper(): pass\ndef target(): pass\n"
    target = tmp_path / "cli_helpers.py"
    target.write_text(original, encoding="utf-8")

    # Without allow-helper-deletion -> exit 1
    code_blocked = main([
        "apply",
        "--file", str(target),
        "--search", original,
        "--replace", "def target(): return 1\n",
    ])
    assert code_blocked == 1

    # With allow-helper-deletion -> exit 0
    code_allowed = main([
        "apply",
        "--file", str(target),
        "--search", original,
        "--replace", "def target(): return 1\n",
        "--allow-helper-deletion",
    ])
    assert code_allowed == 0


def test_cli_check_existing_file_json(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    target = tmp_path / "valid.py"
    target.write_text("def foo():\n    return 42\n", encoding="utf-8")

    code = main(["check", "--file", str(target), "--json"])
    assert code == 0
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["success"] is True
    assert payload["status"] == "ok"


def test_cli_check_with_content_json(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    target = tmp_path / "existing.py"
    target.write_text("def foo(): return 1\n", encoding="utf-8")

    code = main([
        "check",
        "--file", str(target),
        "--content", "def foo(): return 2\n",
        "--json",
    ])
    assert code == 0
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["success"] is True


def test_cli_check_syntax_leak(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    target = tmp_path / "valid.py"
    target.write_text("def foo(): return 1\n", encoding="utf-8")
    leaked = "def foo(): return 1\n(End of file)\n"

    code = main([
        "check",
        "--file", str(target),
        "--content", leaked,
        "--json",
    ])
    assert code == 1
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["success"] is False
    assert payload["status"] == "syntax_leak"


def test_cli_check_invalid_syntax(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    target = tmp_path / "valid.py"
    target.write_text("def foo(): return 1\n", encoding="utf-8")

    code = main([
        "check",
        "--file", str(target),
        "--content", "def invalid_syntax(:\n",
        "--json",
    ])
    assert code == 1
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["success"] is False
    assert payload["status"] == "invalid_syntax"


def test_cli_check_helper_deletion(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    target = tmp_path / "helpers.py"
    target.write_text("def helper(): pass\ndef foo(): pass\n", encoding="utf-8")

    code = main([
        "check",
        "--file", str(target),
        "--content", "def foo(): return 1\n",
        "--json",
    ])
    assert code == 1
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["success"] is False
    assert payload["status"] == "helper_deletion_violation"


def test_cli_check_missing_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    missing = tmp_path / "missing.py"
    code = main(["check", "--file", str(missing), "--json"])
    assert code == 1
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["success"] is False
    assert payload["status"] == "file_not_found"



