"""Guarded Edit wrapper with SHA-256 block uniqueness and AST preservation (Trilha B / Roadmap Tarefa 8).

Implements deterministic safety gates for code modifications:
1. File verification: rejects symlinks, checks file existence.
2. Content integrity: verifies expected SHA-256 against on-disk state.
3. Uniqueness enforcement: search block must occur exactly once in target file.
4. Syntax leak guard: detects conversational markdown artifacts.
5. AST helper preservation: blocks accidental unscoped deletion of existing helper functions.
"""
from __future__ import annotations

import argparse
import ast
from dataclasses import dataclass
from enum import Enum
import hashlib
import json
import os
from pathlib import Path
import re
import sys

SYNTAX_LEAK_PATTERNS = [
    re.compile(r"\(End of file.*\)", re.IGNORECASE),
    re.compile(r"```(?:python|py)?"),
    re.compile(r"^Here is the (?:code|updated code|implementation):", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^Below is the (?:code|updated code):", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^\(total \d+ lines\)$", re.IGNORECASE | re.MULTILINE),
]


class EditStatus(str, Enum):
    APPLIED = "applied"
    FILE_NOT_FOUND = "file_not_found"
    EMPTY_SEARCH = "empty_search"
    STALE_SHA = "stale_sha"
    ZERO_OCCURRENCES = "zero_occurrences"
    MULTIPLE_OCCURRENCES = "multiple_occurrences"
    SYMLINK_REJECTED = "symlink_rejected"
    SYNTAX_LEAK = "syntax_leak"
    HELPER_DELETION_VIOLATION = "helper_deletion_violation"
    INVALID_SYNTAX = "invalid_syntax"


@dataclass(frozen=True)
class EditResult:
    success: bool
    status: EditStatus
    new_sha256: str | None = None
    diff: str | None = None
    error_message: str | None = None

    def to_dict(self) -> dict[str, str | bool | None]:
        return {
            "success": self.success,
            "status": self.status.value,
            "new_sha256": self.new_sha256,
            "diff": self.diff,
            "error_message": self.error_message,
        }


def check_syntax_leak(content: str) -> list[str]:
    """Detects leaked markdown commentary or conversation artifacts in code."""
    leaks: list[str] = []
    for pattern in SYNTAX_LEAK_PATTERNS:
        match = pattern.search(content)
        if match:
            leaks.append(f"Matched conversational syntax artifact: {match.group(0)!r}")
    return leaks


def _extract_definitions(source: str) -> set[str]:
    """Extracts top-level and method definitions from source code via AST."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return set()

    defs: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            defs.add(node.name)
        elif isinstance(node, ast.ClassDef):
            defs.add(node.name)
    return defs


def check_helper_preservation(original_code: str, new_code: str) -> tuple[bool, set[str]]:
    """Checks whether existing helper functions and classes in original_code are preserved."""
    orig_defs = _extract_definitions(original_code)
    new_defs = _extract_definitions(new_code)
    missing = orig_defs - new_defs
    return len(missing) == 0, missing


def apply_guarded_edit(
    file_path: Path,
    expected_sha256: str | None,
    search_block: str,
    replacement_block: str,
    *,
    allow_helper_deletion: bool = False,
) -> EditResult:
    """Safely applies a unique search-and-replace edit with deterministic pre-checks."""
    if not search_block:
        return EditResult(
            success=False,
            status=EditStatus.EMPTY_SEARCH,
            error_message="Search block cannot be empty",
        )

    if file_path.is_symlink():
        return EditResult(
            success=False,
            status=EditStatus.SYMLINK_REJECTED,
            error_message=f"Modifications through symlinks are prohibited: {file_path}",
        )

    if not file_path.is_file():
        return EditResult(
            success=False,
            status=EditStatus.FILE_NOT_FOUND,
            error_message=f"Target file does not exist: {file_path}",
        )

    raw_bytes = file_path.read_bytes()
    current_sha = hashlib.sha256(raw_bytes).hexdigest()

    if expected_sha256 is not None and current_sha != expected_sha256.lower():
        return EditResult(
            success=False,
            status=EditStatus.STALE_SHA,
            error_message=f"File state mismatch (expected SHA {expected_sha256}, found {current_sha})",
        )

    # Check syntax leaks in replacement block
    leaks = check_syntax_leak(replacement_block)
    if leaks:
        return EditResult(
            success=False,
            status=EditStatus.SYNTAX_LEAK,
            error_message="; ".join(leaks),
        )

    current_content = raw_bytes.decode("utf-8", errors="replace")

    # Check occurrence count
    count = current_content.count(search_block)
    if count == 1:
        new_content = current_content.replace(search_block, replacement_block, 1)
    elif count > 1:
        return EditResult(
            success=False,
            status=EditStatus.MULTIPLE_OCCURRENCES,
            error_message=f"Search block occurs {count} times (must be unique)",
        )
    else:
        # count == 0: attempt line-level normalized fuzzy matching
        orig_lines = current_content.splitlines(keepends=True)
        search_lines = search_block.splitlines()
        if not search_lines:
            return EditResult(
                success=False,
                status=EditStatus.ZERO_OCCURRENCES,
                error_message="Search block was not found in target file",
            )
        norm_content = [line.rstrip() for line in orig_lines]
        norm_search = [line.rstrip() for line in search_lines]
        m = len(norm_search)
        matches = [
            i
            for i in range(len(norm_content) - m + 1)
            if norm_content[i : i + m] == norm_search
        ]
        if len(matches) == 0:
            return EditResult(
                success=False,
                status=EditStatus.ZERO_OCCURRENCES,
                error_message="Search block was not found in target file",
            )
        if len(matches) > 1:
            return EditResult(
                success=False,
                status=EditStatus.MULTIPLE_OCCURRENCES,
                error_message=f"Search block occurs {len(matches)} times (must be unique)",
            )
        match_idx = matches[0]
        prefix = "".join(orig_lines[:match_idx])
        suffix = "".join(orig_lines[match_idx + m :])
        new_content = prefix + replacement_block + suffix

    # Validate Python syntax if file is a Python source
    if file_path.suffix == ".py":
        try:
            ast.parse(new_content)
        except SyntaxError as syn_err:
            return EditResult(
                success=False,
                status=EditStatus.INVALID_SYNTAX,
                error_message=f"Replacement results in invalid Python syntax: {syn_err}",
            )

        # Helper preservation check
        if not allow_helper_deletion:
            preserved, missing_helpers = check_helper_preservation(current_content, new_content)
            if not preserved:
                return EditResult(
                    success=False,
                    status=EditStatus.HELPER_DELETION_VIOLATION,
                    error_message=f"Unscoped deletion of existing helper functions/classes: {sorted(missing_helpers)}",
                )

    # Write atomically
    new_bytes = new_content.encode("utf-8")
    temp_path = file_path.with_suffix(file_path.suffix + ".tmp")
    temp_path.write_bytes(new_bytes)
    os.replace(temp_path, file_path)

    new_sha = hashlib.sha256(new_bytes).hexdigest()
    return EditResult(
        success=True,
        status=EditStatus.APPLIED,
        new_sha256=new_sha,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="guarded-edit",
        description="Guarded Edit tool with deterministic safety gates and AST validation",
    )
    subparsers = parser.add_subparsers(dest="subcommand", required=True)

    # Subcommand: apply
    apply_parser = subparsers.add_parser("apply", help="Apply a guarded search-and-replace edit")
    apply_parser.add_argument("--file", required=True, type=Path, help="Target file path")
    search_group = apply_parser.add_mutually_exclusive_group(required=True)
    search_group.add_argument("--search", type=str, help="Search block string")
    search_group.add_argument("--search-file", type=Path, help="Path to file containing search block")

    replace_group = apply_parser.add_mutually_exclusive_group(required=True)
    replace_group.add_argument("--replace", type=str, help="Replacement block string")
    replace_group.add_argument("--replace-file", type=Path, help="Path to file containing replacement block")

    apply_parser.add_argument("--expected-sha", type=str, default=None, help="Expected SHA-256 hex digest")
    apply_parser.add_argument(
        "--allow-helper-deletion", action="store_true", default=False, help="Allow helper function deletion"
    )
    apply_parser.add_argument("--json", action="store_true", default=False, help="Output result as JSON")

    # Subcommand: check
    check_parser = subparsers.add_parser(
        "check", help="Check file or proposed content for syntax leaks and AST validity"
    )
    check_parser.add_argument("--file", required=True, type=Path, help="Target file path")
    content_group = check_parser.add_mutually_exclusive_group(required=False)
    content_group.add_argument("--content", type=str, help="Proposed content string")
    content_group.add_argument("--content-file", type=Path, help="Path to file containing proposed content")
    check_parser.add_argument("--json", action="store_true", default=False, help="Output result as JSON")

    try:
        parsed = parser.parse_args(argv)
    except SystemExit as exc:
        return 0 if exc.code == 0 else 1

    if parsed.subcommand == "apply":
        if parsed.search is not None:
            search_block = parsed.search
        else:
            try:
                search_block = parsed.search_file.read_text(encoding="utf-8")
            except OSError as err:
                if parsed.json:
                    print(
                        json.dumps({
                            "success": False,
                            "status": EditStatus.FILE_NOT_FOUND.value,
                            "new_sha256": None,
                            "diff": None,
                            "error_message": f"Could not read search file: {err}",
                        })
                    )
                else:
                    sys.stderr.write(f"Could not read search file: {err}\n")
                return 1

        if parsed.replace is not None:
            replacement_block = parsed.replace
        else:
            try:
                replacement_block = parsed.replace_file.read_text(encoding="utf-8")
            except OSError as err:
                if parsed.json:
                    print(
                        json.dumps({
                            "success": False,
                            "status": EditStatus.FILE_NOT_FOUND.value,
                            "new_sha256": None,
                            "diff": None,
                            "error_message": f"Could not read replace file: {err}",
                        })
                    )
                else:
                    sys.stderr.write(f"Could not read replace file: {err}\n")
                return 1

        res = apply_guarded_edit(
            parsed.file,
            expected_sha256=parsed.expected_sha,
            search_block=search_block,
            replacement_block=replacement_block,
            allow_helper_deletion=parsed.allow_helper_deletion,
        )

        if parsed.json:
            print(json.dumps(res.to_dict(), indent=2))
        else:
            if res.success:
                print(f"Edit applied successfully. New SHA: {res.new_sha256}")
            else:
                sys.stderr.write(f"Edit failed ({res.status.value}): {res.error_message}\n")
        return 0 if res.success else 1

    if parsed.subcommand == "check":
        file_path: Path = parsed.file
        content_specified = parsed.content is not None or parsed.content_file is not None

        if parsed.content is not None:
            code_to_check = parsed.content
        elif parsed.content_file is not None:
            try:
                code_to_check = parsed.content_file.read_text(encoding="utf-8")
            except OSError as err:
                if parsed.json:
                    print(
                        json.dumps({
                            "success": False,
                            "status": EditStatus.FILE_NOT_FOUND.value,
                            "error_message": f"Could not read content file: {err}",
                        })
                    )
                else:
                    sys.stderr.write(f"Could not read content file: {err}\n")
                return 1
        else:
            if not file_path.is_file():
                if parsed.json:
                    print(
                        json.dumps({
                            "success": False,
                            "status": EditStatus.FILE_NOT_FOUND.value,
                            "error_message": f"Target file does not exist: {file_path}",
                        })
                    )
                else:
                    sys.stderr.write(f"Target file does not exist: {file_path}\n")
                return 1
            code_to_check = file_path.read_text(encoding="utf-8")

        # 1. Syntax leak check
        leaks = check_syntax_leak(code_to_check)
        if leaks:
            err_msg = "; ".join(leaks)
            if parsed.json:
                print(
                    json.dumps({
                        "success": False,
                        "status": EditStatus.SYNTAX_LEAK.value,
                        "error_message": err_msg,
                    })
                )
            else:
                sys.stderr.write(f"Syntax leak detected: {err_msg}\n")
            return 1

        # 2. AST syntax check (for Python files)
        if file_path.suffix == ".py":
            try:
                ast.parse(code_to_check)
            except SyntaxError as syn_err:
                if parsed.json:
                    print(
                        json.dumps({
                            "success": False,
                            "status": EditStatus.INVALID_SYNTAX.value,
                            "error_message": f"Invalid Python syntax: {syn_err}",
                        })
                    )
                else:
                    sys.stderr.write(f"Invalid Python syntax: {syn_err}\n")
                return 1

            # 3. Helper preservation check if checking proposed content against existing file
            if content_specified and file_path.is_file():
                orig_code = file_path.read_text(encoding="utf-8")
                preserved, missing = check_helper_preservation(orig_code, code_to_check)
                if not preserved:
                    err_msg = f"Unscoped deletion of existing helper functions/classes: {sorted(missing)}"
                    if parsed.json:
                        print(
                            json.dumps({
                                "success": False,
                                "status": EditStatus.HELPER_DELETION_VIOLATION.value,
                                "error_message": err_msg,
                            })
                        )
                    else:
                        sys.stderr.write(f"Helper deletion violation: {err_msg}\n")
                    return 1

        if parsed.json:
            print(
                json.dumps({
                    "success": True,
                    "status": "ok",
                    "error_message": None,
                })
            )
        else:
            print(f"Check passed for {file_path}")
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
