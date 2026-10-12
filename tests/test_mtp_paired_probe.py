from __future__ import annotations

import json
import time
import tempfile
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Event, Thread
from unittest import mock

from benchmark.mtp_paired_probe import (
    MAX_NEW_TOKENS,
    PROMPTS,
    RunStop,
    _run_quality_gates,
    _run_session,
    counter_delta,
    classify_cap_condition,
    evaluate_quality_gates,
    measured_schedule,
    parse_prometheus_counters,
    parse_sse_events,
    request_payload,
    request_completion,
    server_command,
    stop_reason,
    summarize_speculative_activity,
    summarize_denominators,
    swap_growth_breach,
)


class MtpPairedProbeTests(unittest.TestCase):
    def test_quality_gate_evaluation_requires_exactly_one_success_per_gate(self) -> None:
        passed = evaluate_quality_gates([
            {"mode": "structured_json", "success": True},
            {"mode": "tool_round_trip", "success": True},
        ])
        self.assertTrue(passed["passed"])
        failed = evaluate_quality_gates([
            {"mode": "structured_json", "success": False},
            {"mode": "tool_round_trip", "success": True},
            {"mode": "tool_round_trip", "success": True},
        ])
        self.assertFalse(failed["passed"])
        self.assertEqual(failed["checks"]["structured_json"]["reason"], "reported_failure")
        self.assertEqual(failed["checks"]["tool_round_trip"]["reason"], "duplicate_records")
        missing = evaluate_quality_gates([{"mode": "structured_json", "success": True}])
        self.assertEqual(missing["checks"]["tool_round_trip"]["reason"], "missing_record")

    def test_quality_smoke_wrapper_uses_isolated_real_cli_and_preserves_records(self) -> None:
        records = [{"mode": "structured_json", "success": True},
                   {"mode": "tool_round_trip", "success": True}]
        with tempfile.TemporaryDirectory() as temporary:
            session = Path(temporary)
            process = mock.Mock(pid=45678, returncode=0)
            process.poll.return_value = 0

            def launch(command: list[str], **kwargs: object) -> mock.Mock:
                self.assertIn(str(Path(__file__).resolve().parents[1] / "benchmark/quality_smoke.py"), command)
                self.assertEqual(command[command.index("--url") + 1], "http://127.0.0.1:18763")
                self.assertEqual(command[command.index("--model") + 1], "local")
                output = Path(command[command.index("--output") + 1])
                output.write_text("".join(json.dumps(row) + "\n" for row in records))
                env = kwargs["env"]
                self.assertEqual(env["LAB_CONTEXT_TOKENS"], "16384")
                self.assertEqual(env["LAB_REASONING"], "off")
                self.assertEqual(env["LAB_KV_CACHE_K"], "q4_0")
                self.assertEqual(env["LAB_SOURCE_DIRTY"], "true")
                return process

            with (mock.patch("benchmark.mtp_paired_probe.subprocess.Popen", side_effect=launch) as popen,
                  mock.patch("benchmark.mtp_paired_probe._server_log_has_oom", return_value=False),
                  mock.patch("benchmark.mtp_paired_probe._get_metrics", return_value={})):
                result = _run_quality_gates(
                    arm="off", install_root=Path("/ssd/install"), runtime=Path("/ssd/runtime"),
                    session=session, url="http://127.0.0.1:18763",
                    server_log=session / "server.log", resources_path=session / "resources.jsonl",
                    deadline=10**12, swap_baseline=0)

            self.assertTrue(result["passed"])
            self.assertEqual(result["runtime_configuration"]["spec_type"], "none")
            self.assertEqual(result["assessment"]["checks"]["structured_json"]["record"]["success"], True)
            self.assertEqual(result["assessment"]["checks"]["tool_round_trip"]["record"]["success"], True)
            self.assertEqual(popen.call_count, 1)

    def test_quality_smoke_wrapper_fails_closed_on_child_error_or_gate_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            session = Path(temporary)
            process = mock.Mock(pid=56789, returncode=1)
            process.poll.return_value = 1

            def launch(command: list[str], **_kwargs: object) -> mock.Mock:
                output = Path(command[command.index("--output") + 1])
                output.write_text(json.dumps({"mode": "structured_json", "success": False}) + "\n")
                return process

            with (mock.patch("benchmark.mtp_paired_probe.subprocess.Popen", side_effect=launch),
                  mock.patch("benchmark.mtp_paired_probe._server_log_has_oom", return_value=False),
                  mock.patch("benchmark.mtp_paired_probe._get_metrics", return_value={})):
                result = _run_quality_gates(
                    arm="on", install_root=Path("/ssd/install"), runtime=Path("/ssd/runtime"),
                    session=session, url="http://127.0.0.1:18763",
                    server_log=session / "server.log", resources_path=session / "resources.jsonl",
                    deadline=10**12, swap_baseline=0)

            self.assertFalse(result["passed"])
            self.assertEqual(result["status"], "failed_closed")
            self.assertEqual(result["stop_reason"], "quality_gate_failed")
            self.assertEqual(result["runtime_configuration"]["mtp_draft_context_kv"],
                             {"k": "f16", "v": "f16"})
            self.assertEqual(result["assessment"]["checks"]["structured_json"]["reason"],
                             "reported_failure")
            self.assertEqual(result["assessment"]["checks"]["tool_round_trip"]["reason"],
                             "missing_record")
    def _fake_completion(self, content: str = "ok") -> dict[str, object]:
        return {"http_status": 200, "content": content, "prompt_tokens": 20,
                "completion_tokens": 2, "timings": {"predicted_ms": 10},
                "finish_reason": "stop", "saw_done": True,
                "ttft_ms": 5.0, "wall_time_s": 0.02}

    def _run_mocked_session(self, output_root: Path, rows: list[dict[str, object]],
                            request_side_effect: list[object]) -> list[dict[str, object]]:
        records: list[dict[str, object]] = []
        process = mock.Mock(pid=23456)
        process.poll.return_value = None
        with (mock.patch("benchmark.mtp_paired_probe.subprocess.Popen", return_value=process),
              mock.patch("benchmark.mtp_paired_probe._server_healthy", return_value=True),
              mock.patch("benchmark.mtp_paired_probe._get_metrics", return_value={}),
              mock.patch("benchmark.mtp_paired_probe.request_completion",
                         side_effect=request_side_effect),
              mock.patch("benchmark.mtp_paired_probe._terminate_process_group") as terminate):
            _run_session(install_root=Path("/ssd/install"), server=Path("/ssd/llama-server"),
                         runtime=Path("/ssd/runtime"), output_root=output_root, rows=rows,
                         sequence=1, deadline=10**12, swap_baseline=0, records=records)
            self.assertEqual(terminate.call_count, 2)
        return records

    def test_session_orchestration_persists_success_and_reaps_owned_processes(self) -> None:
        rows = [
            {"stage": "measurement", "prompt_id": prompt_id, "arm": "off",
             "pair": 1, "repeat": 1, "session_id": "pair-1-off"}
            for prompt_id in PROMPTS
        ]
        with tempfile.TemporaryDirectory() as temporary:
            output_root = Path(temporary)
            records = self._run_mocked_session(
                output_root, rows, [self._fake_completion("first"), self._fake_completion("second")])

            self.assertEqual(len(records), 2)
            self.assertTrue(all(row["attempted"] and row["completed"] for row in records))
            self.assertEqual([row["response"] for row in records], ["first", "second"])
            self.assertEqual(len((output_root / "records.jsonl").read_text().splitlines()), 2)
            summary = json.loads((output_root / "summary.json").read_text())
            self.assertEqual(summary["attempted_measurements"], 2)
            self.assertEqual(summary["completed_measurements"], 2)

    def test_session_orchestration_keeps_request_error_in_attempted_denominator(self) -> None:
        rows = [
            {"stage": "measurement", "prompt_id": prompt_id, "arm": "on",
             "pair": 1, "repeat": 1, "session_id": "pair-1-on"}
            for prompt_id in PROMPTS
        ]
        with tempfile.TemporaryDirectory() as temporary:
            output_root = Path(temporary)
            records = self._run_mocked_session(
                output_root, rows,
                [RuntimeError("synthetic request failure"), self._fake_completion("recovered")])

            self.assertEqual([row["stop_reason"] for row in records], ["request_error", None])
            self.assertEqual([row["attempted"] for row in records], [True, True])
            self.assertEqual([row["completed"] for row in records], [False, True])
            summary = json.loads((output_root / "summary.json").read_text())
            self.assertEqual(summary["attempted_measurements"], 2)
            self.assertEqual(summary["completed_measurements"], 1)

    def test_quality_gates_run_before_warmups_and_measurements(self) -> None:
        events: list[str] = []
        rows = [
            {"stage": stage, "prompt_id": "division_repair", "arm": "off",
             "pair": 1, "repeat": 1 if stage == "measurement" else None,
             "session_id": "pair-1-off"}
            for stage in ("warmup", "measurement")
        ]
        gate = {"arm": "off", "passed": True, "status": "passed", "stop_reason": None,
                "summary_path": "/session/quality-gates/gate-summary.json"}
        completion = self._fake_completion()
        records: list[dict[str, object]] = []
        process = mock.Mock(pid=67890)
        process.poll.return_value = None

        def run_gate(**kwargs: object) -> dict[str, object]:
            events.append(f"gate:{kwargs['arm']}")
            return gate

        def run_completion(*_args: object, **_kwargs: object) -> dict[str, object]:
            events.append("completion")
            return completion

        with (tempfile.TemporaryDirectory() as temporary,
              mock.patch("benchmark.mtp_paired_probe.subprocess.Popen", return_value=process),
              mock.patch("benchmark.mtp_paired_probe._server_healthy", return_value=True),
              mock.patch("benchmark.mtp_paired_probe._get_metrics", return_value={}),
              mock.patch("benchmark.mtp_paired_probe.request_completion", side_effect=run_completion),
              mock.patch("benchmark.mtp_paired_probe._run_quality_gates", side_effect=run_gate),
              mock.patch("benchmark.mtp_paired_probe._terminate_process_group")):
            _run_session(install_root=Path("/ssd/install"), server=Path("/ssd/server"),
                         runtime=Path("/ssd/runtime"), output_root=Path(temporary), rows=rows,
                         sequence=1, deadline=10**12, swap_baseline=0, records=records)

        self.assertEqual(events, ["gate:off", "completion", "completion"])
        self.assertTrue(all(row["quality_gate_status"] == "passed" for row in records))

    def test_quality_gate_failure_aborts_arm_before_any_warmup_or_measurement(self) -> None:
        rows = [
            {"stage": stage, "prompt_id": "division_repair", "arm": "on",
             "pair": 1, "repeat": 1 if stage == "measurement" else None,
             "session_id": "pair-1-on"}
            for stage in ("warmup", "measurement")
        ]
        gate = {"arm": "on", "passed": False, "status": "failed_closed",
                "stop_reason": "quality_gate_failed", "summary_path": "/session/gate-summary.json"}
        records: list[dict[str, object]] = []
        process = mock.Mock(pid=78901)
        process.poll.return_value = None
        with (tempfile.TemporaryDirectory() as temporary,
              mock.patch("benchmark.mtp_paired_probe.subprocess.Popen", return_value=process),
              mock.patch("benchmark.mtp_paired_probe._server_healthy", return_value=True),
              mock.patch("benchmark.mtp_paired_probe._get_metrics", return_value={}),
              mock.patch("benchmark.mtp_paired_probe.request_completion") as completion,
              mock.patch("benchmark.mtp_paired_probe._run_quality_gates", return_value=gate),
              mock.patch("benchmark.mtp_paired_probe._terminate_process_group")):
            _run_session(install_root=Path("/ssd/install"), server=Path("/ssd/server"),
                         runtime=Path("/ssd/runtime"), output_root=Path(temporary), rows=rows,
                         sequence=1, deadline=10**12, swap_baseline=0, records=records)

        self.assertFalse(completion.called)
        self.assertEqual(len(records), 2)
        self.assertTrue(all(not row["attempted"] and not row["completed"] for row in records))
        self.assertTrue(all(row["stop_reason"] == "quality_gate_failed" for row in records))
        self.assertTrue(all(row["quality_gate_status"] == "failed_closed" for row in records))

    def test_speculative_activity_requires_positive_draft_and_acceptance_counters(self) -> None:
        active = summarize_speculative_activity([{
            "stage": "measurement", "arm": "on", "attempted": True,
            "speculative_counters": {
                "drafted_tokens": {"available": True, "delta": 8},
                "accepted_tokens": {"available": True, "delta": 3},
            },
        }])
        self.assertEqual(active["status"], "active_counters_observed")
        self.assertFalse(active["speedup_claim_allowed"])
        inactive = summarize_speculative_activity([{
            "stage": "measurement", "arm": "on", "attempted": True,
            "speculative_counters": {
                "drafted_tokens": {"available": False, "delta": None},
                "accepted_tokens": {"available": False, "delta": None},
            },
        }])
        self.assertEqual(inactive["status"], "inactive_or_incomplete")

    def test_stream_watchdog_runs_while_server_has_not_emitted_sse(self) -> None:
        entered_handler = Event()

        class DelayedStreamHandler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_POST(self) -> None:
                self.rfile.read(int(self.headers.get("Content-Length", "0")))
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.flush()
                entered_handler.set()
                time.sleep(1.5)

            def log_message(self, _format: str, *_args: object) -> None:
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), DelayedStreamHandler)
        server.daemon_threads = True
        server_thread = Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        checks = 0

        def watchdog() -> None:
            nonlocal checks
            checks += 1
            if checks >= 3:
                raise RunStop("swap_growth_limit")

        started = time.monotonic()
        try:
            with self.assertRaisesRegex(RunStop, "swap_growth_limit"):
                request_completion(f"http://127.0.0.1:{server.server_port}",
                                   request_payload("fixed"), timeout=5, on_event=watchdog)
        finally:
            server.shutdown()
            server.server_close()
            server_thread.join(timeout=1)

        self.assertTrue(entered_handler.is_set())
        self.assertGreaterEqual(checks, 3)
        self.assertLess(time.monotonic() - started, 1.25)

    def test_startup_guard_stops_before_request_on_swap_or_oom(self) -> None:
        over = [{"swap_used_bytes": 600 * 1024**2}] * 10
        row = {"stage": "measurement", "prompt_id": "division_repair", "arm": "off",
               "pair": 1, "repeat": 1, "session_id": "pair-1-off"}
        for expected_reason, oom, samples in (("swap_growth_limit", False, over),
                                               ("server_lost_or_oom", True, [])):
            with self.subTest(expected_reason=expected_reason), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                records: list[dict[str, object]] = []
                process = mock.Mock(pid=34567)
                process.poll.return_value = None
                with (mock.patch("benchmark.mtp_paired_probe.subprocess.Popen", return_value=process),
                      mock.patch("benchmark.mtp_paired_probe._server_healthy", return_value=False),
                      mock.patch("benchmark.mtp_paired_probe._server_log_has_oom", return_value=oom),
                      mock.patch("benchmark.mtp_paired_probe._read_jsonl", return_value=samples),
                      mock.patch("benchmark.mtp_paired_probe._terminate_process_group") as terminate,
                      mock.patch("benchmark.mtp_paired_probe._get_metrics", return_value={})):
                    _run_session(install_root=Path("/ssd/install"), server=Path("/ssd/server"),
                                 runtime=Path("/ssd/runtime"), output_root=root, rows=[row],
                                 sequence=1, deadline=10**12, swap_baseline=0, records=records)

                self.assertEqual(records[0]["attempted"], False)
                self.assertEqual(records[0]["stop_reason"], expected_reason)
                self.assertEqual(terminate.call_count, 2)

    def test_schedule_pairs_fresh_arm_blocks_and_warms_each_arm_prompt_once(self) -> None:
        schedule = measured_schedule()
        warmups = [row for row in schedule if row["stage"] == "warmup"]
        measured = [row for row in schedule if row["stage"] == "measurement"]

        self.assertEqual(len(warmups), 4)
        self.assertEqual(len(measured), 12)
        self.assertEqual(len({row["session_id"] for row in schedule}), 6)
        self.assertEqual(
            {(row["prompt_id"], row["arm"]) for row in warmups},
            {("division_repair", "off"), ("division_repair", "on"),
             ("text_summary", "off"), ("text_summary", "on")},
        )
        self.assertEqual(
            [(pair, sorted({row["arm"] for row in measured if row["pair"] == pair}))
             for pair in (1, 2, 3)],
            [(1, ["off", "on"]), (2, ["off", "on"]), (3, ["off", "on"])],
        )
        block_orders = [
            next(row["arm"] for row in schedule if row["session_id"] == f"pair-{pair}-{arm}")
            for pair, arm in ((1, "off"), (1, "on"), (2, "on"), (2, "off"),
                              (3, "off"), (3, "on"))
        ]
        self.assertEqual(block_orders, ["off", "on", "on", "off", "off", "on"])
        self.assertEqual(len({row["session_id"] for row in warmups}), 2)

    def test_request_payload_freezes_deterministic_512_token_streaming_cap(self) -> None:
        self.assertEqual(
            request_payload("fixed prompt bytes", "Qwen3.5-4B-Q4_K_M"),
            {"model": "Qwen3.5-4B-Q4_K_M",
             "messages": [{"role": "user", "content": "fixed prompt bytes"}],
             "temperature": 0, "seed": 1234, "max_tokens": 512,
             "stream": True, "stream_options": {"include_usage": True}},
        )
        self.assertEqual(MAX_NEW_TOKENS, 512)

    def test_sse_parser_collects_content_usage_timings_and_done_marker(self) -> None:
        parsed = parse_sse_events([
            'data: {"choices":[{"delta":{"content":"answer"}}]}\n',
            'data: {"choices":[{"delta":{},"finish_reason":"length"}],'
            '"usage":{"prompt_tokens":12,"completion_tokens":3},'
            '"timings":{"prompt_ms":9.5,"predicted_ms":21.0,"draft_n":4,"draft_n_accepted":3}}\n',
            "data: [DONE]\n",
        ])
        self.assertEqual(parsed, {
            "content": "answer", "prompt_tokens": 12, "completion_tokens": 3,
            "timings": {"prompt_ms": 9.5, "predicted_ms": 21.0, "draft_n": 4,
                         "draft_n_accepted": 3}, "finish_reason": "length", "saw_done": True,
        })

    def test_cap_condition_distinguishes_eos_cap_and_unknown(self) -> None:
        self.assertEqual(classify_cap_condition("stop", 18), "stop")
        self.assertEqual(classify_cap_condition("length", 18), "cap")
        self.assertEqual(classify_cap_condition("stop", MAX_NEW_TOKENS), "cap")
        self.assertEqual(classify_cap_condition(None, None), "unknown")

    def test_missing_prometheus_counter_remains_unavailable_not_zero(self) -> None:
        before = parse_prometheus_counters(
            "# TYPE llamacpp:spec_decode_num_draft_tokens_total counter\n")
        after = parse_prometheus_counters(
            "llamacpp:spec_decode_num_draft_tokens_total 4\n")
        metric = "llamacpp:spec_decode_num_draft_tokens_total"
        self.assertEqual(counter_delta(before, after, metric),
                         {"available": False, "before": None, "after": 4.0, "delta": None})
        self.assertEqual(counter_delta({metric: 0.0}, {metric: 4.0}, metric),
                         {"available": True, "before": 0.0, "after": 4.0, "delta": 4.0})

    def test_swap_guard_requires_ten_consecutive_samples_over_512_mib(self) -> None:
        baseline = 1024 * 1024 * 1024
        over = baseline + 512 * 1024 * 1024 + 1
        self.assertFalse(swap_growth_breach([{"swap_used_bytes": over}] * 9, baseline))
        self.assertTrue(swap_growth_breach([{"swap_used_bytes": over}] * 10, baseline))
        reset_rows = ([{"swap_used_bytes": over}] * 5 + [{"swap_used_bytes": baseline}
                      ] + [{"swap_used_bytes": over}] * 5)
        self.assertFalse(swap_growth_breach(reset_rows, baseline))

    def test_stop_reason_distinguishes_deadline_oom_and_swap(self) -> None:
        common = {"server_healthy": True, "server_log": "", "swap_samples": [],
                  "swap_baseline_bytes": 0}
        self.assertEqual(stop_reason(now=20, deadline=20, **common), "round_deadline")
        self.assertEqual(stop_reason(now=1, deadline=20, server_healthy=True,
                                     server_log="CUDA malloc failed", swap_samples=[],
                                     swap_baseline_bytes=0), "server_lost_or_oom")
        self.assertEqual(stop_reason(now=1, deadline=20, server_healthy=False,
                                     server_log="", swap_samples=[],
                                     swap_baseline_bytes=0), "server_lost_or_oom")
        samples = [{"swap_used_bytes": 600 * 1024**2}] * 10
        self.assertEqual(stop_reason(now=1, deadline=20, server_healthy=True,
                                     server_log="", swap_samples=samples,
                                     swap_baseline_bytes=0), "swap_growth_limit")
        self.assertIsNone(stop_reason(now=1, deadline=20, **common))

    def test_denominators_count_attempted_failures_and_exclude_warmups(self) -> None:
        rows = [
            {"stage": "warmup", "attempted": True, "arm": "off", "prompt_id": "division_repair"},
            {"stage": "measurement", "attempted": True, "completed": True,
             "arm": "off", "prompt_id": "division_repair"},
            {"stage": "measurement", "attempted": True, "completed": False,
             "arm": "off", "prompt_id": "division_repair"},
            {"stage": "measurement", "attempted": False, "completed": False,
             "arm": "on", "prompt_id": "division_repair"},
        ]
        self.assertEqual(summarize_denominators(rows), {
            "planned_measurements": 3, "attempted_measurements": 2,
            "completed_measurements": 1,
            "by_arm_prompt": {"off/division_repair": {"attempted": 2, "completed": 1}},
        })

    def test_server_command_freezes_mtp_draft_cache_as_f16(self) -> None:
        off = server_command("/ssd/llama-server", "/ssd/model.gguf", 18763, "off")
        on = server_command("/ssd/llama-server", "/ssd/model.gguf", 18763, "on")
        self.assertEqual(off[off.index("--spec-type") + 1], "none")
        self.assertEqual(on[on.index("--spec-type") + 1], "draft-mtp")
        self.assertEqual(on[on.index("--spec-draft-type-k") + 1], "f16")
        self.assertEqual(on[on.index("--spec-draft-type-v") + 1], "f16")
        self.assertEqual(on[on.index("--n-predict") + 1], "512")
        for flag in ("--spec-draft-n-max", "--spec-draft-type-k", "--spec-draft-type-v"):
            self.assertEqual(off[off.index(flag) + 1], on[on.index(flag) + 1])
        off_without_spec = off[:off.index("--spec-type")] + off[off.index("--spec-type") + 2:]
        on_without_spec = on[:on.index("--spec-type")] + on[on.index("--spec-type") + 2:]
        self.assertEqual(off_without_spec, on_without_spec)


if __name__ == "__main__":
    unittest.main()
