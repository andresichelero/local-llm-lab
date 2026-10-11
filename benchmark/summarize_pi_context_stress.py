"""Summarize Pi context-stress records and validate actual archive reads."""
from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path


def read_archive_ids(record: dict) -> list[int]:
    session_file = record.get("session_stats", {}).get("sessionFile")
    if not session_file or not Path(session_file).is_file():
        return []
    found: set[int] = set()
    with Path(session_file).open(encoding="utf-8") as stream:
        for line in stream:
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            message = entry.get("message", {})
            for item in message.get("content", []) or []:
                if not isinstance(item, dict) or item.get("type") != "toolCall":
                    continue
                arguments = item.get("arguments", {}) or {}
                for value in (arguments.get("path", ""), arguments.get("command", "")):
                    found.update(int(number) for number in re.findall(r"archive-(\d{2})\.md", str(value)))
    return sorted(found)


def quality_pass(record: dict, archive_ids: list[int]) -> bool:
    return bool(
        record.get("source_tree_dirty") is False
        and record.get("summary_exists")
        and record.get("manifest_exact") is True
        and record.get("key_preserved_in_summary")
        and record.get("recovery_exact_match")
        and record.get("test_exit_code") == 0
        and record.get("compaction_event_count", 0) > 0
        and len(archive_ids) == 32
    )


def load_records(paths: list[Path]) -> list[dict]:
    records = []
    for path in paths:
        if not path.exists():
            continue
        with path.open(encoding="utf-8") as stream:
            for line in stream:
                if not line.strip():
                    continue
                record = json.loads(line)
                record["archive_files_read"] = read_archive_ids(record)
                record["archive_files_read_count"] = len(record["archive_files_read"])
                record["quality_pass"] = quality_pass(record, record["archive_files_read"])
                records.append(record)
    return sorted(records, key=lambda item: item.get("timestamp", ""))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw", type=Path, action="append", required=True, help="JSONL result files; may be repeated")
    parser.add_argument("--csv", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    records = load_records(args.raw)
    fields = [
        "timestamp", "git_sha", "elapsed_ms", "compaction_event_count", "tool_call_start_count",
        "archive_files_read_count", "archive_files_read", "summary_exists", "manifest_exact",
        "key_preserved_in_summary", "recovery_exact_match", "test_exit_code", "source_tree_dirty",
        "quality_pass", "storage_profile", "context_after_phase_1", "context_after_phase_2",
        "compaction_tokens_before", "compaction_summary_chars",
    ]
    args.csv.parent.mkdir(parents=True, exist_ok=True)
    with args.csv.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for record in records:
            row = dict(record)
            row["archive_files_read"] = ";".join(f"{number:02d}" for number in record["archive_files_read"])
            samples = {item.get("label"): item.get("usage", {}).get("tokens") for item in record.get("context_samples", [])}
            row["context_after_phase_1"] = samples.get("after_phase_1")
            row["context_after_phase_2"] = samples.get("after_phase_2")
            row["compaction_tokens_before"] = ";".join(
                str(item.get("tokensBefore")) for item in record.get("compaction_events", [])
            )
            row["compaction_summary_chars"] = ";".join(
                str(item.get("summaryChars")) for item in record.get("compaction_events", [])
            )
            writer.writerow(row)

    lines = [
        "# Pi local context-compaction stress",
        "",
        "This is a functional stress probe, not a throughput ranking. It ran Pi SDK 1.1.0 with Qwen3.5-9B Q4_K_M through llama.cpp on the RTX 3070, using a 16,384-token context. Auto-compaction was enabled with a 2,048-token reserve and 4,096 recent-token retention. Scratch workspaces, sessions, model, server, and raw run files were on the C:-hosted WSL2 SSD; no HDD benchmark I/O was used.",
        "",
        "Success requires: at least one automatic compaction, all 32 archive files evidenced in actual Pi tool-call transcripts, an exact 32-line fingerprint manifest, the exact recovery key in the summary and continuation file, a passing workspace test, and clean source provenance.",
        "",
        "| Run (UTC) | Time (s) | Compactions | Tools | Archive files read | Summary / key | Manifest | Continuation | Test | Result |",
        "|---|---:|---:|---:|---:|---|---|---|---:|---|",
    ]
    for record in records:
        run = record.get("timestamp", "unknown")
        lines.append(
            f"| {run} | {record.get('elapsed_ms', 0) / 1000:.1f} | {record.get('compaction_event_count', 0)} "
            f"| {record.get('tool_call_start_count', 0)} | {record['archive_files_read_count']}/32 "
            f"| {'pass' if record.get('summary_exists') and record.get('key_preserved_in_summary') else 'fail'} "
            f"| {'pass' if record.get('manifest_exact') else 'fail'} "
            f"| {'pass' if record.get('recovery_exact_match') else 'fail'} "
            f"| {record.get('test_exit_code')} | {'PASS' if record['quality_pass'] else 'FAIL'} |"
        )
    passed = sum(bool(record["quality_pass"]) for record in records)
    lines.extend([
        "",
        f"Full quality passes: {passed}/{len(records)}. Earlier attempts remain in the raw data and are not omitted from this assessment.",
        "",
        "The first run read all 32 files and passed the summary test, but failed recovery and then exposed a cleanup API error. Later runs preserved parts of the state but failed the full contract; transcript inspection rejected an apparent pass that had read only 7/32 archives. The fourth run read 15/32 files, overflowed the configured context and produced neither summary nor manifest. The fifth run lasted 225.7 seconds, made 31 read-tool calls and covered 31/32 archive files, but produced no summary or manifest; its workspace tests failed. Pi reported 16,828 tokens after phase 1 and 16,906 after phase 2 against a 16,384-token context (102.7% and 103.2%). It emitted nine compaction start events, yet context remained over limit and no continuation key was recovered.",
        "",
        "This machine-specific sample shows that compaction events alone do not establish task continuity. Across five runs, none passed the full independent quality contract. The existing records include context estimates, pre-compaction context counts and summary character lengths, but they do not measure the tokenized content removed by each compaction, so a token compression ratio cannot be calculated reliably. Treat Pi as a low-overhead option for bounded tasks, not as validated for long-context continuation with this model and workload. The fifth run's over-limit context is part of its failure, not a valid performance result.",
        "",
        "The early attempts are retained in `results/raw/pi-context-stress-exploratory-invalid.jsonl`; the pre-audit apparent pass is retained in `results/raw/pi-context-stress.jsonl`. The fifth trial's session, workspace, and server log were copied to `E:\\LocalLLMLabArchive\\2026-10-11\\pi-context-stress\\20261011T135433Z` after measurement and checksum verification; C:-backed WSL ext4 was used for all benchmark execution. Recreate with `scripts/22_benchmark_pi_context_stress.sh`; regenerate this table with `python3 benchmark/summarize_pi_context_stress.py --raw results/raw/pi-context-stress.jsonl --raw results/raw/pi-context-stress-exploratory-invalid.jsonl --csv results/csv/pi-context-stress.csv --report results/reports/pi-context-stress.md`.",
        "",
    ])
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text("\n".join(lines), encoding="utf-8")
    print(f"records={len(records)} full_quality_pass={passed} csv={args.csv} report={args.report}")
    return 0 if records else 1


if __name__ == "__main__":
    raise SystemExit(main())
