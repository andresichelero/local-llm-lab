"""Guarded Edit wrapper with SHA-256 block uniqueness and AST preservation (Trilha B / Roadmap Tarefa 8).

Implements deterministic safety gates for code modifications:
1. File verification: rejects symlinks, checks file existence.
2. Content integrity: verifies expected SHA-256 against on-disk state.
3. Uniqueness enforcement: search block must occur exactly once in target file.
4. Syntax leak guard: detects conversational markdown artifacts.
5. AST helper preservation: blocks accidental unscoped deletion of existing helper functions.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass
from enum import Enum
import hashlib
import os
from pathlib import Path
import re

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
    if count == 0:
        return EditResult(
            success=False,
            status=EditStatus.ZERO_OCCURRENCES,
            error_message="Search block was not found in target file",
        )
    if count > 1:
        return EditResult(
            success=False,
            status=EditStatus.MULTIPLE_OCCURRENCES,
            error_message=f"Search block occurs {count} times (must be unique)",
        )

    new_content = current_content.replace(search_block, replacement_block, 1)

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
