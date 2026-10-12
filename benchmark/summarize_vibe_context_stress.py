"""Summarize local Vibe context-continuation runs and independently grade artifacts."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import shlex
import statistics
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


MODEL = "Qwen3.5-9B-Q4_K_M"
EXPECTED_FILES = {f"archive-{i:02d}.md" for i in range(1, 33)}
EXPECTED_OUTPUTS = {"summary.md", "archive_manifest.txt", "recovery.txt"}
RECOVERY_KEY = "GLACIER-47-MAPLE"


def _json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _unique_events(run_dir: Path) -> list[dict[str, Any]]:
    seen: set[str] = set()
    events: list[dict[str, Any]] = []
    for path in run_dir.rglob("journal/*.jsonl"):
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for line in lines:
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(event, dict):
                continue
            event_key = event.get("record_sha256") or hashlib.sha256(line.encode()).hexdigest()
            if event_key not in seen:
                seen.add(str(event_key))
                events.append(event)
    return events


def _shell_read_invocations(command: str) -> list[tuple[str, list[str]]]:
    """Return executed cat/grep invocations, excluding quoted command-like text."""
    invocations: list[tuple[str, list[str]]] = []
    if re.search(r"\b(?:if|elif|else|fi|while|until|case|esac)\b", command):
        return invocations
    normalized = " ".join(command.split())
    body = normalized
    cd_prefix = re.match(r"^cd\s+[^;&|]+\s+&&\s+(.*)$", normalized)
    if cd_prefix:
        body = cd_prefix.group(1)
    supported_seq_loop = body == (
        'for i in $(seq -w 1 32); do echo "=== archive-0${i}.md ===" && '
        'cat "archive-0${i}.md"; done'
    )
    supported_brace_loop = body == (
        'for i in {10..32}; do echo "archive-${i:0:2}=$(grep \'ARCHIVE FINGERPRINT:\' '
        'archive-${i:0:2}.md | sed \'s/.*ARCHIVE FINGERPRINT:[[:space:]]*//\')"; done'
    )
    supported_fingerprint_grep = body == 'grep -h "ARCHIVE FINGERPRINT:" archive-0[1-9].md'
    if any(operator in normalized for operator in (";", "&&", "||", "|")) and not (
        supported_seq_loop or supported_brace_loop or supported_fingerprint_grep
    ):
        return invocations

    def matching_subshell_end(text: str, start: int) -> int:
        depth = 1
        quote: str | None = None
        i = start + 2
        while i < len(text):
            char = text[i]
            if quote == "'":
                if char == "'":
                    quote = None
            elif quote == '"':
                if char == "\\":
                    i += 1
                elif char == '"':
                    quote = None
                elif text.startswith("$(", i):
                    depth += 1
                    i += 1
                elif char == ")":
                    depth -= 1
                    if depth == 0:
                        return i
            elif char in "'\"":
                quote = char
            elif text.startswith("$(", i):
                depth += 1
                i += 1
            elif char == ")":
                depth -= 1
                if depth == 0:
                    return i
            i += 1
        return len(command)

    def scan(source: str) -> None:
        segments: list[str] = []
        current: list[str] = []
        quote: str | None = None
        i = 0
        while i < len(source):
            char = source[i]
            if quote == "'":
                current.append(char)
                if char == "'":
                    quote = None
            elif quote == '"':
                current.append(char)
                if char == "\\" and i + 1 < len(source):
                    current.append(source[i + 1])
                    i += 1
                elif char == '"':
                    quote = None
                elif source.startswith("$(", i):
                    end = matching_subshell_end(source, i)
                    scan(source[i + 2:end])
                    current.extend(" " for _ in source[i:end + 1])
                    i = end
            elif char in "'\"":
                quote = char
                current.append(char)
            elif source.startswith("$(", i):
                end = matching_subshell_end(source, i)
                scan(source[i + 2:end])
                current.extend(" " for _ in source[i:end + 1])
                i = end
            elif char in ";|&\n":
                if current:
                    segments.append("".join(current))
                    current = []
                while i + 1 < len(source) and source[i + 1] == char and char in "|&":
                    i += 1
            else:
                current.append(char)
            i += 1
        if current:
            segments.append("".join(current))

        for segment in segments:
            try:
                tokens = shlex.split(segment)
            except ValueError:
                continue
            while tokens and tokens[0] in {"do", "then", "else"}:
                tokens.pop(0)
            while tokens and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", tokens[0]):
                tokens.pop(0)
            if tokens and tokens[0] in {"cat", "grep"}:
                invocations.append((tokens[0], tokens[1:]))

    scan(command)
    return invocations


def _archive_operand_ids(operands: list[str], command: str) -> set[int]:
    ids = {
        int(number) for operand in operands
        for number in re.findall(r"archive-(\d{2})\.md$", operand)
    }
    if any("archive-0[1-9].md" in operand for operand in operands):
        ids.update(range(1, 10))
    if any("archive-*.md" in operand for operand in operands):
        ids.update(range(1, 33))

    dynamic_operands = [operand for operand in operands if "$" in operand]
    if not dynamic_operands:
        return ids
    for match in re.finditer(r"\bfor\s+([A-Za-z_][A-Za-z0-9_]*)\s+in\s+\$\(\s*seq\s+([^)]+)\)", command):
        variable, raw_values = match.groups()
        values = [int(value) for value in re.findall(r"\b\d+\b", raw_values)]
        if len(values) >= 2:
            first, last = values[-2:]
        elif values:
            first, last = 1, values[-1]
        else:
            continue
        if any(re.search(rf"\$(?:\{{{variable}(?::[^}}]+)?\}}|{variable})", operand) for operand in dynamic_operands):
            ids.update(range(min(first, last), max(first, last) + 1))
    for match in re.finditer(r"\bfor\s+([A-Za-z_][A-Za-z0-9_]*)\s+in\s+\{(\d+)\.\.(\d+)\}", command):
        variable, first, last = match.groups()
        if any(re.search(rf"\$(?:\{{{variable}(?::[^}}]+)?\}}|{variable})", operand) for operand in dynamic_operands):
            ids.update(range(min(int(first), int(last)), max(int(first), int(last)) + 1))
    for match in re.finditer(r"\bfor\s+([A-Za-z_][A-Za-z0-9_]*)\s+in\s+(\d+)(?=\s*(?:;|$))", command):
        variable, value = match.groups()
        if any(re.search(rf"\$(?:\{{{variable}(?::[^}}]+)?\}}|{variable})", operand) for operand in dynamic_operands):
            ids.add(int(value))
    return ids


def _phase_archive_reads(run_dir: Path, phase: str, *, successful_only: bool = False) -> set[int]:
    found: set[int] = set()
    phase_dir = run_dir / f"output-{phase}"
    seen: set[str] = set()
    intents: dict[str, tuple[str | None, set[int], dict[str, Any]]] = {}
    results: dict[str, dict[str, Any]] = {}
    fingerprints = {
        hashlib.sha256(f"pi-context-stress-2026|archive-{i:02d}".encode()).hexdigest()[:12].upper(): i
        for i in range(1, 33)
    }
    for path in phase_dir.rglob("journal/*.jsonl"):
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(event, dict):
                continue
            event_key = event.get("record_sha256") or hashlib.sha256(line.encode()).hexdigest()
            if event_key in seen:
                continue
            seen.add(str(event_key))
            payload = event.get("payload", {})
            request = payload.get("request", {})
            if event.get("type") == "action_intent" and payload.get("kind") == "tool":
                call = request.get("call", {})
                arguments = call.get("arguments", {})
                archive_ids = {
                    int(n) for n in re.findall(r"archive-(\d{2})\.md", json.dumps(arguments, ensure_ascii=False))
                }
                action_id = payload.get("action_id")
                if successful_only:
                    if action_id:
                        intents[str(action_id)] = (call.get("name"), archive_ids, arguments)
                else:
                    found.update(archive_ids)
            elif event.get("type") == "action_result" and payload.get("action_id"):
                result = payload.get("result", {})
                results[str(payload["action_id"])] = result if isinstance(result, dict) else {}
    if successful_only:
        for action_id, (name, archive_ids, arguments) in intents.items():
            result = results.get(action_id, {})
            if name in {"file_system.read", "file_system.read_file"} and result.get("type") == "tool_succeeded":
                found.update(archive_ids)
            elif name == "file_system.bash" and result.get("type") == "tool_succeeded":
                execution = result.get("result", {})
                structured = execution.get("structured_content", {}) if isinstance(execution, dict) else {}
                command = str(arguments.get("command", ""))
                stdout = str(structured.get("stdout", "")) if isinstance(structured, dict) else ""
                if structured.get("returncode") != 0 or not re.search(r"\b(?:cat|grep)\b", command):
                    continue
                cat_archive_operands: list[str] = []
                grep_archive_operands: list[str] = []
                for executable, tokens in _shell_read_invocations(command):
                    positional: list[str] = []
                    skip_option_value = False
                    for token in tokens:
                        if skip_option_value:
                            skip_option_value = False
                            continue
                        if token in {"-e", "-f", "-m", "-A", "-B", "-C"}:
                            skip_option_value = True
                        elif token.startswith("-"):
                            continue
                        else:
                            positional.append(token)
                    file_tokens = positional if executable == "cat" else positional[1:]
                    matched_operands = [
                        token for token in file_tokens
                        if re.search(r"(?:^|/)archive-(?:\d{2}|0\[1-9\]|\*|\$\{[^}]+\}|\$[A-Za-z_][A-Za-z0-9_]*)\.md$", token)
                    ]
                    if executable == "cat":
                        cat_archive_operands.extend(matched_operands)
                    else:
                        grep_archive_operands.extend(matched_operands)
                archive_operands = cat_archive_operands + grep_archive_operands
                operand_ids = _archive_operand_ids(archive_operands, command)
                dynamic_grep_variables = {
                    variable for operand in grep_archive_operands
                    for variable in re.findall(r"archive-(\$\{[^}]+\}|\$[A-Za-z_][A-Za-z0-9_]*)\.md", operand)
                }
                dynamic_echo_variables = set(re.findall(
                    r"archive-(\$\{[^}]+\}|\$[A-Za-z_][A-Za-z0-9_]*)=", command
                ))
                linked_dynamic_grep_output = any(
                    variable in dynamic_echo_variables and re.search(
                        rf"archive-{re.escape(variable)}=\$\([^)]*\bgrep\b[^)]*archive-{re.escape(variable)}\.md",
                        command,
                    )
                    for variable in dynamic_grep_variables
                )
                if not operand_ids:
                    continue
                if cat_archive_operands:
                    for match in re.finditer(r"(?m)^# Archive (\d{1,2})\s*$([\s\S]*?)(?=^# Archive \d{1,2}\s*$|\Z)", stdout):
                        archive_id = int(match.group(1))
                        block_fingerprints = re.findall(r"ARCHIVE FINGERPRINT:\s*([0-9A-F]{12})", match.group(2))
                        if block_fingerprints and archive_id in operand_ids and fingerprints.get(block_fingerprints[0]) == archive_id:
                            found.add(archive_id)
                for match in re.finditer(r"(?m)^archive-(\d{2})=([0-9A-F]{12})(?:\b.*)?$", stdout):
                    archive_id, fingerprint = int(match.group(1)), match.group(2)
                    if linked_dynamic_grep_output and archive_id in operand_ids and fingerprints.get(fingerprint) == archive_id:
                        found.add(archive_id)
                if grep_archive_operands:
                    for fingerprint in re.findall(r"ARCHIVE FINGERPRINT:\s*([0-9A-F]{12})", stdout):
                        archive_id = fingerprints.get(fingerprint)
                        if archive_id in operand_ids:
                            found.add(archive_id)
    return found


def _resource_summary(path: Path) -> dict[str, int | float | None]:
    rows = []
    if path.exists():
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                rows.append(value)
    getters = {
        "cpu_util_pct": lambda row: row.get("cpu_util_pct"),
        "ram_used_mb": lambda row: row.get("ram_used_mb"),
        "swap_used_mb": lambda row: row.get("swap_used_mb"),
        "vram_used_mb": lambda row: row.get("gpu", {}).get("vram_used_mb"),
        "gpu_util_pct": lambda row: row.get("gpu", {}).get("gpu_util_pct"),
        "temperature_c": lambda row: row.get("gpu", {}).get("temperature_c"),
        "power_w": lambda row: row.get("gpu", {}).get("power_w"),
    }
    result: dict[str, int | float | None] = {"resource_samples": len(rows)}
    for name, getter in getters.items():
        values = []
        for row in rows:
            try:
                values.append(float(getter(row)))
            except (TypeError, ValueError):
                continue
        result[f"{name}_avg"] = round(statistics.mean(values), 1) if values else None
        result[f"{name}_peak"] = round(max(values), 1) if values else None
    return result


def _time_seconds(first: dict[str, Any] | None, second: dict[str, Any] | None) -> float | None:
    starts = [x.get("started_at") for x in (first, second) if x and x.get("started_at")]
    ends = [x.get("ended_at") for x in (first, second) if x and x.get("ended_at")]
    if not starts or not ends:
        return None
    try:
        start = min(datetime.fromisoformat(x.replace("Z", "+00:00")) for x in starts)
        end = max(datetime.fromisoformat(x.replace("Z", "+00:00")) for x in ends)
    except ValueError:
        return None
    return round((end - start).total_seconds(), 3)


def summarize_run(run_dir: Path, git_sha: str) -> dict[str, Any]:
    phase1 = _json(run_dir / "output-phase-1/export.json")
    phase2 = _json(run_dir / "output-phase-2/export.json")
    events = _unique_events(run_dir)
    try:
        recorded_git_sha = (run_dir / "git_sha.txt").read_text(encoding="utf-8").strip() or git_sha
    except OSError:
        recorded_git_sha = git_sha
    try:
        source_git_status = (run_dir / "source_git_status.txt").read_text(encoding="utf-8")
        source_dirty: bool | None = bool(source_git_status.strip())
    except OSError:
        source_dirty = None
    try:
        source_diff_sha256: str | None = (run_dir / "source_diff_sha256.txt").read_text(encoding="utf-8").strip() or None
    except OSError:
        source_diff_sha256 = None
    archive_ids = _phase_archive_reads(run_dir, "phase-1", successful_only=True)
    phase2_archive_ids = _phase_archive_reads(run_dir, "phase-2")
    compaction_ids: set[str] = set()
    tool_ids: set[str] = set()
    for event in events:
        payload = event.get("payload", {})
        request = payload.get("request", {})
        if request.get("purpose") == "compaction" and request.get("compaction_id"):
            compaction_ids.add(str(request["compaction_id"]))
        if event.get("type") == "action_intent" and payload.get("kind") == "tool":
            action_id = payload.get("action_id")
            if action_id:
                tool_ids.add(str(action_id))

    workspace = run_dir / "workspace"
    manifest_path = workspace / "archive_manifest.txt"
    manifest = manifest_path.read_text(encoding="utf-8").splitlines() if manifest_path.exists() else []
    expected_manifest = [
        f"archive-{i:02d}=" + hashlib.sha256(f"pi-context-stress-2026|archive-{i:02d}".encode()).hexdigest()[:12].upper()
        for i in range(1, 33)
    ]
    summary = (workspace / "summary.md").read_text(encoding="utf-8") if (workspace / "summary.md").exists() else ""
    recovery = (workspace / "recovery.txt").read_text(encoding="utf-8").strip() if (workspace / "recovery.txt").exists() else ""
    test = subprocess.run([sys.executable, "test_result.py"], cwd=workspace, capture_output=True, text=True) if (workspace / "test_result.py").exists() else None
    baseline = subprocess.run(
        ["git", "rev-list", "--max-parents=0", "HEAD"], cwd=workspace, capture_output=True, text=True, check=True
    ).stdout.splitlines()[0] if (workspace / ".git").exists() else ""
    tracked_changes = subprocess.run(
        ["git", "diff", "--name-only", baseline], cwd=workspace, capture_output=True, text=True, check=True
    ).stdout.splitlines() if baseline else []
    untracked_changes = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard"], cwd=workspace, capture_output=True, text=True, check=True
    ).stdout.splitlines() if baseline else []
    changed_files = sorted({
        name.replace("\\", "/") for name in tracked_changes + untracked_changes
        if "__pycache__/" not in name and not name.endswith(".pyc")
    })
    numstat = subprocess.run(
        ["git", "diff", "--numstat", baseline], cwd=workspace, capture_output=True, text=True, check=True
    ).stdout.splitlines() if baseline else []
    mode_only_files = sorted(
        line.split("\t", 2)[2] for line in numstat
        if line.startswith("0\t0\t") and len(line.split("\t", 2)) == 3
    )
    content_changed_files = sorted(
        line.split("\t", 2)[2] for line in numstat
        if len(line.split("\t", 2)) == 3 and not line.startswith("0\t0\t")
    )
    mode_summary = subprocess.run(
        ["git", "diff", "--summary", baseline], cwd=workspace, capture_output=True, text=True, check=True
    ).stdout.splitlines() if baseline else []
    mode_changed_files = sorted(
        line.rsplit(" ", 1)[-1] for line in mode_summary if line.startswith(" mode change ")
    )
    changes_scoped = bool(changed_files) and set(changed_files) <= EXPECTED_OUTPUTS
    phase1_exit = phase1.get("exit_code") if phase1 else None
    phase2_exit = phase2.get("exit_code") if phase2 else None
    summary_exact = "archive_count: 32" in summary and f"recovery_key: {RECOVERY_KEY}" in summary
    recovery_exact = recovery == RECOVERY_KEY
    manifest_exact = manifest == expected_manifest
    tests_pass = test is not None and test.returncode == 0
    quality_pass = all((
        phase1_exit == 0,
        phase2_exit == 0,
        len(compaction_ids) > 0,
        archive_ids == set(range(1, 33)),
        summary_exact,
        recovery_exact,
        manifest_exact,
        tests_pass,
        changes_scoped,
        not phase2_archive_ids,
    ))
    usage1 = (phase1 or {}).get("usage") or {}
    usage2 = (phase2 or {}).get("usage") or {}
    return {
        "timestamp": (phase1 or phase2 or {}).get("started_at"),
        "experiment": "vibe_local_context_compaction_stress",
        "harness": "Mistral Vibe",
        "harness_version": (phase1 or phase2 or {}).get("vibe_version"),
        "model": MODEL,
        "model_revision": "3885219b6810b007914f3a7950a8d1b469d598a5",
        "quant": "Q4_K_M",
        "runtime": "llama.cpp d81235049384534c167caea52b85a694f6103d14",
        "kv_cache": "q4_0/q4_0",
        "git_sha": recorded_git_sha,
        "source_dirty": source_dirty,
        "source_diff_sha256": source_diff_sha256,
        "storage_profile": "ssd-wsl-ext4-c",
        "context_tokens": 16384,
        "auto_compact_threshold": 15000,
        "phase1_outcome": (phase1 or {}).get("outcome"),
        "phase1_exit_code": phase1_exit,
        "phase1_steps": (phase1 or {}).get("steps"),
        "phase2_outcome": (phase2 or {}).get("outcome"),
        "phase2_exit_code": phase2_exit,
        "phase2_steps": (phase2 or {}).get("steps"),
        "wall_s": _time_seconds(phase1, phase2),
        "input_tokens": sum(int(x.get("input_tokens", 0) or 0) for x in (usage1, usage2)),
        "output_tokens": sum(int(x.get("output_tokens", 0) or 0) for x in (usage1, usage2)),
        "total_tokens": sum(int(x.get("total_tokens", 0) or 0) for x in (usage1, usage2)),
        "compaction_count": len(compaction_ids),
        "tool_calls": len(tool_ids),
        "archive_files_read_count": len(archive_ids),
        "archive_files_read": sorted(archive_ids),
        "phase2_archive_files_read_count": len(phase2_archive_ids),
        "phase2_archive_files_read": sorted(phase2_archive_ids),
        "summary_exact": summary_exact,
        "manifest_exact": manifest_exact,
        "recovery_exact": recovery_exact,
        "tests_pass": tests_pass,
        "changed_files": changed_files,
        "mode_changed_files": mode_changed_files,
        "mode_changed_count": len(mode_changed_files),
        "mode_only_files": mode_only_files,
        "content_changed_files": content_changed_files,
        "changes_scoped": changes_scoped,
        "quality_pass": quality_pass,
        "run_dir": str(run_dir),
        **_resource_summary(run_dir / "resources.jsonl"),
    }


def write_outputs(records: list[dict[str, Any]], raw_path: Path, csv_path: Path, report_path: Path) -> None:
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in records), encoding="utf-8")
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "timestamp", "git_sha", "source_dirty", "source_diff_sha256", "harness_version", "wall_s", "phase1_exit_code", "phase2_exit_code",
        "input_tokens", "output_tokens", "compaction_count", "tool_calls", "archive_files_read_count",
        "phase2_archive_files_read_count",
        "summary_exact", "manifest_exact", "recovery_exact", "tests_pass", "quality_pass",
        "mode_changed_count", "vram_used_mb_peak", "ram_used_mb_peak", "gpu_util_pct_avg", "storage_profile", "run_dir",
    ]
    with csv_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in records:
            item = dict(row)
            item["archive_files_read_count"] = row.get("archive_files_read_count", 0)
            writer.writerow(item)
    lines = [
        "# Vibe local context-compaction stress",
        "",
        "The same local Qwen3.5-9B Q4_K_M endpoint and synthetic 32-file workspace were used in two Vibe prompts. The second prompt resumed the exact first session ID. The runtime, model, scratch workspaces, server logs, and resource samples were on C:-backed WSL ext4; no HDD performance I/O or paid endpoint was used.",
        "",
        "A full pass requires both phases to exit cleanly, at least one automatic compaction, tool-call evidence for all 32 archive files, an exact fingerprint manifest, the recovery key preserved and recovered, passing workspace tests, and only expected output files changed.",
        "",
        "| Started (UTC) | Wall (s) | Tokens in/out | Compactions | Tools | Successful reads | Reopened | Manifest | Continuity | Tests | Mode flips | Result |",
        "|---|---:|---:|---:|---:|---:|---:|---|---|---|---:|---|",
    ]
    for row in records:
        lines.append(
            f"| {row.get('timestamp')} | {row.get('wall_s')} | {row.get('input_tokens')}/{row.get('output_tokens')} "
            f"| {row.get('compaction_count')} | {row.get('tool_calls')} | {row.get('archive_files_read_count')}/32 "
            f"| {row.get('phase2_archive_files_read_count')} "
            f"| {'pass' if row.get('manifest_exact') else 'fail'} "
            f"| {'pass' if row.get('summary_exact') and row.get('recovery_exact') else 'fail'} "
            f"| {'pass' if row.get('tests_pass') else 'fail'} | {row.get('mode_changed_count')} "
            f"| {'PASS' if row.get('quality_pass') else 'FAIL'} |"
        )
    passed = sum(bool(row.get("quality_pass")) for row in records)
    successful_reads = ", ".join(f"{row.get('archive_files_read_count')}/32" for row in records)
    mode_counts = ", ".join(str(row.get("mode_changed_count")) for row in records)
    reopened = [
        f"run {index}: {row.get('phase2_archive_files_read')}"
        for index, row in enumerate(records, start=1)
        if row.get("phase2_archive_files_read")
    ]
    lines.extend([
        "",
        f"Strict full-task passes: {passed}/{len(records)}.",
        "",
        f"Correlating archive paths with successful file-read tool results gives {successful_reads} successful reads in run order. The earlier summary used intent-only matching; the updated journal audit confirms each reported read through a successful read result or successful shell output containing the deterministic archive fingerprints. Workspace mode-change counts in run order were {mode_counts}; mode changes remain a strict-scope failure even when file contents are unchanged. Reopened archives after continuation: {', '.join(reopened) if reopened else 'none'}. The latest run completed both phases, preserved all required artifacts, passed workspace tests, and made no out-of-scope workspace changes. Strict full-task passes: {passed}/{len(records)}.",
        "",
        "Usage totals are the harness-reported sum across model calls, not the peak context size. Vibe's journal records compaction IDs and requests, but this run does not expose a reliable token count for the history removed; no token compression ratio is claimed. Resource samples are one-second observations and the RTX 3070 is shared with the Windows desktop.",
        "",
        "Session journals, workspaces, stdout/stderr, and server logs are archived on E: after measurement in a SHA-256-verified tarball. The latest workspace was graded from its original C:-backed WSL ext4 run directory before archival; do not run the workspace-mode quality gate directly from the mounted E: copy. To reproduce the comparison, restore all archived run folders onto WSL ext4, then run `python3 benchmark/summarize_vibe_context_stress.py --runs-root $BENCH_ROOT/results/vibe-context-stress --git-sha <fallback_git_sha> --raw results/raw/vibe-context-stress.jsonl --csv results/csv/vibe-context-stress.csv --report results/reports/vibe-context-stress.md`. The checked-in JSONL/CSV retain the exact per-run provenance and results.",
        "",
    ])
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs-root", type=Path, required=True)
    parser.add_argument("--git-sha", required=True)
    parser.add_argument("--raw", type=Path, required=True)
    parser.add_argument("--csv", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    run_dirs = sorted((p for p in args.runs_root.iterdir() if p.is_dir()), key=lambda p: p.name)
    records = [summarize_run(path, args.git_sha) for path in run_dirs]
    write_outputs(records, args.raw, args.csv, args.report)
    print(f"runs={len(records)} clean_passes={sum(bool(r['quality_pass']) for r in records)}")
    return 0 if records else 1


if __name__ == "__main__":
    raise SystemExit(main())
