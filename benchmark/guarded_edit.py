"""Guarded Edit wrapper with SHA-256 block uniqueness and AST preservation (Track B / Roadmap Task 8).

Implements deterministic safety gates for code modifications:
1. File verification: rejects symlinks, checks file existence.
2. Path scope: confines targets and block inputs to a workspace root.
3. Content integrity: verifies expected SHA-256 against on-disk state.
4. Uniqueness enforcement: search block must occur exactly once in target file.
5. Syntax leak guard: detects conversational markdown artifacts.
6. AST helper preservation: blocks accidental unscoped deletion of existing helper functions.

Path checks are an application guard, not an OS sandbox, and do not prevent
path swaps by a hostile concurrent process.
"""
from __future__ import annotations

import argparse
import ast
import difflib
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

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
    PATH_OUTSIDE_WORKSPACE = "path_outside_workspace"
    SYNTAX_LEAK = "syntax_leak"
    HELPER_DELETION_VIOLATION = "helper_deletion_violation"
    INVALID_SYNTAX = "invalid_syntax"
    MALFORMED_OUTPUT = "malformed_output"
    OUTSIDE_ALLOWLIST = "outside_allowlist"
    PROTECTED_FILE = "protected_file"
    VALIDATOR_UNAVAILABLE = "validator_unavailable"


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


class _WorkspacePathError(ValueError):
    def __init__(self, status: EditStatus, message: str) -> None:
        super().__init__(message)
        self.status = status


def _is_link_or_junction(path: Path) -> bool:
    if path.is_symlink():
        return True
    is_junction = getattr(path, "is_junction", None)
    return bool(is_junction and is_junction())


def _resolve_workspace_path(path: Path, workspace_root: Path) -> Path:
    """Resolve a candidate path while rejecting escapes and linked components."""
    try:
        root = Path(workspace_root).resolve(strict=True)
    except (OSError, RuntimeError) as err:
        raise _WorkspacePathError(
            EditStatus.PATH_OUTSIDE_WORKSPACE,
            f"Workspace root cannot be resolved: {workspace_root}",
        ) from err
    if not root.is_dir():
        raise _WorkspacePathError(
            EditStatus.PATH_OUTSIDE_WORKSPACE,
            f"Workspace root is not a directory: {root}",
        )

    candidate = Path(path)
    if candidate.is_absolute():
        try:
            relative = candidate.relative_to(root)
        except ValueError as err:
            raise _WorkspacePathError(
                EditStatus.PATH_OUTSIDE_WORKSPACE,
                f"Path is outside the workspace: {path}",
            ) from err
    else:
        if candidate.drive or candidate.root:
            raise _WorkspacePathError(
                EditStatus.PATH_OUTSIDE_WORKSPACE,
                f"Path is outside the workspace: {path}",
            )
        relative = candidate

    current = root
    for part in relative.parts:
        if part in ("", "."):
            continue
        if part == "..":
            if current == root:
                raise _WorkspacePathError(
                    EditStatus.PATH_OUTSIDE_WORKSPACE,
                    f"Path is outside the workspace: {path}",
                )
            current = current.parent
            continue

        current = current / part
        try:
            linked = _is_link_or_junction(current)
        except OSError as err:
            raise _WorkspacePathError(
                EditStatus.PATH_OUTSIDE_WORKSPACE,
                f"Path cannot be inspected safely: {path}",
            ) from err
        if linked:
            raise _WorkspacePathError(
                EditStatus.SYMLINK_REJECTED,
                f"Modifications through symlinks are prohibited: {current}",
            )
        try:
            current.relative_to(root)
        except ValueError as err:
            raise _WorkspacePathError(
                EditStatus.PATH_OUTSIDE_WORKSPACE,
                f"Path is outside the workspace: {path}",
            ) from err

    try:
        resolved = current.resolve(strict=False)
        resolved.relative_to(root)
    except (OSError, RuntimeError, ValueError) as err:
        raise _WorkspacePathError(
            EditStatus.SYMLINK_REJECTED,
            f"Path cannot be resolved within the workspace: {path}",
        ) from err
    return resolved


def _emit_cli_error(
    json_output: bool,
    status: EditStatus,
    message: str,
    *,
    include_edit_fields: bool = False,
) -> None:
    if json_output:
        payload: dict[str, str | bool | None] = {
            "success": False,
            "status": status.value,
            "error_message": message,
        }
        if include_edit_fields:
            payload["new_sha256"] = None
            payload["diff"] = None
        print(json.dumps(payload, indent=2))
    else:
        sys.stderr.write(f"Operation failed ({status.value}): {message}\n")


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
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
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
    workspace_root: Path | None = None,
) -> EditResult:
    """Apply one unique edit; workspace_root defaults to cwd for trusted callers."""
    try:
        root = Path.cwd() if workspace_root is None else Path(workspace_root)
        file_path = _resolve_workspace_path(file_path, root)
    except _WorkspacePathError as err:
        return EditResult(
            success=False,
            status=err.status,
            error_message=str(err),
        )

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

    # Write atomically through a unique, exclusively-created file beside the target.
    new_bytes = new_content.encode("utf-8")
    target_mode = stat.S_IMODE(file_path.stat().st_mode)
    temp_fd, temp_name = tempfile.mkstemp(
        dir=file_path.parent,
        prefix=f".{file_path.name}.",
        suffix=".tmp",
    )
    temp_path = Path(temp_name)
    try:
        with os.fdopen(temp_fd, "wb") as temp_file:
            temp_file.write(new_bytes)
            temp_file.flush()
            if hasattr(os, "fchmod"):
                os.fchmod(temp_file.fileno(), target_mode)
            else:
                os.chmod(temp_path, target_mode)
        os.replace(temp_path, file_path)
    except BaseException:
        try:
            temp_path.unlink()
        except FileNotFoundError:
            pass
        raise

    new_sha = hashlib.sha256(new_bytes).hexdigest()
    return EditResult(
        success=True,
        status=EditStatus.APPLIED,
        new_sha256=new_sha,
    )


@dataclass(frozen=True)
class BatchFileReceipt:
    path: str
    before_sha256: str
    after_sha256: str
    diff: str
    blocks_applied: tuple[dict[str, str], ...]


@dataclass(frozen=True)
class BatchResult:
    success: bool
    status: EditStatus
    original_output: str
    files: tuple[BatchFileReceipt, ...] = ()
    error_message: str = ""


def apply_edit_batch(workspace_root: Path, output: str, input_hashes: dict[str, str],
                     writable_files: list[str], *,
                     authored_tests: tuple[str, ...] = ()) -> BatchResult:
    """Apply exact blocks; format: FILE: path, SEARCH marker, text, separator, text, REPLACE marker.

    Every marker occupies its own LF-terminated line; blocks concatenate without
    fences or prose. Empty SEARCH creates an absent allowlisted file only.
    """
    def reject(status: EditStatus, message: str) -> BatchResult:
        return BatchResult(False, status, output, error_message=message)

    pattern = re.compile(
        r"FILE: ([^\r\n]+)\n<<<<<<< SEARCH\n(.*?)^=======\n(.*?)^>>>>>>> REPLACE\n",
        re.DOTALL | re.MULTILINE,
    )
    blocks = []
    pos = 0
    while pos < len(output):
        match = pattern.match(output, pos)
        if not match:
            return reject(EditStatus.MALFORMED_OUTPUT, "Invalid SEARCH/REPLACE grammar")
        path, search, replacement = match.groups()
        if any(marker in search or marker in replacement for marker in
               ("<<<<<<< SEARCH", "=======", ">>>>>>> REPLACE", "FILE: ")):
            return reject(EditStatus.MALFORMED_OUTPUT, "Reserved marker in block")
        blocks.append((path, search, replacement))
        pos = match.end()
    if not blocks:
        return reject(EditStatus.MALFORMED_OUTPUT, "No blocks")
    root = Path(workspace_root).resolve()
    original: dict[str, bytes] = {}
    contents: dict[str, str] = {}
    targets: dict[str, Path] = {}
    counts: dict[str, int] = {}
    applied: dict[str, list[dict[str, str]]] = {}
    existed: dict[str, bool] = {}
    for name, search, replacement in blocks:
        try:
            target = _resolve_workspace_path(Path(name), root)
        except _WorkspacePathError as err:
            return reject(err.status, str(err))
        canonical = target.relative_to(root).as_posix()
        if name != canonical or name not in writable_files:
            return reject(EditStatus.OUTSIDE_ALLOWLIST, name)
        is_test = (any(part in {"test", "tests"} for part in target.parts)
                   or target.name.startswith("test_") or target.name.endswith("_test.py"))
        if "oracles" in target.parts or (is_test and target.exists() and name not in authored_tests):
            return reject(EditStatus.PROTECTED_FILE, name)
        if name not in contents:
            existed[name] = target.exists()
            if existed[name] and not target.is_file():
                return reject(EditStatus.FILE_NOT_FOUND, name)
            raw = target.read_bytes() if existed[name] else b""
            digest = hashlib.sha256(raw).hexdigest()
            if input_hashes.get(name) != digest:
                return reject(EditStatus.STALE_SHA, name)
            try:
                contents[name] = raw.decode("utf-8")
            except UnicodeDecodeError:
                return reject(EditStatus.INVALID_SYNTAX, "Target is not UTF-8")
            original[name], targets[name], counts[name] = raw, target, 0
            applied[name] = []
        if check_syntax_leak(replacement):
            return reject(EditStatus.SYNTAX_LEAK, name)
        if not search:
            if existed[name] or counts[name]:
                return reject(EditStatus.EMPTY_SEARCH, name)
            contents[name] = replacement
        else:
            first = contents[name].find(search)
            if first < 0:
                return reject(EditStatus.ZERO_OCCURRENCES, name)
            if contents[name].find(search, first + 1) >= 0:
                return reject(EditStatus.MULTIPLE_OCCURRENCES, name)
            contents[name] = contents[name].replace(search, replacement, 1)
        counts[name] += 1
        applied[name].append({"search": search, "replace": replacement})
    receipts = []
    for name, content in contents.items():
        if targets[name].suffix == ".py":
            try:
                compile(content, str(targets[name]), "exec", dont_inherit=True)
            except SyntaxError as err:
                return reject(EditStatus.INVALID_SYNTAX, str(err))
            if not check_helper_preservation(original[name].decode(), content)[0]:
                return reject(EditStatus.HELPER_DELETION_VIOLATION, name)
        elif targets[name].suffix in {".js", ".cjs", ".mjs"}:
            node = os.environ.get("CORPUS_NODE") or shutil.which("node")
            if not node:
                versions = []
                for candidate in (Path.home() / ".nvm/versions/node").glob("v*/bin/node"):
                    try:
                        version = tuple(int(part) for part in candidate.parent.parent.name[1:].split("."))
                    except ValueError:
                        continue
                    if candidate.is_file() and os.access(candidate, os.X_OK):
                        versions.append((version, candidate))
                if versions:
                    node = str(max(versions)[1])
            if not node:
                return reject(EditStatus.VALIDATOR_UNAVAILABLE, "Node is required to check JavaScript")
            try:
                command = [node, "--check"]
                if targets[name].suffix == ".mjs":
                    command.append("--input-type=module")
                checked = subprocess.run([*command, "-"], input=content, text=True,
                                         capture_output=True, timeout=10, check=False)
            except TimeoutError:
                raise
            except (OSError, subprocess.TimeoutExpired) as err:
                return reject(EditStatus.VALIDATOR_UNAVAILABLE, str(err))
            if checked.returncode:
                return reject(EditStatus.INVALID_SYNTAX, "JavaScript syntax check failed")
        before = original[name].decode()
        receipts.append(BatchFileReceipt(name, hashlib.sha256(original[name]).hexdigest(),
                         hashlib.sha256(content.encode()).hexdigest(),
                         "".join(difflib.unified_diff(before.splitlines(True),
                                 content.splitlines(True), fromfile="a/" + name,
                                 tofile="b/" + name)), tuple(applied[name])))
    # All validation precedes writes. Roll back any already replaced files on I/O failure.
    staged: dict[str, Path] = {}
    backups: dict[str, Path] = {}
    written: list[str] = []
    retain_backups = False
    try:
        for name, target in targets.items():
            fd, temp = tempfile.mkstemp(dir=target.parent, prefix=".worker-", suffix=".tmp")
            staged[name] = Path(temp)
            with os.fdopen(fd, "wb") as f:
                f.write(contents[name].encode())
            if existed[name]:
                os.chmod(temp, stat.S_IMODE(target.stat().st_mode))
                backup_fd, backup_name = tempfile.mkstemp(
                    dir=target.parent, prefix=".worker-backup-", suffix=".tmp")
                backups[name] = Path(backup_name)
                with os.fdopen(backup_fd, "wb") as backup:
                    backup.write(original[name])
                os.chmod(backup_name, stat.S_IMODE(target.stat().st_mode))
        for name, target in targets.items():
            written.append(name)
            os.replace(staged[name], target)
    except BaseException as failure:
        rollback_errors = []
        for name in reversed(written):
            try:
                if existed[name]:
                    os.replace(backups[name], targets[name])
                else:
                    targets[name].unlink(missing_ok=True)
            except OSError as err:
                rollback_errors.append(f"{name}: {err}")
        if rollback_errors:
            retain_backups = True
            raise RuntimeError("Rollback failed; backups retained: " + "; ".join(rollback_errors)) from failure
        raise
    finally:
        for temp in staged.values():
            temp.unlink(missing_ok=True)
        if not retain_backups:
            for backup in backups.values():
                backup.unlink(missing_ok=True)
    return BatchResult(True, EditStatus.APPLIED, output, tuple(receipts))


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

    workspace_root = Path.cwd().resolve()
    try:
        file_path = _resolve_workspace_path(parsed.file, workspace_root)
        search_file = (
            _resolve_workspace_path(parsed.search_file, workspace_root)
            if parsed.subcommand == "apply" and parsed.search_file is not None
            else None
        )
        replace_file = (
            _resolve_workspace_path(parsed.replace_file, workspace_root)
            if parsed.subcommand == "apply" and parsed.replace_file is not None
            else None
        )
        content_file = (
            _resolve_workspace_path(parsed.content_file, workspace_root)
            if parsed.subcommand == "check" and parsed.content_file is not None
            else None
        )
    except _WorkspacePathError as err:
        _emit_cli_error(
            parsed.json,
            err.status,
            str(err),
            include_edit_fields=parsed.subcommand == "apply",
        )
        return 1

    if parsed.subcommand == "apply":
        if parsed.search is not None:
            search_block = parsed.search
        else:
            try:
                assert search_file is not None
                search_block = search_file.read_text(encoding="utf-8")
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
                assert replace_file is not None
                replacement_block = replace_file.read_text(encoding="utf-8")
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
            file_path,
            expected_sha256=parsed.expected_sha,
            search_block=search_block,
            replacement_block=replacement_block,
            allow_helper_deletion=parsed.allow_helper_deletion,
            workspace_root=workspace_root,
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
        content_specified = parsed.content is not None or parsed.content_file is not None

        if parsed.content is not None:
            code_to_check = parsed.content
        elif parsed.content_file is not None:
            try:
                assert content_file is not None
                code_to_check = content_file.read_text(encoding="utf-8")
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
