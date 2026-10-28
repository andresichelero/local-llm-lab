import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path

MODULE_PATH = Path(__file__).parents[1] / "scripts" / "local_llm_snapshot.py"
SPEC = importlib.util.spec_from_file_location("local_llm_snapshot", MODULE_PATH)
monitor = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(monitor)


def test_dynamic_repair_stages_grow_beyond_initial_baseline(tmp_path):
    status = {'completed_episodes': 75, 'scheduled_episodes': 81,
              'task_quarantines': {'M2': {'reason': 'unattributed_tool_error'}}}
    manifest = {'immutable': {'repair_schedule': [{}] * 75},
                'stage_schedules': {'baseline': [{}] * 75, 'cache_on': [{}] * 6}}
    result = monitor.derive_run_summary(tmp_path, status, manifest)
    assert result['scheduled'] == 81
    assert result['task_quarantines']['M2']['reason'] == 'unattributed_tool_error'


def test_manifest_schedule_wins_when_status_only_counts_current_stage(tmp_path):
    status = {
        "protocol_id": "practical-agent-selection-7bplus-repair-v1",
        "status": "running",
        "completed_episodes": 21,
        "scheduled_episodes": 75,
        "current_stage": "baseline",
        "updated_at_utc": "2026-10-21T14:34:56+00:00",
    }
    manifest = {"immutable": {"repair_schedule": [{"id": i} for i in range(93)]}}
    result = monitor.derive_run_summary(tmp_path, status, manifest)
    assert result["scheduled"] == 93
    assert result["manifest_scheduled"] == 93
    assert result["status_scheduled"] == 75
    assert result["schedule_source"] == "manifest.immutable.repair_schedule"
    assert result["schedule_mismatch"] is True
    assert result["completed"] == 21
    assert result["progress_percent"] == 22.6


def test_recent_runs_sort_by_status_update_and_skip_malformed_files(tmp_path):
    for name, updated, state, total in (
        ("older", "2026-10-20T10:00:00+00:00", "complete", 2),
        ("newer", "2026-10-21T10:00:00+00:00", "running", 5),
    ):
        folder = tmp_path / name
        folder.mkdir()
        (folder / "status.json").write_text(json.dumps({
            "status": state, "scheduled_episodes": total, "updated_at_utc": updated,
        }), encoding="utf-8")
    broken = tmp_path / "broken"
    broken.mkdir()
    (broken / "status.json").write_text("{", encoding="utf-8")
    runs = monitor.load_recent_runs(tmp_path, limit=2)
    assert [run["name"] for run in runs] == ["newer", "older"]


def test_memory_parser_reports_available_ram_and_used_swap():
    info = monitor.parse_meminfo(
        "MemTotal:       8192000 kB\n"
        "MemAvailable:   3072000 kB\n"
        "SwapTotal:      2048000 kB\n"
        "SwapFree:       1024000 kB\n"
    )
    result = monitor._wsl_memory(info)
    assert result["total_gib"] == 7.81
    assert result["available_gib"] == 2.93
    assert result["swap_used_gib"] == 0.98


def test_cpu_usage_uses_busy_delta_and_rejects_reversed_samples():
    before = monitor.parse_cpu_counters("cpu 100 0 20 80 0 0 0 0")
    after = monitor.parse_cpu_counters("cpu 150 0 30 120 0 0 0 0")
    assert monitor.cpu_busy_percent(before, after) == 60.0
    assert monitor.cpu_busy_percent(after, before) is None


def test_nvidia_smi_metadata_distinguishes_wsl_umd_from_legacy_cuda_ceiling():
    current = monitor.parse_nvidia_smi_metadata(
        "NVIDIA-SMI 610.43.02 KMD Version: 610.62 CUDA UMD Version: 13.3"
    )
    assert current["nvidia_smi_version"] == "610.43.02"
    assert current["kernel_driver_version"] == "610.62"
    assert current["cuda_umd_version"] == "13.3"
    assert current["cuda_driver_max"] is None

    legacy = monitor.parse_nvidia_smi_metadata(
        "NVIDIA-SMI 560.12 Driver Version: 560.12 CUDA Version: 12.6"
    )
    assert legacy["cuda_driver_max"] == "12.6"


def test_exact_runner_uptime_and_status_age_do_not_mark_repair_r1_active():
    output_root = "/home/foxtrot/local-llm-benchmark/results"
    runner = {
        "kind": "benchmark-runner",
        "pid": 291,
        "elapsed": "02:03:45",
        "cwd": "/home/foxtrot/local-llm-benchmark",
        "command": (
            "/usr/bin/python3 -m benchmark.practical_repair --execute "
            f"--output {output_root}/practical-selection-7bplus-repair-r2"
        ),
    }
    r1 = {
        "name": "practical-selection-7bplus-repair-r1",
        "protocol": "practical-agent-selection-7bplus-repair-v1",
        "path": f"{output_root}/practical-selection-7bplus-repair-r1",
        "status": "running",
    }
    r2 = {
        "name": "practical-selection-7bplus-repair-r2",
        "protocol": "practical-agent-selection-7bplus-repair-v1",
        "path": f"{output_root}/practical-selection-7bplus-repair-r2",
        "status": "running",
        "updated_at_utc": "2026-10-21T16:50:20.039332+00:00",
    }

    stale_r1 = monitor.correlate_run_with_processes(r1, [runner])
    active_r2 = monitor.correlate_run_with_processes(
        r2,
        [runner],
        observed_at=datetime(2026, 10, 21, 16, 57, tzinfo=timezone.utc),
    )

    assert stale_r1["runner_active"] is False
    assert stale_r1["display_status"] == "stale?"
    assert active_r2["runner_active"] is True
    assert active_r2["display_status"] == "running"
    assert active_r2["runner_pid"] == 291
    assert active_r2["runner_elapsed"] == "02:03:45"
    assert active_r2["status_age_seconds"] == 400.0
    assert active_r2["runner_observed_at_utc"] == "2026-10-21T16:57:00+00:00"


def test_process_parser_finds_runner_and_server_with_memory(tmp_path):
    output = (
        "  PID  PPID %CPU %MEM   RSS     ELAPSED COMMAND\n"
        "  101     1 12.5  1.0 10240       01:20 python -m benchmark.practical_repair --execute\n"
        "  102   101 88.0 15.0 524288      00:45 /opt/llama-server --model /models/a.gguf --ctx-size 16384\n"
        "  103     1  0.0  0.0  1024       00:10 bash\n"
    )
    processes = monitor.parse_relevant_processes(output, proc_root=tmp_path)
    assert [item["kind"] for item in processes] == ["benchmark-runner", "llama-server"]
    assert processes[1]["pid"] == 102
    assert processes[1]["rss_mib"] == 512.0


def test_qwen_quant_runner_is_detected_and_correlated_to_its_output(tmp_path):
    output = (
        "  PID  PPID %CPU %MEM   RSS     ELAPSED COMMAND\n"
        "  201     1  3.9  0.3 32768    09:31:28 python -m benchmark.qwen_quant_runner "
        "--output /home/foxtrot/local-llm-benchmark/results/qwen-quant-harness-optimization-v4 --execute\n"
        "  202   201 93.1 16.1 1679360  01:42 /opt/llama-server --model /models/Qwen3.5-4B.i1-IQ2_M.gguf\n"
    )
    processes = monitor.parse_relevant_processes(output, proc_root=tmp_path)
    assert [item["kind"] for item in processes] == ["benchmark-runner", "llama-server"]
    run = {
        "path": "/home/foxtrot/local-llm-benchmark/results/qwen-quant-harness-optimization-v4",
        "status": "running",
        "updated_at_utc": "2026-10-26T06:36:10+00:00",
    }
    correlated = monitor.correlate_run_with_processes(run, processes)
    assert correlated["runner_active"] is True
    assert correlated["runner_pid"] == 201


def test_completed_campaign_total_uses_all_stage_schedules(tmp_path):
    status = {
        "status": "complete", "scheduled_episodes": 10, "completed_episodes": 10,
        "episodes_by_stage": {"baseline": {"complete": 6}, "holdout": {"complete": 4}},
    }
    manifest = {"stage_schedules": {"baseline": [{} for _ in range(6)],
                                    "holdout": [{} for _ in range(4)]}}
    result = monitor.derive_run_summary(tmp_path, status, manifest)
    assert result["scheduled"] == 10
    assert result["completed"] == 10
    assert result["progress_percent"] == 100.0


def test_run_summary_reports_authorization_capacity_and_agenda_fields(tmp_path):
    status = {"status": "blocked", "records": 3, "updated_at_utc": "2026-10-23T10:00:00+00:00",
              "maximum_episodes": None}
    manifest = {
        "status": "blocked", "error": None, "operator_retry_blocked": True,
        "resolved_errors": [{"resolved_at_utc": "2026-10-23T09:00:00+00:00",
                             "error": "profile probe failed: fixture", "status": "blocked"},
                            {"resolved_at_utc": "2026-10-23T09:30:00+00:00",
                             "error": "runtime versions changed", "status": "blocked"}],
        "immutable": {"schedule": {"maximum_episodes": 12}},
    }
    (tmp_path / "capacity-wait.json").write_text(json.dumps({
        "started_at_utc": "2026-10-23T10:00:00+00:00",
        "finished_at_utc": "2026-10-23T10:02:00+00:00", "waited_seconds": 120.1,
        "poll_seconds": 2.0, "stable_samples_required": 3, "ready": False,
        "outcome": "probe_never_ready", "note": "a model server is active"}))

    result = monitor.derive_run_summary(tmp_path, status, manifest)

    assert result["agenda_denominator"] == 12
    assert result["active_error"] is None
    assert result["resolved_errors"] == 2
    assert result["operator_retry_blocked"] is True
    assert result["capacity_wait"]["outcome"] == "probe_never_ready"
    assert result["capacity_wait"]["ready"] is False


def test_run_summary_without_capacity_file_keeps_fields_absent(tmp_path):
    status = {"status": "complete", "updated_at_utc": "2026-10-23T10:00:00+00:00"}
    manifest = {"status": "complete", "error": "leftover stale? no: active string"}

    result = monitor.derive_run_summary(tmp_path, status, manifest)

    assert result["agenda_denominator"] is None
    assert result["active_error"] == "leftover stale? no: active string"
    assert result["resolved_errors"] == 0
    assert result["operator_retry_blocked"] is False
    assert result["capacity_wait"] is None
