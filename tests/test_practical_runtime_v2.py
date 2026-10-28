"""Focused controls for the v2 runtime contract; these never load a model."""
from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from benchmark import practical_runtime_v2 as runtime
from benchmark import opencode_controlled_probe
from benchmark import practical_grade_contract as grade
from benchmark import practical_tasks_v2 as tasks

from benchmark.practical_runtime_v2 import (
    build_generation_policy,
    classify_http_error,
    make_opencode_profile,
    make_server_command,
    _mcp_events,
    validate_profile,
)
from benchmark.practical_driver_v2 import phase_timeout


def test_repetition_seed_and_generation_policy_are_frozen() -> None:
    assert build_generation_policy(1) == {
        "temperature": 0.2,
        "top_p": 0.95,
        "seed": 101,
        "max_tokens": 4096,
    }
    assert build_generation_policy(2)["seed"] == 202
    assert build_generation_policy(3)["seed"] == 303


def test_profile_sets_input_limit_compaction_and_prompt_cache() -> None:
    contract = {"alias": "fixture-model", "path": "models/fixture.gguf", "sha256": "a" * 64,
                "revision": "fixture-revision"}
    baseline = validate_profile({"id": "baseline", "context_tokens": 16384, "cache_prompt": False})
    config = make_opencode_profile("fixture", contract, baseline)
    model = config["provider"]["local"]["models"]["fixture-model"]
    assert model["limit"] == {"context": 16384, "input": 16384, "output": 4096}
    assert model["options"] == {"temperature": 0.2, "top_p": 0.95, "seed": 101}
    assert config["compaction"] == {"auto": True, "prune": True, "reserved": 6144}
    assert config["tool_output"] == {"max_bytes": 6000, "max_lines": 200}

    cache = validate_profile({"id": "cache_on", "context_tokens": 16384, "cache_prompt": True})
    command = make_server_command("/models/fixture.gguf", "fixture-model", cache, 12345)
    assert "--cache-prompt" in command
    assert "--no-cache-prompt" not in command
    assert command[command.index("--ctx-size") + 1] == "16384"


def test_profile_probe_uses_the_registered_opencode_mcp_tool_name(monkeypatch, tmp_path):
    captured = {}
    native_event = {
        "type": "tool_use",
        "part": {
            "tool": "lab_list_issues",
            "state": {"status": "completed", "input": {}, "output": {"issues": []}},
        },
    }

    monkeypatch.setattr(runtime, "_start_model_server",
                        lambda *args, **kwargs: (None, tmp_path / "llama.log", 12345, 0.1))
    monkeypatch.setattr(runtime, "make_server_command", lambda *args, **kwargs: [])

    def run_agent(*args, **kwargs):
        captured["prompts"] = kwargs["prompts"]
        return SimpleNamespace(
            output=(json.dumps(native_event) + "\n").encode(),
            cleanup_verified=True,
            infrastructure_error=None,
            broker_events=[SimpleNamespace(method="POST")],
        )

    monkeypatch.setattr(runtime, "_run_agent", run_agent)
    monkeypatch.setattr(runtime, "_stop_model_server", lambda process: True)

    result = runtime.probe_profile(
        "qwen3.5-4b",
        {"id": "baseline", "context_tokens": 16384, "cache_prompt": False},
        lab=tmp_path,
        output=tmp_path / "probes",
    )

    assert result["passed"] is True
    assert "lab_list_issues" in captured["prompts"][0]


def test_model_start_preflight_allows_only_an_explicit_lower_gpu_floor(monkeypatch, tmp_path):
    monkeypatch.setattr(runtime, "GPU_FREE_FLOOR_MIB", 7168)
    monkeypatch.setattr(opencode_controlled_probe, "_assert_free_resources", lambda lab: None)
    monkeypatch.setattr(
        runtime.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="7022,8192\n"),
    )

    with pytest.raises(RuntimeError, match="need 7168 MiB"):
        runtime._model_start_preflight(tmp_path)

    runtime.configure_gpu_free_floor_mib(7000)
    runtime._model_start_preflight(tmp_path)

    with pytest.raises(ValueError):
        runtime.configure_gpu_free_floor_mib(7169)
    with pytest.raises(ValueError):
        runtime.configure_gpu_free_floor_mib(6999)


def test_profile_rejects_unfrozen_or_inconsistent_values() -> None:
    for profile in (
        {"id": "baseline", "context_tokens": 32768, "cache_prompt": False},
        {"id": "cache_on", "context_tokens": 16384, "cache_prompt": False},
        {"id": "baseline", "context_tokens": 16384, "cache_prompt": False, "temperature": 0},
    ):
        try:
            validate_profile(profile)
        except ValueError:
            continue
        raise AssertionError(f"accepted non-canonical profile: {profile}")


def test_http_errors_separate_context_configuration_and_infrastructure() -> None:
    assert classify_http_error(400, "prompt exceeds the available context window") == "context_exhausted"
    assert classify_http_error(400, "unsupported generation option: top_p") == "configuration"
    assert classify_http_error(400, "invalid request body") == "configuration"
    assert classify_http_error(503, "model server unavailable") == "infrastructure"
    assert classify_http_error(200, "tool call recovered after an argument error") is None


def test_mcp_error_event_preserves_server_audit_from_native_error_field() -> None:
    arguments = {"change_id": "C-17", "version": 1}
    audit = {"sequence": 2, "call": {"name": "apply_change", "arguments": arguments,
                                      "isError": True}}
    error = {"error": "stale version", "_audit": audit}
    native = [{"type": "tool_use", "part": {
        "tool": "lab_apply_change", "state": {
            "status": "error", "input": arguments, "error": json.dumps(error),
        },
    }}]

    events = _mcp_events(native)

    assert events == [{"name": "apply_change", "arguments": arguments,
                       "result": error, "isError": True}]


def _mcp_success_result():
    from benchmark.linux_sandbox import RunResult

    return RunResult(
        returncode=0, timed_out=False, cleanup_verified=True, output_limited=False,
        output=b"", workspace_outputs={}, workspace_output_modes={},
        workspace_audit={}, namespace_evidence={}, file_evidence={},
        network_evidence={}, resource_evidence={}, infrastructure_error=None)


def _wire_agent(monkeypatch, tmp_path, task, journal_payload: dict | None):
    """Run the real _run_agent behind a fake sandbox supervisor.

    The fake mirrors the trusted bridge close: it writes the journal exactly
    when ``journal_payload`` is given, then returns a successful RunResult.
    """

    captured: dict = {}

    def capture_binds(lab, path, **kwargs):
        captured["runtime"] = Path(path)
        return ()

    class Supervisor:
        def run(self, spec):
            captured["spec"] = spec
            captured["config"] = json.loads(
                (captured["runtime"] / "opencode.json").read_text())
            # The runtime directory is deleted after the episode: record the
            # namespace-visible bind contents while they still exist.
            captured["binds_proxy_module"] = (
                captured["runtime"] / "practical_mcp_bridge.py").is_file()
            captured["binds_trusted_server"] = (
                captured["runtime"] / "practical_mcp_v2.py").exists()
            bridge = getattr(spec, "mcp_bridge", None)
            if bridge is not None and journal_payload is not None:
                bridge.journal_path.write_text(
                    json.dumps(journal_payload), encoding="utf-8")
            return _mcp_success_result()

    monkeypatch.setattr(runtime, "_runtime_binds", capture_binds)
    monkeypatch.setattr(runtime, "SandboxSupervisor", Supervisor)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    value = runtime._run_agent(
        task, "fixture", {"alias": "fixture"},
        {"id": "baseline", "context_tokens": 16384, "cache_prompt": False},
        1, workspace, tmp_path, lab=tmp_path, upstream_port=12345,
        seconds=20, max_requests=5, prompts=["fixture request"],
        task_contract_id="historical-v2")
    return value, captured


def test_mcp_episode_wires_the_host_bridge_and_the_source_free_proxy(
        monkeypatch, tmp_path):
    value, captured = _wire_agent(
        monkeypatch, tmp_path, "C2",
        _valid_idle_journal('C2'))
    spec = captured["spec"]
    command = captured["config"]["mcp"]["lab"]["command"]
    assert command[3] == "/opt/practical/practical_mcp_bridge.py"
    assert command[4:7] == ["--proxy", "127.0.0.1", str(spec.mcp.port)]
    assert spec.mcp_bridge is not None
    assert spec.mcp_bridge.journal_path == tmp_path / "mcp-journal.json"
    assert spec.mcp_bridge.task == "C2"
    assert spec.mcp_bridge.contract_id == "historical-v2"
    # The namespace-visible runtime binds no server source, no fixtures: only
    # the source-free proxy module.
    assert not captured["binds_trusted_server"]
    assert captured["binds_proxy_module"]
    # A clean journal keeps the sandbox verdict untouched.
    assert value.infrastructure_error is None


def test_mcp_episode_without_a_journal_is_infrastructure(monkeypatch, tmp_path):
    value, captured = _wire_agent(monkeypatch, tmp_path, "C2", None)
    assert value.infrastructure_error == "mcp_journal_missing"


def test_mcp_episode_with_a_channel_fault_is_infrastructure(monkeypatch, tmp_path):
    value, _ = _wire_agent(
        monkeypatch, tmp_path, "M2",
        {"schema": "practical-mcp-journal-v1", "task": "M2",
         "clean_close": False, "fault": "mcp_channel_error:OSError",
         "final_state": {"calls": []}, "records": []})
    assert value.infrastructure_error == "mcp_channel_fault:mcp_channel_error:OSError"


def test_non_mcp_episode_wires_no_mcp_channel(monkeypatch, tmp_path):
    value, captured = _wire_agent(monkeypatch, tmp_path, "M1", None)
    spec = captured["spec"]
    assert captured["config"].get("mcp") is None
    assert spec.mcp is None and spec.mcp_bridge is None
    assert not captured["binds_proxy_module"]


def test_driver_phase_one_cap_is_at_most_45_percent_and_total_is_shared() -> None:
    assert phase_timeout(remaining_seconds=300, total_seconds=300, phase_index=1, phase_count=2) == 135
    assert phase_timeout(remaining_seconds=100, total_seconds=300, phase_index=1, phase_count=2) == 100
    assert phase_timeout(remaining_seconds=92, total_seconds=300, phase_index=2, phase_count=2) == 92


def test_agent_sandbox_keeps_reserved_path_and_mcp_task_scope(monkeypatch, tmp_path):
    captured = {}
    monkeypatch.setattr(runtime, "_runtime_binds", lambda lab, path, **kwargs:
                        captured.update(runtime=path) or ())

    class Supervisor:
        def run(self, spec):
            captured["spec"] = spec
            captured["config"] = json.loads((captured["runtime"] / "opencode.json").read_text())
            return _mcp_success_result()

    monkeypatch.setattr(runtime, "SandboxSupervisor", Supervisor)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (tmp_path / "mcp-journal.json").write_text(json.dumps(_valid_idle_journal('D2')),
        encoding="utf-8")
    value = runtime._run_agent(
        "D2", "fixture", {"alias": "fixture"},
        {"id": "baseline", "context_tokens": 16384, "cache_prompt": False},
        1, workspace, tmp_path, lab=tmp_path, upstream_port=12345,
        seconds=20, max_requests=5, prompts=["fixture request"],
    )
    assert value.infrastructure_error is None
    assert "PATH" not in captured["spec"].env
    command = captured["config"]["mcp"]["lab"]["command"]
    assert "/opt/practical/practical_mcp_bridge.py" in command[:4]
    assert "--proxy" in command and "127.0.0.1" in command


def test_driver_fails_environment_before_any_model_request(monkeypatch, tmp_path, capsys):
    from benchmark import practical_driver_v2 as driver

    config = tmp_path / "driver.json"
    config.write_text(json.dumps({"model": "fixture", "prompts": ["implement"],
                                  "seconds": 20, "language": "javascript"}))
    monkeypatch.setattr(driver, "CONFIG_PATH", config)
    monkeypatch.setenv("PATH", "/usr/bin:/bin")

    def preflight(language):
        assert driver.os.environ["PATH"] == "/opt/node/bin:/usr/bin:/bin"
        return {"passed": False, "reason": "node unavailable through candidate shell"}

    monkeypatch.setattr(driver, "environment_preflight", preflight)
    monkeypatch.setattr(driver.subprocess, "run", lambda *args, **kwargs:
                        pytest.fail("OpenCode must not run after failed environment check"))
    assert driver.main() == 125
    event = json.loads(capsys.readouterr().out)
    assert event["_practical_driver"] == "environment"
    assert event["passed"] is False


def test_environment_marker_is_host_driver_metadata():
    raw = (json.dumps({"_practical_driver": "environment", "passed": False,
                       "reason": "node unavailable"}) + "\n").encode()
    native, driver = runtime._events(raw)
    assert native == []
    assert driver[0]["passed"] is False


def test_tool_error_counts_exclude_only_validated_expected_errors(monkeypatch):
    from benchmark import practical_mcp_grading_v2 as grading

    calls = [{"type": "tool_use", "part": {"tool": "lab_apply_change", "state": {
        "status": "error", "input": {}, "error": "deliberate temporary failure"}}},
        {"type": "tool_use", "part": {"tool": "glob", "state": {"status": "error"}}}]
    monkeypatch.setattr(grading, "expected_tool_errors", lambda task, events: 1 if task == "M2" else 0)
    assert runtime.tool_error_counts("M2", calls) == {
        "tool_errors": 2, "expected_tool_errors": 1, "avoidable_tool_errors": 1}
    assert runtime.tool_error_counts("D2", calls) == {
        "tool_errors": 2, "expected_tool_errors": 0, "avoidable_tool_errors": 2}


def test_probe_environment_failure_is_infrastructure_not_model_capability(monkeypatch, tmp_path):
    event = {"_practical_driver": "environment", "passed": False, "reason": "python3 unavailable"}
    monkeypatch.setattr(runtime, "_start_model_server",
                        lambda *args, **kwargs: (None, tmp_path / "llama.log", 12345, 0.1))
    monkeypatch.setattr(runtime, "make_server_command", lambda *args, **kwargs: [])
    monkeypatch.setattr(runtime, "_run_agent", lambda *args, **kwargs: SimpleNamespace(
        output=(json.dumps(event) + "\n").encode(), cleanup_verified=True,
        infrastructure_error=None, broker_events=[]))
    monkeypatch.setattr(runtime, "_stop_model_server", lambda process: True)
    result = runtime.probe_profile("fixture", {"id": "baseline", "context_tokens": 16384,
                                               "cache_prompt": False},
                                   lab=tmp_path, output=tmp_path / "probes",
                                   models={"fixture": {"alias": "fixture", "path": "fixture.gguf"}})
    assert result["status"] == "infrastructure"
    assert result["model_calls"] == 0


def test_shell_preflight_checks_node_through_candidate_shell_and_reports_missing(monkeypatch):
    from benchmark import practical_driver_v2 as driver

    seen = []

    def shell_run(command, **kwargs):
        assert command[:2] == ["/usr/bin/bash", "-c"]
        seen.append(command[2])
        missing = command[2].startswith("node ")
        return SimpleNamespace(returncode=127 if missing else 0, stdout="",
                               stderr="node: command not found" if missing else "")

    monkeypatch.setattr(driver.subprocess, "run", shell_run)
    result = driver.environment_preflight("javascript")
    assert len(seen) == 2
    assert seen[0].startswith("python3 ")
    assert seen[1].startswith("node ")
    assert result["passed"] is False
    assert result["returncode"] == 127
    assert "node: command not found" in result["output"]


# --- grade contract dispatch inside the sandbox (Task 1, post-audit) ---


def _seed_report(spec):
    """Mirror the in-sandbox collector: slot 0 only, from the seed nonce."""
    nonce = json.loads(
        (spec.workspace / ".practical-grade-seed.json").read_text())["nonce"]
    source = None
    for bind in spec.runtime_ro:
        if str(bind.target) in {"/opt/checks.py", "/opt/checks.test.js"}:
            source = Path(bind.source).read_text(encoding="utf-8")
    assert source is not None
    language = spec.argv[spec.argv.index('--language')+1] if '--language' in spec.argv else 'python'
    parser = grade.node_check_case_ids if language == "javascript" \
        else grade.python_check_case_ids
    expected = list(parser(source))
    report = {"schema": grade.REPORT_SCHEMA, "nonce": nonce,
              "expected_case_ids": expected, "status": "complete",
              "checks": [{"id": case, "stop": "pass"} for case in expected],
              "tests_run": len(expected)}
    raw = json.dumps(report).encode("utf-8")
    return grade.report_export_paths(nonce)[0], raw


def _make_supervisor(monkeypatch, exporter):
    class Supervisor:
        def __init__(self, *args, **kwargs):
            pass

        def run(self, spec):
            return exporter(spec)

    monkeypatch.setattr(runtime, "SandboxSupervisor", Supervisor)


def _run_result(**overrides):
    values = {"returncode": 0, "timed_out": False, "cleanup_verified": True,
              "output": b"", "workspace_outputs": {},
              "infrastructure_error": None}
    values.update(overrides)
    return SimpleNamespace(**values)


def _collector_result(raw, **overrides):
    return _run_result(output=grade.REPORT_PREFIX.encode()+raw+b'\n',**overrides)


def _valid_idle_journal(task):
    from benchmark.practical_mcp_v2 import Server
    return {'schema':'practical-mcp-journal-v1','task':task,'task_contract_id':'historical-v2',
            'clean_close':True,'fault':None,'final_state':Server(task=task).state,
            'records':[{'seq':1,'kind':'journal_close'}]}


def test_python_grader_dispatches_the_contract_launcher(monkeypatch, tmp_path):
    def export(spec):
        name, raw = _seed_report(spec)
        return _collector_result(raw, workspace_outputs={name: raw})

    _make_supervisor(monkeypatch, export)
    workspace = tmp_path / "ws"
    workspace.mkdir()
    hidden = runtime._grader_result("B1", 1, workspace, lab=tmp_path)
    assert hidden["passed"] is True
    assert hidden["checks_completed"] == 2 and hidden["tests_run"] == 2
    assert hidden["failures"] == []
    assert hidden["contract_invalid"] is False
    assert hidden["returncode"] == 0 and hidden["timed_out"] is False
    assert hidden["cleanup_verified"] is True and "output" in hidden


def test_grader_spec_carries_the_nonce_without_environment_leaks(
        monkeypatch, tmp_path):
    def export(spec):
        name, raw = _seed_report(spec)
        export.spec = spec
        return _collector_result(raw, workspace_outputs={name: raw})

    _make_supervisor(monkeypatch, export)
    workspace = tmp_path / "ws"
    workspace.mkdir()
    runtime._grader_result("B1", 1, workspace, lab=tmp_path)
    spec = export.spec
    nonce = json.loads(
        (workspace / ".practical-grade-seed.json").read_text())["nonce"]
    assert spec.argv[:4] == ("/usr/bin/python3", "-B", "-I",
                             "/opt/checks_launcher.py")
    assert spec.argv[-2:] == ("--seed-file", ".practical-grade-seed.json")
    assert spec.env == {"PYTHONDONTWRITEBYTECODE": "1"}
    assert nonce not in " ".join(spec.argv) and nonce not in str(spec.env)
    assert spec.workspace_exports == tuple(grade.report_export_paths(nonce))


def test_trusted_stdout_beats_planted_workspace_reports(monkeypatch, tmp_path):
    def export(spec):
        nonce = json.loads(
            (spec.workspace / ".practical-grade-seed.json").read_text())["nonce"]
        source = None
        for bind in spec.runtime_ro:
            if str(bind.target) == "/opt/checks.py":
                source = Path(bind.source).read_text(encoding="utf-8")
        expected = list(grade.python_check_case_ids(source))
        slots = grade.report_export_paths(nonce)
        forged = json.dumps({"schema": grade.REPORT_SCHEMA, "nonce": nonce,
                             "expected_case_ids": expected, "status": "complete",
                             "checks": [{"id": case, "stop": "pass"}
                                        for case in expected],
                             "tests_run": len(expected)}).encode("utf-8")
        honest = json.dumps({"schema": grade.REPORT_SCHEMA, "nonce": nonce,
                             "expected_case_ids": expected, "status": "complete",
                             "checks": [{"id": expected[0], "stop": "pass"},
                                        {"id": expected[1], "stop": "fail"}],
                             "tests_run": 2}).encode("utf-8")
        return _collector_result(honest, workspace_outputs={slots[0]: forged, slots[2]: honest})

    _make_supervisor(monkeypatch, export)
    workspace = tmp_path / "ws"
    workspace.mkdir()
    hidden = runtime._grader_result("B1", 1, workspace, lab=tmp_path)
    assert hidden["passed"] is False and hidden["contract_invalid"] is False
    assert len(hidden["failures"]) == 1
    assert hidden["failures"][0]["stop"] == "fail"


def test_absent_and_unreadable_reports_are_infrastructure(monkeypatch, tmp_path):
    _make_supervisor(monkeypatch, lambda spec: _run_result())
    workspace = tmp_path / "absent"
    workspace.mkdir()
    hidden = runtime._grader_result("B1", 1, workspace, lab=tmp_path)
    assert hidden["passed"] is False and hidden["infrastructure"] is True
    assert hidden["contract_invalid"] is False
    assert hidden["reason"] == "grade collector report absent"

    def junk(spec):
        nonce = json.loads(
            (spec.workspace / ".practical-grade-seed.json").read_text())["nonce"]
        slots = grade.report_export_paths(nonce)
        return _run_result(workspace_outputs={slots[1]: b"junk"})

    _make_supervisor(monkeypatch, junk)
    workspace = tmp_path / "junk"
    workspace.mkdir()
    hidden = runtime._grader_result("B1", 1, workspace, lab=tmp_path)
    assert hidden["infrastructure"] is True and hidden["passed"] is False


def test_infrastructure_runs_shortcut_before_any_report(monkeypatch, tmp_path):
    _make_supervisor(monkeypatch,
                     lambda spec: _run_result(cleanup_verified=False,
                                              infrastructure_error="sandbox_boot",
                                              returncode=None))
    workspace = tmp_path / "ws"
    workspace.mkdir()
    hidden = runtime._grader_result("B1", 1, workspace, lab=tmp_path)
    assert hidden == {"passed": False, "infrastructure": True,
                      "reason": "sandbox_boot"}


def test_node_grader_dispatches_the_tap_reporter(monkeypatch, tmp_path):
    def export(spec):
        name, raw = _seed_report(spec)
        export.spec = spec
        return _collector_result(raw, workspace_outputs={name: raw})

    _make_supervisor(monkeypatch, export)
    workspace = tmp_path / "ws"
    workspace.mkdir()
    hidden = runtime._grader_result("B2", 1, workspace, lab=tmp_path)
    assert hidden["passed"] is True
    # The collector must account for every check the real B2 oracle defines
    # (Task 1: checks-must-actually-run); the oracle grew with the audit's
    # supplemental regressions, so the count is derived, never pinned.
    assert hidden["tests_run"] == len(
        grade.node_check_case_ids(tasks.checks_source("B2"))
    )
    spec = export.spec
    assert spec.argv[:3] == ("/usr/bin/python3", "-B", "-I")
    assert spec.argv[spec.argv.index('--language')+1] == 'javascript'
    assert spec.argv[spec.argv.index('--node-reporter')+1] == '/opt/practical_node_rpc.mjs' 
    targets = {str(bind.target) for bind in spec.runtime_ro}
    assert "/opt/node" in targets and "/opt/checks.test.js" in targets
    assert "/opt/practical_node_rpc.mjs" in targets
    assert "/opt/practical_python_checks.py" not in targets


def test_cleanup_failure_overrides_a_complete_report(monkeypatch, tmp_path):
    def export(spec):
        name, raw = _seed_report(spec)
        return _collector_result(raw, workspace_outputs={name: raw}, cleanup_verified=False)

    _make_supervisor(monkeypatch, export)
    workspace = tmp_path / "ws"
    workspace.mkdir()
    hidden = runtime._grader_result("B1", 1, workspace, lab=tmp_path)
    assert hidden["infrastructure"] is True and hidden["passed"] is False


# --- Task 2: causal classification and the single eligibility gate ----------------


def _outcome_row(**overrides):
    row = {
        "correct": False, "functional_correct": False, "autonomous": False,
        "environment_passed": True, "review_required": False,
        "scoring_eligible": True, "failure": "workflow", "model_calls": 8,
    }
    row.update(overrides)
    return row


def _result(**overrides):
    return SimpleNamespace(**{"cleanup_verified": True, "infrastructure_error": None,
                              "timed_out": False} | overrides)


def _finalize(row, *, phases=(), phase_codes=(0,), native=(), driver=(), prompts=1,
              language="python", result=None, model_stop=False):
    runtime._finalize_outcome(
        row, phase_results=list(phases),
        phase_native=[{"exit_code": code} for code in phase_codes],
        native=list(native), driver=list(driver), prompt_count=prompts,
        language=language, result=result or _result(), model_stop=model_stop)
    return row


def _graded(expected_passed=True, **hidden):
    report = {"passed": expected_passed, "contract_invalid": False,
              "infrastructure": False, "checks_completed": 3}
    report.update(hidden)
    return {"hidden": report, "authored_tests": {"passed": True, "additional_count": 1}}


def test_infra_precedence_clears_stale_success_flags():
    row = _outcome_row(correct=True, autonomous=True, failure="passed")
    _finalize(row, phases=(_graded(),), result=_result(infrastructure_error="oom kill"))

    from benchmark.practical_evidence import is_scoring_eligible
    assert row["failure"] == "infrastructure"
    assert row["correct"] is False and row["autonomous"] is False
    assert row["functional_correct"] is True
    assert is_scoring_eligible({"status": "complete", **row}) is False


def test_grade_infrastructure_stays_above_any_functional_inference():
    row = _outcome_row(correct=True, autonomous=True)
    _finalize(row, phases=(_graded(infrastructure=True),))
    assert row["failure"] == "infrastructure"
    assert row["correct"] is False and row["functional_correct"] is None


def test_contract_invalid_forces_review_and_disqualifies_the_run():
    row = _outcome_row(autonomous=True, failure="workflow")
    _finalize(row, phases=(_graded(expected_passed=False, contract_invalid=True,
                                   checks_completed=1),))
    from benchmark.practical_evidence import is_scoring_eligible
    assert row["failure"] == "contract_error"
    assert row["review_required"] is True and row["scoring_eligible"] is False
    assert row["autonomous"] is False and row["correct"] is False
    assert is_scoring_eligible({"status": "complete", **row}) is False


def test_sigterm_without_snapshot_is_invalid_execution_never_wrong_result():
    # Audit latent case: SIGTERM (-15), eight model calls, no snapshot on disk.
    row = _outcome_row(failure="workflow")
    _finalize(row, phase_codes=(-15,))
    from benchmark.practical_evidence import is_scoring_eligible
    assert row["failure"] == "invalid_execution"
    assert row["functional_correct"] is None
    assert row["correct"] is False
    assert row["failure"] != "wrong_result"
    assert is_scoring_eligible({"status": "complete", **row}) is False


def test_unknown_failure_with_stale_success_flags_is_not_scoring_eligible():
    row = _outcome_row(correct=True, autonomous=True, failure="unknown")
    _finalize(row)

    assert row["failure"] == "unknown"
    assert row["functional_correct"] is None
    assert row["execution_valid"] is False
    assert row["workflow_complete"] is False
    assert row["review_required"] is True
    assert row["scoring_eligible"] is False
    assert row["correct"] is False and row["autonomous"] is False


def test_proven_functional_fault_requires_a_concluded_grader():
    row = _outcome_row(correct=False)
    _finalize(row, phases=(_graded(expected_passed=False),))
    assert row["failure"] == "wrong_result"
    assert row["functional_correct"] is False
    assert row["correct"] is False


def test_incomplete_observation_with_delimited_failure_keeps_the_delimitation():
    row = _outcome_row(failure="unknown")
    _finalize(row)
    assert row["failure"] == "unknown"
    assert row["functional_correct"] is None


def test_transport_api_errors_stay_unknown_never_configuration():
    through_faults = [
        {"type": "error", "part": {"message": "APIError: 500 connection reset by peer"}},
        {"type": "error", "part": {"message": "stream interrupted before completion"}},
    ]
    assert runtime._failure_for(None, through_faults) == "unknown"
    ambiguous = [{"type": "error", "part": {"message": "APIError: request failed"}}]
    assert runtime._failure_for(None, ambiguous) == "unknown"
    mixed = through_faults + ambiguous
    assert runtime._failure_for(None, mixed) == "unknown"
    attributed = [{"type": "error",
                   "part": {"message": "Model tried to call unavailable tool 'x'."}}]
    assert runtime._failure_for(None, attributed) == "unknown"


def test_registered_deadline_and_limit_cancellation_is_budget_exhausted():
    events = [SimpleNamespace(method="POST", status=400, outcome="budget_exhausted:compaction")]
    run = SimpleNamespace(timed_out=False, infrastructure_error=None, broker_events=events)
    assert runtime._failure_for(run, [], run_dir=Path("unused")) == "budget_exhausted"
    assert runtime._failure_for(_result(timed_out=True), [], run_dir=None) == "budget_exhausted"


def test_budget_exhausted_typing_survives_native_error_text():
    events = [SimpleNamespace(method="POST", status=400, outcome="budget_exhausted:main")]
    run = SimpleNamespace(timed_out=False, infrastructure_error=None, broker_events=events)
    native = [{"type": "error", "part": {"message": "budget_exhausted:main (opencode) APIError"}}]
    assert runtime._failure_for(run, native, run_dir=Path("unused")) == "budget_exhausted"


def test_driver_budget_halt_event_is_driver_scoped_and_finalizes_at_budget():
    lines = [
        {"_practical_driver": "budget_halt", "phase": 1,
         "stop_reason": "budget_exhausted:compaction"},
        {"type": "error", "part": {"message": "budget_exhausted:compaction"}},
    ]
    raw = b"\n".join(json.dumps(line).encode() for line in lines) + b"\n"
    native, driver = runtime._events(raw)
    assert [item.get("_practical_driver") for item in driver] == ["budget_halt"]
    assert native and native[0]["type"] == "error"

    events = [SimpleNamespace(method="POST", status=400, outcome="budget_exhausted:compaction")]
    run = SimpleNamespace(timed_out=False, infrastructure_error=None, broker_events=events)
    row = _outcome_row(failure=None)
    row["failure"] = runtime._failure_for(run, native, run_dir=Path("unused"))
    _finalize(row, driver=driver)

    assert row["failure"] == "budget_exhausted"
    assert row["deadline_exceeded"] is True


def test_phase_observation_for_code_requires_a_concluded_contract_check():
    assert runtime._phase_observed(_graded(), "python") is True
    assert runtime._phase_observed({"hidden": {"contract_invalid": False,
                                               "infrastructure": False,
                                               "checks_completed": 0}}, "python") is False
    assert runtime._phase_observed({"hidden": {"contract_invalid": True,
                                               "infrastructure": False,
                                               "checks_completed": 3}}, "python") is False
    assert runtime._phase_observed({"hidden": {"contract_invalid": False,
                                               "infrastructure": True,
                                               "checks_completed": 3}}, "python") is False


def test_phase_observation_for_mcp_reads_the_hidden_verdict():
    assert runtime._phase_observed({"hidden": {"passed": True}}, "mcp") is True
    assert runtime._phase_observed({"hidden": {"passed": False}}, "mcp") is True
    assert runtime._phase_observed({"hidden": {"passed": None}}, "mcp") is False
    assert runtime._phase_observed({"hidden": {"passed": True, "infrastructure": True}},
                                   "mcp") is False


def test_driver_budget_halt_finalizes_captures_and_does_not_retry(monkeypatch, tmp_path, capsys):
    from benchmark import practical_driver_v2 as driver

    halted = json.dumps({"type": "error",
                         "part": {"message": "budget_exhausted:compaction"}}).encode()
    config = tmp_path / "driver.json"
    config.write_text(json.dumps({"model": "fixture", "task": "C2",
                                  "prompts": ["implement"], "seconds": 30,
                                  "language": "mcp", "policy": {"mode": "benchmark"}}))
    monkeypatch.setattr(driver, "CONFIG_PATH", config)
    monkeypatch.setattr(driver, "METADATA_PATH", tmp_path / ".practical.json")
    monkeypatch.setattr(driver, "environment_preflight",
                        lambda language: {"passed": True, "checks": {}})
    commands: list[list[str]] = []

    def fake_guarded(command, budget, guard, *, stream=False):
        commands.append(command)
        return halted, b"", 88

    monkeypatch.setattr(driver, "run_guarded", fake_guarded)
    snapshots = []
    monkeypatch.setattr(driver, "_snapshot", lambda phase: snapshots.append(phase))

    assert driver.main() == 0

    events = [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.strip()]
    halt = next(event for event in events if event.get("_practical_driver") == "budget_halt")
    assert halt["stop_reason"] == "budget_exhausted:compaction" and halt["phase"] == 1
    phase = next(event for event in events if event.get("_practical_driver") == "phase")
    assert phase["exit_code"] == 88 and phase["stop_reason"] == "budget_exhausted:compaction"
    assert len(commands) == 1              # no further generation is attempted
    assert snapshots == [1]                # the reserved tests/snapshot still happen
    metadata = json.loads((tmp_path / ".practical.json").read_text(encoding="utf-8"))
    assert metadata["phases"][0]["stop_reason"] == "budget_exhausted:compaction"


# --- Task 3: capacity wait is preparation, never model budget ----------------------


def test_capacity_wait_constants_match_the_documented_bounds():
    assert runtime.CAPACITY_WAIT_SECONDS == 120.0
    assert runtime.CAPACITY_POLL_SECONDS == 2.0
    assert runtime.CAPACITY_STABLE_SAMPLES == 3


class _FakeClock:
    def __init__(self, start: float = 0.0):
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _sleeper(clock: _FakeClock, sleeps: list):
    def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        clock.advance(seconds)
    return sleep


def test_capacity_guard_requires_three_consecutive_ready_samples():
    clock = _FakeClock()
    sleeps: list = []
    samples = iter([False, True, True, True])
    ready = runtime.capacity_guard(
        lambda: next(samples), clock=clock, sleep=_sleeper(clock, sleeps))

    assert ready is True
    assert sleeps == [runtime.CAPACITY_POLL_SECONDS] * 3
    assert clock.now == 6.0    # polls two seconds between every probe sample


def test_capacity_guard_oscillation_never_starts_the_episode():
    clock = _FakeClock()
    sleeps: list = []
    calls = {"n": 0}

    def probe():
        calls["n"] += 1
        return calls["n"] % 2 == 1

    ready = runtime.capacity_guard(
        probe, clock=clock, sleep=_sleeper(clock, sleeps))

    assert ready is False
    assert sleeps == [runtime.CAPACITY_POLL_SECONDS] * 60   # waits the full 120s
    assert clock.now == 120.0                               # expires without readiness
    assert calls["n"] == 61


def test_capacity_guard_expires_when_the_probe_never_becomes_ready():
    clock = _FakeClock()
    sleeps: list = []
    side_effects: list = []

    def probe():
        side_effects.append(1)
        return False

    ready = runtime.capacity_guard(probe, clock=clock, sleep=_sleeper(clock, sleeps))

    assert ready is False
    assert max(side_effects, default=0) >= 1 and len(side_effects) == 61
    assert sleeps == [runtime.CAPACITY_POLL_SECONDS] * 60


# --- Task 5: task_contract_id regrade resolution (historical is never retroactive) --


def _regrade_dir(root, task, contract=None, protocol=None, *, monkeypatch=None):
    run_dir = root / f"run-{task}-{contract or 'legacy'}-{protocol or 'v2'}"
    run_dir.mkdir()
    # Legacy records carry the runtime's own frozen historical protocol id, not
    # the mutable live protocol global: suite-wide tests may mutate the latter.
    record = {"protocol": protocol or runtime._VERIFIED_HISTORICAL_PROTOCOL,
              "model": "m", "task": task}
    if contract:
        record["task_contract_id"] = contract
    (run_dir / "record.json").write_text(json.dumps(record), encoding="utf-8")
    with __import__("zipfile").ZipFile(run_dir / ".snapshot1.zip", "w") as archive:
        for name, content in tasks.reference_files(task, 0).items():
            archive.writestr(name, content)
    if monkeypatch is not None:
        import hashlib
        from benchmark.practical_campaign_v2 import _hash_value
        immutable={'task_contracts':{task:'historical-v2'}}
        manifest={'protocol_id':record['protocol'],'immutable':immutable,
                  'immutable_sha256':_hash_value(immutable)}
        manifest_path=root/'manifest.json'
        manifest_path.write_text(json.dumps(manifest))
        def digest(path):
            return hashlib.sha256(path.read_bytes()).hexdigest()
        census={'runs':[{'run_dir':str(run_dir),'record':{'task':task},
            'evidence':{p.name:{'sha256':digest(p)} for p in (run_dir/'record.json',run_dir/'.snapshot1.zip')}}],
            'outputs':[{'output':str(root),'protocol':record['protocol'],
                'manifest_sha256':digest(manifest_path),'immutable_hash_valid':True}]}
        census_path=root/'census.json'
        census_path.write_text(json.dumps(census))
        monkeypatch.setattr(runtime,'_HISTORICAL_CENSUS',census_path)
    return run_dir


def _bind_checks_exporter(seen):
    def export(spec):
        targets = {str(bind.target) for bind in spec.runtime_ro}
        if not targets & {"/opt/checks.test.js", "/opt/checks.py"}:
            return _run_result()          # the authored-tests sandbox has no checks
        for bind in spec.runtime_ro:
            if str(bind.target) == "/opt/checks.test.js":
                seen["source"] = Path(bind.source).read_text(encoding="utf-8")
        name, raw = _seed_report(spec)
        return _collector_result(raw, workspace_outputs={name: raw})

    return export


def test_regrade_defaults_to_historical_for_verified_legacy_records(
        monkeypatch, tmp_path):
    run_dir = _regrade_dir(tmp_path, "M1",monkeypatch=monkeypatch)
    seen = {}
    _make_supervisor(monkeypatch, _bind_checks_exporter(seen))
    verdict = runtime.regrade_episode(run_dir)

    assert verdict["task_contract_id"] == tasks.HISTORICAL_CONTRACT
    assert verdict["verdict_profile"] == "main"
    assert verdict["correct"] is True
    assert verdict["original_score_preserved"] is True
    assert "independent result" not in seen["source"]   # no future checks for legacy
    evaluation = json.loads(
        Path(verdict["evaluation_path"]).read_text(encoding="utf-8"))
    assert evaluation["task_contract_id"] == tasks.HISTORICAL_CONTRACT
    assert evaluation["grader_hashes"]["practical_tasks_v2.py"]


def test_missing_regrade_snapshot_is_unknown_and_requires_review(monkeypatch, tmp_path):
    run_dir = _regrade_dir(tmp_path, "M1",contract=tasks.HISTORICAL_CONTRACT)
    (run_dir / ".snapshot1.zip").unlink()

    verdict = runtime.regrade_episode(run_dir)

    assert verdict["correct"] is None
    assert verdict["functional_correct"] is None
    assert verdict["execution_valid"] is False
    assert verdict["workflow_complete"] is False
    assert verdict["review_required"] is True
    assert verdict["scoring_eligible"] is False


def test_legacy_regrade_does_not_trust_protocol_prefix(monkeypatch, tmp_path):
    run_dir = _regrade_dir(
        tmp_path, "M1", protocol=runtime._VERIFIED_HISTORICAL_PROTOCOL + "-forged")

    with pytest.raises(ValueError, match="verified historical provenance"):
        runtime.regrade_episode(run_dir)


def test_regrade_honors_the_explicit_contract_of_new_records(monkeypatch, tmp_path):
    run_dir = _regrade_dir(tmp_path, "M1", contract=tasks.M1_INDEPENDENT_CONTRACT)
    seen = {}
    _make_supervisor(monkeypatch, _bind_checks_exporter(seen))
    verdict = runtime.regrade_episode(run_dir)

    assert verdict["task_contract_id"] == tasks.M1_INDEPENDENT_CONTRACT
    assert verdict["verdict_profile"] == "main"
    assert verdict["correct"] is True
    assert "independent result" in seen["source"]       # strict oracle actually graded


def test_incompatible_override_grades_as_sensitivity_never_main(monkeypatch, tmp_path):
    run_dir = _regrade_dir(tmp_path, "M1",monkeypatch=monkeypatch)
    seen = {}
    _make_supervisor(monkeypatch, _bind_checks_exporter(seen))
    verdict = runtime.regrade_episode(
        run_dir, evaluation_profile=tasks.M1_INDEPENDENT_CONTRACT)

    assert "independent result" in seen["source"]
    assert verdict["verdict_profile"] == "sensitivity"
    assert verdict["correct"] is None
    assert verdict["task_contract_id"] == tasks.M1_INDEPENDENT_CONTRACT
    assert verdict["original_score_preserved"] is True
    evaluation = json.loads(
        Path(verdict["evaluation_path"]).read_text(encoding="utf-8"))
    assert evaluation["task_contract_id"] == tasks.M1_INDEPENDENT_CONTRACT
    assert evaluation["verdict"]["verdict_profile"] == "sensitivity"
    seen.clear()
    compatible = runtime.regrade_episode(run_dir,
                                         evaluation_profile=tasks.HISTORICAL_CONTRACT)
    assert compatible["verdict_profile"] == "main"
    assert compatible["correct"] is True
    assert "independent result" not in seen["source"]


def test_unknown_contract_or_foreign_protocol_requires_review(monkeypatch, tmp_path):
    run_dir = _regrade_dir(tmp_path, "M1", contract="future-m1-v9")
    seen = {}
    _make_supervisor(monkeypatch, _bind_checks_exporter(seen))
    with pytest.raises(ValueError, match="review required"):
        runtime.regrade_episode(run_dir)
    foreign = _regrade_dir(tmp_path, "M1", protocol="practical-agent-foreign-v1")
    with pytest.raises(ValueError, match="review required"):
        runtime.regrade_episode(foreign)
    inapplicable = _regrade_dir(tmp_path, "M1",
                                contract=tasks.M1_INDEPENDENT_CONTRACT)
    with pytest.raises(ValueError, match="review required"):
        runtime.regrade_episode(inapplicable,
                                evaluation_profile="mcp-no-confirmed-replay-v1")
    b2_dir = _regrade_dir(tmp_path, "B2")
    with pytest.raises(ValueError, match="review required"):
        runtime.regrade_episode(b2_dir,
                                evaluation_profile=tasks.M1_INDEPENDENT_CONTRACT)
    assert not list(run_dir.glob("evaluations/*/*"))              # nothing appended


def test_regraded_sensitivity_evaluations_carry_both_contracts(monkeypatch, tmp_path):
    run_dir = _regrade_dir(tmp_path, "M1", contract=tasks.M1_INDEPENDENT_CONTRACT)
    seen = {}
    _make_supervisor(monkeypatch, _bind_checks_exporter(seen))
    verdict = runtime.regrade_episode(run_dir,
                                      evaluation_profile=tasks.HISTORICAL_CONTRACT)

    assert "independent result" not in seen["source"]
    assert verdict["verdict_profile"] == "sensitivity"
    assert verdict["correct"] is None
    assert verdict["task_contract_id"] == tasks.HISTORICAL_CONTRACT
    assert verdict["record_task_contract_id"] == tasks.M1_INDEPENDENT_CONTRACT
    evaluation = json.loads(
        Path(verdict["evaluation_path"]).read_text(encoding="utf-8"))
    assert evaluation["task_contract_id"] == tasks.HISTORICAL_CONTRACT
    assert evaluation["verdict"]["record_task_contract_id"] == \
        tasks.M1_INDEPENDENT_CONTRACT


# --- Task 6: authored-test regression quality wiring inside the episode ---------


def _episode_snapshot_bytes():
    """B1 candidate state: fixed sources plus one authored regression test."""
    files = dict(tasks.seed_sources("B1"))
    files["orders/report.py"] = (
        "def build_report(records):\n"
        "    totals = {}\n"
        "    seen = set()\n"
        "    for record in records:\n"
        "        if record['id'] in seen:\n"
        "            continue\n"
        "        seen.add(record['id'])\n"
        "        customer = record['customer']\n"
        "        totals[customer] = totals.get(customer, 0) + record['amount_cents']\n"
        "    return totals\n")
    files["tests/test_agent.py"] = (
        "import unittest\n"
        "from orders.report import build_report\n\n"
        "class AgentAuthoredTest(unittest.TestCase):\n"
        "    def test_first_delivery_wins_and_refunds_sum(self):\n"
        "        self.assertEqual(build_report([\n"
        "            {'id':'x','customer':'Ada','amount_cents':100},\n"
        "            {'id':'x','customer':'Other','amount_cents':900},\n"
        "            {'id':'y','customer':'Ada','amount_cents':-25},\n"
        "        ]), {'Ada':75})\n")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in sorted(files.items()):
            archive.writestr(name, content)
    return buffer.getvalue()


def _install_quality_episode_supervisor(monkeypatch):
    """Branch the fake supervisor: grader with checks bind, candidate authored
    suite, and the restored-seed suite (its workspace carries 'seedcheck')."""
    calls = []

    def export(spec):
        calls.append(spec)
        targets = {str(bind.target) for bind in spec.runtime_ro}
        if targets & {"/opt/checks.py", "/opt/checks.test.js"}:
            name, raw = _seed_report(spec)
            return _collector_result(raw, workspace_outputs={name: raw})
        if "seedcheck" in str(spec.workspace):
            return _run_result(returncode=1, output=(
                b"Ran 2 tests in 0.001s\n\nFAILED (failures=1)\n"
                b"FAIL: test_first_delivery_wins_and_refunds_sum "
                b"(tests.test_agent.AgentAuthoredTest)\n"))
        return _run_result(output=b"Ran 2 tests in 0.001s\n\nOK\n")

    class Supervisor:
        def __init__(self, *args, **kwargs):
            pass

        def run(self, spec):
            return export(spec)

    monkeypatch.setattr(runtime, "SandboxSupervisor", Supervisor)
    return calls


def _install_quality_episode_agent(monkeypatch, snapshot_bytes):
    driver_events = [
        json.dumps({"_practical_driver": "environment", "passed": True}),
        json.dumps({"_practical_driver": "phase", "phase": 1, "exit_code": 0,
                    "session_id": "sess-quality"}),
    ]
    output = ("\n".join(driver_events) + "\n").encode()

    def run_agent(*args, **kwargs):
        return SimpleNamespace(
            output=output, cleanup_verified=True, infrastructure_error=None,
            broker_events=[], returncode=0, timed_out=False, output_limited=False,
            resource_evidence={}, namespace_evidence={}, network_evidence={},
            workspace_audit={}, broker_transcript_evidence={},
            workspace_outputs={".snapshot1.zip": snapshot_bytes})

    monkeypatch.setattr(runtime, "_run_agent", run_agent)
    monkeypatch.setattr(runtime, "_stop_model_server", lambda process: True)


def _run_quality_episode(monkeypatch, tmp_path, task="B1"):
    return runtime._execute_episode(
        task, "fixture", {"id": "baseline", "context_tokens": 16384,
                          "cache_prompt": False},
        1, tmp_path / "output",
        {"fixture": {"alias": "fixture", "path": "fixture.gguf"}},
        lab=tmp_path, server_process=None, upstream_port=12345)


def _sandbox_kinds(calls):
    kinds = []
    for spec in calls:
        targets = {str(bind.target) for bind in spec.runtime_ro}
        if targets & {"/opt/checks.py", "/opt/checks.test.js"}:
            kinds.append("grader")
        elif "seedcheck" in str(spec.workspace):
            kinds.append("seed")
        else:
            kinds.append("authored")
    return kinds


def test_full_episode_records_verified_authored_test_quality(monkeypatch, tmp_path):
    calls = _install_quality_episode_supervisor(monkeypatch)
    _install_quality_episode_agent(monkeypatch, _episode_snapshot_bytes())
    row = _run_quality_episode(monkeypatch, tmp_path)

    assert row["authored_test_quality"] == "regression_detected"
    assert row["failure"] == "passed"
    assessment = row["phases"][0]["authored_test_quality"]
    assert assessment["quality"] == "regression_detected"
    assert assessment["seed"]["count"] == 2 and assessment["candidate"]["count"] == 2
    assert assessment["provenance"]["snapshot_sha256"]
    assert len(assessment["provenance"]["restored_seed_sha256"]) == \
        len(tasks.seed_sources("B1"))
    assert _sandbox_kinds(calls) == ["grader", "authored", "seed"]
    # The episode's own input keeps the seeded candidate state; the restore
    # went to a temporary copy only.
    delivered = (Path(row["run_dir"]) / "input/orders/report.py").read_text(
        encoding="utf-8")
    assert delivered == tasks.seed_sources("B1")["orders/report.py"]
    input_files = sorted(path.relative_to(Path(row["run_dir"]) / "input").as_posix()
                         for path in (Path(row["run_dir"]) / "input").rglob("*")
                         if path.is_file())
    assert "tests/test_agent.py" not in input_files
    evaluation = json.loads(
        Path(row["evaluation_path"]).read_text(encoding="utf-8"))
    assert evaluation["verdict"]["authored_test_quality"] == "regression_detected"
    persisted = json.loads(
        (Path(row["run_dir"]) / "record.json").read_text(encoding="utf-8"))
    assert persisted["authored_test_quality"] == "regression_detected"


def test_episode_assessment_errors_become_unverified_and_stay_scoring_eligible(
        monkeypatch, tmp_path):
    from benchmark import practical_test_quality as quality_module

    _install_quality_episode_supervisor(monkeypatch)
    _install_quality_episode_agent(monkeypatch, _episode_snapshot_bytes())

    def broken(*args, **kwargs):
        raise RuntimeError("assessment exploded")

    monkeypatch.setattr(quality_module, "assess_authored_regression", broken)
    row = _run_quality_episode(monkeypatch, tmp_path)

    assert row["authored_test_quality"] == "unverified"
    phase = row["phases"][0]["authored_test_quality"]
    assert phase["quality"] == "unverified"
    assert phase["seed"] is None and phase["candidate"] is None
    assert phase["provenance"] == {"snapshot_sha256": None,
                                   "restored_seed_sha256": {}}
    # The episode verdict is untouched: a broken diagnosis is not a fault of
    # the agent and never spoils scoring eligibility.
    assert row["failure"] == "passed" and row["scoring_eligible"] is True
    assert row["functional_correct"] is True and row["correct"] is True
    evaluation = json.loads(
        Path(row["evaluation_path"]).read_text(encoding="utf-8"))
    assert evaluation["verdict"]["authored_test_quality"] == "unverified"


def test_mcp_only_episode_marks_quality_not_applicable_without_a_sandbox(
        monkeypatch, tmp_path):
    calls = _install_quality_episode_supervisor(monkeypatch)
    _install_quality_episode_agent(monkeypatch, _episode_snapshot_bytes())
    row = _run_quality_episode(monkeypatch, tmp_path, task="C2")

    assert row["authored_test_quality"] == "not_applicable"
    # MCP grading confronts trusted evidence, not a sandbox, and the mcp-only
    # branch never adds an authored-suite quality to the phase results.
    assert row["phases"][0]["hidden"]["passed"] is False
    assert "authored_test_quality" not in row["phases"][0]
    assert calls == []                    # no quality sandbox ever launched
