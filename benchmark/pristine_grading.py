"""Source-only final grading against fingerprinted task fixtures.

This module does not provide OS or network isolation. Candidate tests are parsed
for workflow evidence but are never imported or executed. Candidate source still
shares an interpreter with the test runner, so runtime results are not
authenticated against hostile candidate code. The ``success`` aggregate is a
compatibility diagnostic only; false positives remain possible until a separate
evaluator authority boundary exists.
"""
from __future__ import annotations

import ast
import difflib
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path, PureWindowsPath
from typing import Any

from benchmark.process_control import stop_process_group
from benchmark.run_observer import _is_secret


REPO_ROOT = Path(__file__).resolve().parents[1]
GRADER_PROTOCOL_VERSION = "pristine-workspace-v1"
FINGERPRINT_MANIFEST = REPO_ROOT / "benchmark/configs/grading/fixture-fingerprints-v1.json"
EVAL_SUITES_DIR = REPO_ROOT / "benchmark/eval_suites"
MAX_CANDIDATE_FILE_BYTES = 4 * 1024 * 1024
OUTPUT_LIMIT = 4000

# Explicit task policy: candidate-authored test paths are workflow evidence
# only; source paths are the only candidate bytes ever replayed for execution.
TASK_POLICIES: dict[str, dict[str, Any]] = {
    "calculator_division": {
        "fixture": "benchmark/fixtures/harness_task",
        "source_files": ("src/calculator.py",),
        "test_files": ("tests/test_calculator.py",),
        "suite": "calculator_division",
        "preserved_helpers": ("add", "multiply"),
        "required_test_groups": (
            ("test_divide_positive", "test_divide_positive_operands", "test_positive_operands",
             "test_divide_positives", "test_divide_positive_numbers", "contains:positive"),
            ("test_divide_negative", "test_divide_negative_operand", "test_divide_negative_operands",
             "test_negative_operand", "test_negative_operands", "test_divide_negatives",
             "test_divide_negative_numbers", "contains:negative"),
            ("test_divide_by_zero", "test_division_by_zero", "test_divide_zero", "contains:zero"),
        ),
    },
    "whitespace_normalization": {
        "fixture": "benchmark/fixtures/harness_whitespace",
        "source_files": ("src/text_utils.py",),
        "test_files": ("tests/test_text_utils.py",),
        "suite": "whitespace_normalization",
        "preserved_helpers": ("word_count",),
        "required_test_groups": (
            ("test_empty_input",),
            ("test_collapses_mixed_whitespace",),
            ("test_preserves_unicode_text",),
        ),
    },
    "dotenv_line_parser": {
        "fixture": "benchmark/fixtures/harness_env_parser",
        "source_files": ("src/config_parser.py",),
        "test_files": ("tests/test_config_parser.py",),
        "suite": "dotenv_line_parser",
        "preserved_helpers": ("normalize_key",),
        "required_test_groups": (
            ("test_ignores_blank_and_comment_lines",),
            ("test_splits_on_first_equals_and_trims",),
            ("test_strips_matching_quotes",),
        ),
    },
    "config_precedence": {
        "fixture": "benchmark/fixtures/config_precedence_task",
        "source_files": ("src/config.py",),
        "test_files": ("tests/test_config.py",),
        "suite": "config_precedence",
        "preserved_helpers": ("validate_schema",),
        "required_test_groups": (
            ("test_cli_overrides_file_and_defaults",),
            ("test_preserves_falsy_values",),
            ("test_does_not_mutate_inputs",),
        ),
    },
    "retry_policy": {
        "fixture": "benchmark/fixtures/retry_policy_task",
        "source_files": ("src/retry.py",),
        "test_files": ("tests/test_retry.py",),
        "suite": "retry_policy",
        "preserved_helpers": ("calculate_backoff",),
        "required_test_groups": (
            ("test_succeeds_on_first_attempt",),
            ("test_retries_transient_and_calls_callback",),
            ("test_raises_immediately_on_permanent_error",),
            ("test_exhausts_retries_and_reraises",),
        ),
    },
    "package_refactor": {
        "fixture": "benchmark/fixtures/package_refactor_task",
        "source_files": ("src/service.py", "src/metrics.py"),
        "fixture_source_files": ("src/service.py",),
        "test_files": ("tests/test_service.py",),
        "suite": "package_refactor",
        "preserved_helpers": ("sanitize_record",),
        "required_test_groups": (
            ("test_summarize_metrics_empty_and_normal",),
            ("test_generate_service_summary_filters_missing",),
            ("test_service_reexports_metrics",),
        ),
    },
}
TASK_ALIASES = {
    "config_precedence_task": "config_precedence",
    "retry_policy_task": "retry_policy",
    "package_refactor_task": "package_refactor",
}
IGNORED_BYTECODE_DIRS = {"__pycache__"}


class UnsafeWorkspaceError(RuntimeError):
    """Candidate structure failed before any candidate content was opened."""


def _canonical_task(task: str) -> str:
    canonical = TASK_ALIASES.get(task, task)
    if canonical not in TASK_POLICIES:
        raise ValueError(f"Unsupported task: {task}")
    return canonical


def _absolute_without_resolving(path: Path) -> Path:
    return Path(os.path.abspath(os.fspath(path)))


def _is_junction(path: Path) -> bool:
    checker = getattr(path, "is_junction", None)
    return bool(checker()) if checker is not None else False


def _is_link(path: Path, mode: int) -> bool:
    return stat.S_ISLNK(mode) or _is_junction(path)


def _check_parent_components(path: Path) -> list[str]:
    problems: list[str] = []
    components = list(reversed(path.parents)) + [path]
    for component in components:
        try:
            metadata = component.lstat()
        except OSError:
            problems.append(f"missing_parent:{component}")
            continue
        if _is_link(component, metadata.st_mode):
            problems.append(f"linked_parent:{component}")
        if _is_secret(component.name):
            problems.append(f"secret_path_component:{component.name}")
    return problems


def _existing_parent_link(path: Path) -> str | None:
    for component in list(reversed(path.parents)) + [path]:
        try:
            metadata = component.lstat()
        except OSError:
            continue
        if _is_link(component, metadata.st_mode):
            return str(component)
    return None


def _path_is_within(path: Path, parent: Path) -> bool:
    try:
        common = os.path.commonpath([os.fspath(path), os.fspath(parent)])
    except ValueError:
        return False
    return os.path.normcase(common) == os.path.normcase(os.fspath(parent))


def _read_regular_file(path: Path, *, max_bytes: int | None = None) -> tuple[bytes, os.stat_result]:
    parent_problems = _check_parent_components(path)
    if parent_problems:
        raise UnsafeWorkspaceError("unsafe_file_path_components")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    descriptor = os.open(path, flags)
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink > 1:
            raise UnsafeWorkspaceError(f"not_an_unlinked_regular_file:{path.name}")
        if max_bytes is not None and metadata.st_size > max_bytes:
            raise UnsafeWorkspaceError(f"candidate_file_too_large:{path.name}")
        chunks: list[bytes] = []
        while True:
            block = os.read(descriptor, 1024 * 1024)
            if not block:
                break
            chunks.append(block)
        return b"".join(chunks), metadata
    finally:
        os.close(descriptor)


def _load_manifest() -> dict[str, Any]:
    try:
        raw, metadata = _read_regular_file(FINGERPRINT_MANIFEST)
        if not stat.S_ISREG(metadata.st_mode):
            raise ValueError("fingerprint manifest is not a regular file")
        manifest = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError, UnsafeWorkspaceError) as error:
        raise ValueError(f"fixture_fingerprint_manifest_unavailable:{type(error).__name__}") from error
    if not isinstance(manifest, dict):
        raise ValueError("fixture fingerprint manifest is not an object")
    if manifest.get("schema_version") != 1 or manifest.get("grader_protocol_version") != GRADER_PROTOCOL_VERSION:
        raise ValueError("unsupported fixture fingerprint manifest")
    tasks = manifest.get("tasks")
    if not isinstance(tasks, dict) or set(tasks) != set(TASK_POLICIES):
        raise ValueError("fixture fingerprint task set does not match grader policy")
    return manifest


def _expected_fixture(task: str, baseline: Path) -> Path:
    fixture_relative = TASK_POLICIES[task]["fixture"]
    expected = _absolute_without_resolving(REPO_ROOT / fixture_relative)
    supplied = _absolute_without_resolving(baseline)
    if os.path.normcase(os.fspath(expected)) != os.path.normcase(os.fspath(supplied)):
        raise ValueError("baseline_path_does_not_match_fixed_task_fixture")
    return expected


def _verify_fixture(task: str, baseline: Path, manifest: dict[str, Any]) -> tuple[dict[str, bytes], dict[str, int]]:
    expected_root = _expected_fixture(task, baseline)
    parent_problems = _check_parent_components(expected_root)
    if parent_problems:
        raise ValueError("unsafe_trusted_fixture_path")
    entry = manifest["tasks"][task]
    if not isinstance(entry, dict):
        raise ValueError("fixture task fingerprint entry is invalid")
    if entry.get("fixture") != TASK_POLICIES[task]["fixture"]:
        raise ValueError("fixture_path_mismatch_in_manifest")
    declared = entry.get("files")
    if not isinstance(declared, dict) or not declared:
        raise ValueError("fixture_file_manifest_empty")

    expected_paths = {
        "TASK.md",
        *TASK_POLICIES[task].get("fixture_source_files", TASK_POLICIES[task]["source_files"]),
        *TASK_POLICIES[task]["test_files"],
    }
    if set(declared) != expected_paths:
        raise ValueError("fixture_file_manifest_does_not_match_task_policy")

    contents: dict[str, bytes] = {}
    modes: dict[str, int] = {}
    for relative in sorted(expected_paths):
        if Path(relative).is_absolute() or PureWindowsPath(relative).is_absolute() or ".." in Path(relative).parts:
            raise ValueError("invalid_fixture_relative_path")
        path = expected_root / relative
        raw, metadata = _read_regular_file(path)
        record = declared[relative]
        if not isinstance(record, dict):
            raise ValueError(f"fixture_fingerprint_entry_invalid:{relative}")
        if len(raw) != record.get("size_bytes") or hashlib.sha256(raw).hexdigest() != record.get("sha256"):
            raise ValueError(f"fixture_fingerprint_mismatch:{relative}")
        if relative in TASK_POLICIES[task]["test_files"] and not raw.strip():
            raise ValueError(f"fixture_test_file_empty:{relative}")
        contents[relative] = raw
        modes[relative] = stat.S_IMODE(metadata.st_mode)
    return contents, modes


def _scan_candidate(workspace: Path) -> dict[str, Any]:
    root = _absolute_without_resolving(workspace)
    problems = _check_parent_components(root)
    if problems:
        return {"passed": False, "problems": problems, "files": set(), "directories": set(),
                "modes": {}, "git_metadata_audited": False, "bytecode_ignored": True}
    try:
        root_metadata = root.lstat()
    except OSError:
        return {"passed": False, "problems": ["workspace_root_unavailable"], "files": set(),
                "directories": set(), "modes": {}, "git_metadata_audited": False, "bytecode_ignored": True}
    if _is_link(root, root_metadata.st_mode) or not stat.S_ISDIR(root_metadata.st_mode):
        return {"passed": False, "problems": ["workspace_root_not_plain_directory"], "files": set(),
                "directories": set(), "modes": {}, "git_metadata_audited": False, "bytecode_ignored": True}

    problems: list[str] = []
    files: set[str] = set()
    directories: set[str] = set()
    modes: dict[str, int] = {}
    stack: list[tuple[Path, str]] = [(root, "")]
    while stack:
        directory, relative_parent = stack.pop()
        try:
            entries = list(os.scandir(directory))
        except OSError:
            problems.append(f"directory_scan_failed:{relative_parent or '.'}")
            continue
        for entry in entries:
            name = entry.name
            relative = f"{relative_parent}/{name}" if relative_parent else name
            if name.lower() == ".git":
                continue
            if _is_secret(name):
                problems.append(f"secret_path_component:{relative}")
                continue
            path = Path(entry.path)
            try:
                metadata = entry.stat(follow_symlinks=False)
            except OSError:
                problems.append(f"entry_stat_failed:{relative}")
                continue
            mode = metadata.st_mode
            if _is_link(path, mode):
                problems.append(f"symlink_or_junction:{relative}")
                continue
            if stat.S_ISDIR(mode):
                if name not in IGNORED_BYTECODE_DIRS:
                    directories.add(relative)
                stack.append((path, relative))
                continue
            if not stat.S_ISREG(mode):
                problems.append(f"special_entry:{relative}")
                continue
            if metadata.st_nlink > 1:
                problems.append(f"hardlink:{relative}")
                continue
            if name.endswith(".pyc") or "__pycache__" in Path(relative).parts:
                continue
            files.add(relative)
            modes[relative] = stat.S_IMODE(mode)
    return {"passed": not problems, "problems": sorted(problems), "files": files,
            "directories": directories, "modes": modes, "git_metadata_audited": False,
            "bytecode_ignored": True}


def _allowed_paths(task: str) -> set[str]:
    policy = TASK_POLICIES[task]
    return set(policy["source_files"]) | set(policy["test_files"])


def _scope_result(
    task: str,
    candidate: dict[str, Any],
    trusted_files: dict[str, bytes],
    candidate_bytes: dict[str, bytes],
) -> dict[str, Any]:
    policy = TASK_POLICIES[task]
    allowed = _allowed_paths(task)
    source_paths = set(policy["source_files"])
    known_paths = set(trusted_files)
    allowed_directories = {
        parent.as_posix()
        for relative in (known_paths | set(policy["source_files"]) | set(policy["test_files"]))
        for parent in Path(relative).parents
        if parent.as_posix() != "."
    }
    unlisted_files = sorted(candidate["files"] - known_paths - source_paths)
    missing_protected = sorted((known_paths - allowed) - candidate["files"])
    unlisted_directories = sorted(candidate["directories"] - allowed_directories)
    helper_ok: bool | None = True
    helper_errors: list[str] = []
    for relative in policy["source_files"]:
        current = candidate_bytes.get(relative)
        original = trusted_files.get(relative)
        if current is None or original is None:
            if relative == "src/metrics.py" and current is not None:
                continue
            if current is None and original is None:
                continue
            helper_ok = False
            helper_errors.append(f"preserved_helper_source_missing:{relative}")
            continue
        try:
            current_functions = _functions(current.decode("utf-8"), set(policy["preserved_helpers"]))
            original_functions = _functions(original.decode("utf-8"), set(policy["preserved_helpers"]))
        except (UnicodeError, SyntaxError):
            helper_ok = None
            helper_errors.append(f"source_parse_failed:{relative}")
            continue
        if current_functions != original_functions and helper_ok is not None:
            helper_ok = False
            helper_errors.append(f"preserved_helper_changed:{relative}")
    path_scope_pass = not unlisted_files and not missing_protected and not unlisted_directories
    scope_pass = path_scope_pass and helper_ok is not False
    changed_allowed = sorted(
        relative for relative in allowed
        if candidate_bytes.get(relative) != trusted_files.get(relative)
    )
    return {
        "passed": scope_pass,
        "unlisted_files": unlisted_files,
        "missing_protected_files": missing_protected,
        "unlisted_directories": unlisted_directories,
        "changed_allowed_files": changed_allowed,
        "preserved_helpers_pass": helper_ok,
        "path_scope_pass": path_scope_pass,
        "preserved_helper_errors": helper_errors,
        "source_changes": sorted(relative for relative in changed_allowed if relative in source_paths),
    }


def _functions(source: str, names: set[str]) -> dict[str, str]:
    tree = ast.parse(source)
    return {
        node.name: ast.dump(node, include_attributes=False)
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names
    }


def _workflow_result(task: str, candidate_bytes: dict[str, bytes]) -> dict[str, Any]:
    policy = TASK_POLICIES[task]
    test_names: set[str] = set()
    parse_errors: list[str] = []
    missing_files: list[str] = []
    for relative in policy["test_files"]:
        raw = candidate_bytes.get(relative)
        if raw is None:
            missing_files.append(relative)
            continue
        try:
            tree = ast.parse(raw.decode("utf-8"))
        except (UnicodeError, SyntaxError) as error:
            parse_errors.append(f"{relative}:{type(error).__name__}")
            continue
        test_names.update(
            node.name for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        )
    present_groups = []
    for group in policy["required_test_groups"]:
        present = any(
            expected in test_names
            or (expected.startswith("contains:") and expected.removeprefix("contains:") in name)
            for expected in group
            for name in test_names
        )
        present_groups.append(present)
    names_present = bool(present_groups) and all(present_groups)
    workflow_pass = not missing_files and not parse_errors and names_present
    return {
        "passed": workflow_pass,
        "candidate_test_files": list(policy["test_files"]),
        "test_method_count": len(test_names),
        "required_test_groups_present": present_groups,
        "required_test_names_present": names_present,
        "missing_test_files": missing_files,
        "parse_errors": parse_errors,
        "test_quality": "unmeasured",
        "candidate_tests_executed": False,
    }


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _write_replay_artifacts(
    artifact_root: Path,
    task: str,
    trusted_files: dict[str, bytes],
    replay_sources: dict[str, bytes],
    result: dict[str, Any],
) -> None:
    source_patches: list[str] = []
    source_hashes: dict[str, str] = {}
    for relative in TASK_POLICIES[task]["source_files"]:
        candidate = replay_sources.get(relative)
        if candidate is None and relative not in trusted_files:
            continue
        original = trusted_files.get(relative, b"")
        if candidate is not None:
            source_hashes[relative] = _sha256(candidate)
        before = original.decode("utf-8", errors="replace").splitlines(keepends=True)
        after = candidate.decode("utf-8", errors="replace").splitlines(keepends=True) if candidate else []
        source_patches.extend(difflib.unified_diff(
            before, after, fromfile=f"a/{relative}", tofile=f"b/{relative}",
        ))
    (artifact_root / "source-only.patch").write_text("".join(source_patches), encoding="utf-8")
    manifest = {
        "grader_protocol_version": GRADER_PROTOCOL_VERSION,
        "task": task,
        "fixture": TASK_POLICIES[task]["fixture"],
        "runtime_result_authenticated": False,
        "adversarial_evaluation_validated": False,
        "aggregate_is_security_proof": False,
        "aggregate_interpretation": "diagnostic_only_false_positives_possible_until_separate_authority_boundary",
        "result_authentication_semantics": "not_authenticated_against_hostile_candidate_source",
        "integrity_semantics": "static_workspace_structure_and_protected_files_only",
        "candidate_tests_executed": False,
        "candidate_git_metadata_audited": False,
        "candidate_bytecode_replayed": False,
        "source_hashes": source_hashes,
        "statuses": {name: result.get(name) for name in (
            "functional_pass", "regression_pass", "integrity_pass", "scope_pass", "workflow_pass"
        )},
        "filesystem_isolation_verified": False,
        "network_isolation_verified": False,
    }
    (artifact_root / "replay-manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _make_grade_root(artifact_dir: Path | None, workspace: Path, baseline: Path) -> tuple[Path, bool]:
    if artifact_dir is None:
        return Path(tempfile.mkdtemp(prefix="pristine-grade-")), True
    parent = _absolute_without_resolving(artifact_dir)
    if _path_is_within(parent, workspace):
        raise ValueError("artifact_parent_inside_candidate_workspace")
    if _path_is_within(parent, baseline):
        raise ValueError("artifact_parent_inside_trusted_fixture")
    linked_parent = _existing_parent_link(parent)
    if linked_parent is not None:
        raise ValueError(f"unsafe_artifact_parent:{linked_parent}")
    parent.mkdir(parents=True, exist_ok=True)
    for problem in _check_parent_components(parent):
        raise ValueError(f"unsafe_artifact_parent:{problem}")
    grade_root = parent / f"pristine-grade-{uuid.uuid4().hex}"
    if _path_is_within(grade_root, _absolute_without_resolving(workspace)):
        raise ValueError("artifact_root_inside_candidate_workspace")
    if _path_is_within(grade_root, _absolute_without_resolving(baseline)):
        raise ValueError("artifact_root_inside_trusted_fixture")
    grade_root.mkdir(exist_ok=False)
    return grade_root, False


def _isolated_environment(grade_root: Path, replay: Path) -> dict[str, str]:
    home = grade_root / "grader-home"
    temporary = grade_root / "grader-tmp"
    home.mkdir(exist_ok=False)
    temporary.mkdir(exist_ok=False)
    return {
        "PATH": os.defpath,
        "PYTHONPATH": str(replay),
        "PYTHONNOUSERSITE": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONUTF8": "1",
        "HOME": str(home),
        "TMPDIR": str(temporary),
        "TEMP": str(temporary),
        "TMP": str(temporary),
    }


def _test_count(output: str) -> int | None:
    prefix = "PRISTINE_UNITTEST_RESULT="
    for line in reversed(output.splitlines()):
        if not line.startswith(prefix):
            continue
        try:
            summary = json.loads(line[len(prefix):])
        except (TypeError, json.JSONDecodeError):
            return None
        count = summary.get("actual_tests_run") if isinstance(summary, dict) else None
        if isinstance(count, int) and not isinstance(count, bool) and count >= 0:
            return count
        return None
    return None


_UNITTEST_RUNNER_BOOTSTRAP = r'''import json, sys, unittest
marker = "PRISTINE_UNITTEST_RESULT="
start_dir, pattern = sys.argv[1], sys.argv[2]
loader = unittest.TestLoader()
try:
    suite = loader.discover(start_dir=start_dir, pattern=pattern, top_level_dir=start_dir)
except BaseException as error:
    print(marker + json.dumps({"actual_tests_run": 0, "success": False,
                               "runner_error": type(error).__name__}, sort_keys=True))
    raise SystemExit(1)
result = unittest.TestResult()
runner_error = None
try:
    suite.run(result)
except BaseException as error:
    runner_error = type(error).__name__
success = (result.testsRun > 0 and result.wasSuccessful() and
           not loader.errors and runner_error is None)
print(marker + json.dumps({"actual_tests_run": result.testsRun, "success": success,
                           "runner_error": runner_error,
                           "loader_error_count": len(loader.errors)}, sort_keys=True))
raise SystemExit(0 if success else 1)
'''


def _trusted_unittest_command(start_dir: Path, pattern: str) -> list[str]:
    return [sys.executable, "-S", "-B", "-c", _UNITTEST_RUNNER_BOOTSTRAP, str(start_dir), pattern]


def _run_trusted_suite(
    command: list[str],
    *,
    cwd: Path,
    environment: dict[str, str],
    timeout_seconds: int,
) -> dict[str, Any]:
    """Run the fixed suite in a child process and return unauthenticated diagnostics.

    Candidate source is imported into this child's interpreter. It can mutate
    ``unittest``, forge the result marker, or terminate the process, so the
    returned test count and pass state are not an authority boundary.
    """
    try:
        process = subprocess.Popen(
            command,
            cwd=cwd,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
    except OSError as error:
        return {"passed": False, "reason": f"launch_failed:{type(error).__name__}",
                "output": "", "test_count": None, "cleanup_verified": True}

    timed_out = False
    output = ""
    failure_reason: str | None = None
    cleanup_verified = True
    try:
        stdout, stderr = process.communicate(timeout=timeout_seconds)
        output = f"{stdout}{stderr}"
    except subprocess.TimeoutExpired:
        timed_out = True
        failure_reason = "timed_out"
    except OSError as error:
        failure_reason = f"runner_io_failed:{type(error).__name__}"
    finally:
        try:
            stop_process_group(process, grace_seconds=0.5)
        except Exception as error:
            cleanup_verified = False
            failure_reason = f"process_group_cleanup_unverified:{type(error).__name__}"
            try:
                process.kill()
                process.wait(timeout=2)
            except (OSError, subprocess.TimeoutExpired):
                pass

    if cleanup_verified:
        try:
            stdout, stderr = process.communicate(timeout=2)
            output = f"{stdout}{stderr}"
        except (OSError, subprocess.TimeoutExpired) as error:
            failure_reason = f"runner_output_failed:{type(error).__name__}"
    else:
        output = ""

    count = _test_count(output)
    summary_success = False
    runner_error: str | None = None
    for line in reversed(output.splitlines()):
        if line.startswith("PRISTINE_UNITTEST_RESULT="):
            try:
                summary = json.loads(line.split("=", 1)[1])
                summary_success = isinstance(summary, dict) and summary.get("success") is True
                if isinstance(summary, dict):
                    runner_error = summary.get("runner_error")
            except (TypeError, json.JSONDecodeError):
                pass
            break
    passed = (
        failure_reason is None
        and cleanup_verified
        and not timed_out
        and process.returncode == 0
        and count is not None
        and count > 0
        and summary_success
    )
    if failure_reason is None and process.returncode != 0:
        failure_reason = f"tests_failed_exit_{process.returncode}"
    elif failure_reason is None and (count is None or count == 0):
        failure_reason = "empty_or_unreported_test_suite"
    return {"passed": passed, "reason": failure_reason, "output": output[-OUTPUT_LIMIT:],
            "test_count": count, "runner_success": summary_success,
            "runner_error": runner_error, "cleanup_verified": cleanup_verified}


def _write_trusted_fixture(replay: Path, trusted_files: dict[str, bytes]) -> None:
    replay.mkdir(parents=True, exist_ok=False)
    for relative, raw in sorted(trusted_files.items()):
        target = replay / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)


def _has_retained_files(root: Path) -> bool | None:
    try:
        pending = [root]
        root_scanned = False
        while pending:
            directory = pending.pop()
            try:
                with os.scandir(directory) as entries:
                    root_scanned = True
                    for entry in entries:
                        if entry.is_file(follow_symlinks=False):
                            return True
                        if entry.is_dir(follow_symlinks=False):
                            pending.append(Path(entry.path))
            except FileNotFoundError:
                if not root_scanned:
                    return False
                raise
        return False
    except OSError:
        return None


def _grade_in_root(
    workspace: Path,
    baseline: Path,
    task: str,
    grade_root: Path,
    trusted_files: dict[str, bytes],
    baseline_modes: dict[str, int],
    keep_artifacts: bool,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "grader_protocol_version": GRADER_PROTOCOL_VERSION,
        "task": task,
        "success": False,
        "aggregate_semantics": "all_five_gates_pristine_v1",
        "comparable_with_legacy": False,
        "functional_pass": None,
        "regression_pass": None,
        "integrity_pass": False,
        "scope_pass": None,
        "workflow_pass": None,
        "test_quality": "unmeasured",
        "private_holdout": False,
        "capability_evidence_eligible": False,
        "filesystem_isolation_verified": False,
        "network_isolation_verified": False,
        "git_metadata_audited": False,
        "candidate_tests_executed": False,
        "grader_skipped": True,
        "skip_reasons": [],
        "test_output": "",
        "behavioral_probe_stderr": "",
    }
    replay_sources: dict[str, bytes] = {}

    def finalize() -> dict[str, Any]:
        if keep_artifacts:
            result["artifact_path"] = str(grade_root)
            try:
                _write_replay_artifacts(grade_root, task, trusted_files, replay_sources, result)
                result["artifacts_retained"] = True
                result["artifacts_written"] = True
                result["partial_artifacts_retained"] = False
                result["artifact_retention"] = "retained"
            except Exception as error:
                result["artifacts_retained"] = False
                result["artifacts_written"] = False
                result["partial_artifacts_retained"] = _has_retained_files(grade_root)
                result["artifact_error"] = type(error).__name__
                result["artifact_retention"] = "failed"
        else:
            result["artifacts_retained"] = False
            result["artifacts_written"] = False
            result["partial_artifacts_retained"] = False
            result["artifact_retention"] = "not_requested"
        return _finish_result(result)

    candidate = _scan_candidate(workspace)
    result["candidate_inspection"] = {
        "problems": candidate["problems"],
        "git_metadata_audited": False,
        "bytecode_ignored": True,
    }
    if not candidate["passed"]:
        result["integrity_pass"] = False
        result["scope_pass"] = False
        result["skip_reasons"].append("unsafe_candidate_structure")
        return finalize()

    policy = TASK_POLICIES[task]
    allowed = _allowed_paths(task)
    source_paths = set(policy["source_files"])
    content_paths = source_paths | set(policy["test_files"]) | {"TASK.md"}
    candidate_bytes: dict[str, bytes] = {}
    candidate_modes = candidate["modes"]
    read_errors: list[str] = []
    for relative in sorted(content_paths):
        if relative not in candidate["files"]:
            continue
        try:
            path = _absolute_without_resolving(workspace) / relative
            if _check_parent_components(path):
                raise UnsafeWorkspaceError("unsafe_candidate_file_path_components")
            raw, metadata = _read_regular_file(
                path,
                max_bytes=MAX_CANDIDATE_FILE_BYTES,
            )
            candidate_bytes[relative] = raw
            candidate_modes[relative] = stat.S_IMODE(metadata.st_mode)
        except (OSError, UnsafeWorkspaceError) as error:
            read_errors.append(f"{relative}:{type(error).__name__}")
    replay_sources.update(
        (relative, candidate_bytes[relative])
        for relative in source_paths
        if relative in candidate_bytes
    )

    protected_changes: list[str] = []
    mode_changes: list[str] = []
    for relative, original in trusted_files.items():
        if relative in allowed:
            continue
        if candidate_bytes.get(relative) != original:
            protected_changes.append(relative)
        if relative not in candidate_modes or candidate_modes.get(relative) != baseline_modes[relative]:
            mode_changes.append(relative)
    for relative in allowed & set(trusted_files):
        if relative in candidate_bytes and candidate_modes.get(relative) != baseline_modes.get(relative):
            mode_changes.append(relative)
    integrity_pass = not read_errors and not protected_changes and not mode_changes
    result["integrity_pass"] = integrity_pass
    result["integrity_details"] = {
        "read_errors": read_errors,
        "protected_content_changes": sorted(protected_changes),
        "mode_changes": sorted(set(mode_changes)),
        "new_source_modes_not_replayed": sorted((source_paths - set(trusted_files)) & set(candidate_bytes)),
        "candidate_git_metadata_audited": False,
        "candidate_bytecode_replayed": False,
    }
    scope = _scope_result(task, candidate, trusted_files, candidate_bytes)
    result["scope_pass"] = scope["passed"]
    result["scope_details"] = scope
    if integrity_pass and candidate["passed"]:
        workflow = _workflow_result(task, candidate_bytes)
        result["workflow_pass"] = workflow["passed"]
        result["workflow_metrics"] = workflow
    else:
        result["workflow_pass"] = None
        result["skip_reasons"].append("workflow_static_read_skipped_integrity_failure")

    if not integrity_pass:
        result["skip_reasons"].append("integrity_gate_failed")
        return finalize()
    if not scope["passed"]:
        result["skip_reasons"].append("scope_gate_failed")
        return finalize()

    replay = grade_root / "workspace"
    _write_trusted_fixture(replay, trusted_files)
    for relative in policy["source_files"]:
        source_bytes = candidate_bytes.get(relative)
        target = replay / relative
        if source_bytes is None:
            if target.exists():
                target.unlink()
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source_bytes)

    environment = _isolated_environment(grade_root, replay)
    baseline_command = _trusted_unittest_command(replay / "tests", "test*.py")
    regression = _run_trusted_suite(
        baseline_command,
        cwd=replay,
        environment=environment,
        timeout_seconds=45,
    )
    result["regression_pass"] = regression["passed"]
    result["regression_details"] = {key: value for key, value in regression.items() if key != "output"}
    result["test_output"] = regression["output"]
    if not regression["cleanup_verified"]:
        result["functional_pass"] = None
        result["skip_reasons"].append("functional_probe_skipped_after_unverified_regression_cleanup")
        result["grader_skipped"] = True
        return finalize()

    suite = EVAL_SUITES_DIR / policy["suite"]
    probe_path = suite / "test_probe.py"
    try:
        probe_bytes, probe_metadata = _read_regular_file(probe_path, max_bytes=MAX_CANDIDATE_FILE_BYTES)
        if not probe_bytes.strip() or not stat.S_ISREG(probe_metadata.st_mode):
            raise ValueError("empty_or_invalid_trusted_probe")
    except (OSError, UnsafeWorkspaceError, ValueError) as error:
        result["functional_pass"] = False
        result["functional_details"] = {"reason": f"trusted_probe_unavailable:{type(error).__name__}", "test_count": None}
        result["skip_reasons"].append("functional_probe_unavailable")
    else:
        probe_command = _trusted_unittest_command(suite, "test_probe.py")
        functional = _run_trusted_suite(
            probe_command,
            cwd=replay,
            environment=environment,
            timeout_seconds=30,
        )
        result["functional_pass"] = functional["passed"]
        result["functional_details"] = {key: value for key, value in functional.items() if key != "output"}
        result["behavioral_probe_stderr"] = "" if functional["passed"] else functional["output"]

    result["grader_skipped"] = False
    if result.get("workflow_metrics") is not None:
        metrics = result["workflow_metrics"]
        result["required_tests_present"] = metrics["required_test_names_present"]
        result["divide_tests_present"] = metrics["required_test_names_present"] if task == "calculator_division" else None
    result["workspace_tests_passed"] = None
    result["unit_tests_passed"] = None
    result["baseline_tests_passed"] = result["regression_pass"]
    result["held_out_tests_passed"] = result["functional_pass"]
    result["behavioral_probe_passed"] = result["functional_pass"]
    result["changes_scoped"] = result["scope_pass"]
    result["unchanged_helpers"] = scope["preserved_helpers_pass"]
    result["changed_files"] = scope["changed_allowed_files"]

    return finalize()


def _finish_result(result: dict[str, Any]) -> dict[str, Any]:
    gates = ("functional_pass", "regression_pass", "integrity_pass", "scope_pass", "workflow_pass")
    result["success"] = all(result.get(gate) is True for gate in gates)
    result["aggregate_semantics"] = "all_five_gates_pristine_v1"
    result["comparable_with_legacy"] = False
    result["test_quality"] = "unmeasured"
    result["private_holdout"] = False
    result["capability_evidence_eligible"] = False
    result["filesystem_isolation_verified"] = False
    result["network_isolation_verified"] = False
    result["runtime_result_authenticated"] = False
    result["adversarial_evaluation_validated"] = False
    result["aggregate_is_security_proof"] = False
    result["aggregate_interpretation"] = "diagnostic_only_false_positives_possible_until_separate_authority_boundary"
    result["result_authentication_semantics"] = "not_authenticated_against_hostile_candidate_source"
    result["integrity_semantics"] = "static_workspace_structure_and_protected_files_only"
    result["candidate_tests_executed"] = False
    result["git_metadata_audited"] = False
    result.setdefault("workspace_tests_passed", None)
    result.setdefault("unit_tests_passed", None)
    result.setdefault("baseline_tests_passed", result.get("regression_pass"))
    result.setdefault("held_out_tests_passed", result.get("functional_pass"))
    result.setdefault("behavioral_probe_passed", result.get("functional_pass"))
    result.setdefault("required_tests_present", None)
    result.setdefault("divide_tests_present", None)
    result.setdefault("changes_scoped", result.get("scope_pass"))
    result.setdefault("unchanged_helpers", None)
    result.setdefault("changed_files", [])
    result.setdefault("partial_artifacts_retained", False)
    return result


def grade_pristine_workspace(
    workspace: Path,
    baseline: Path,
    task: str = "calculator_division",
    artifact_dir: Path | None = None,
) -> dict[str, Any]:
    """Grade allowlisted candidate source replayed into a trusted fresh fixture.

    ``artifact_dir`` is a parent sink. A unique child is created without
    overwriting prior evidence. If omitted, the replay is temporary.
    """
    canonical = _canonical_task(task)
    result: dict[str, Any] = {
        "grader_protocol_version": GRADER_PROTOCOL_VERSION,
        "task": canonical,
        "success": False,
        "functional_pass": None,
        "regression_pass": None,
        "integrity_pass": False,
        "scope_pass": None,
        "workflow_pass": None,
        "skip_reasons": [],
        "artifacts_retained": False,
        "artifacts_written": False,
        "artifact_retention": "failed" if artifact_dir is not None else "not_requested",
    }
    try:
        manifest = _load_manifest()
        trusted_files, baseline_modes = _verify_fixture(canonical, baseline, manifest)
        workspace_abs = _absolute_without_resolving(workspace)
        grade_root, temporary = _make_grade_root(artifact_dir, workspace_abs, _expected_fixture(canonical, baseline))
    except (OSError, ValueError, UnsafeWorkspaceError) as error:
        result.update({
            "integrity_pass": False,
            "scope_pass": None,
            "workflow_pass": None,
            "grader_skipped": True,
            "skip_reasons": [f"preflight_failed:{type(error).__name__}:{str(error)[:160]}"],
            "artifact_retention": "failed" if artifact_dir is not None else "not_requested",
        })
        return _finish_result(result)

    try:
        result = _grade_in_root(
            workspace_abs,
            _expected_fixture(canonical, baseline),
            canonical,
            grade_root,
            trusted_files,
            baseline_modes,
            not temporary,
        )
    except (OSError, ValueError, UnsafeWorkspaceError) as error:
        result.update({
            "integrity_pass": False,
            "scope_pass": None,
            "workflow_pass": None,
            "grader_skipped": True,
            "skip_reasons": [f"grader_failed_closed:{type(error).__name__}:{str(error)[:160]}"],
            "artifact_retention": "failed" if artifact_dir is not None else "not_requested",
        })
        if not temporary and grade_root.exists():
            result["artifact_path"] = str(grade_root)
            result["partial_artifacts_retained"] = _has_retained_files(grade_root)
        _finish_result(result)
    finally:
        if temporary:
            try:
                shutil.rmtree(grade_root)
            except OSError as error:
                result["artifact_path"] = str(grade_root)
                result["artifact_retention"] = "failed"
                result["artifact_cleanup_error"] = type(error).__name__
                result["partial_artifacts_retained"] = _has_retained_files(grade_root)
    return result
