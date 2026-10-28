from __future__ import annotations

import json

import pytest

from benchmark import practical_campaign_v2 as campaign


TASKS = ("B1", "B2", "C1", "C2", "M1", "M2", "D1", "D2")
CORE = TASKS[:6]
HARD = TASKS[-2:]
BASELINE = {"id": "baseline", "context_tokens": 16384, "cache_prompt": False}


def test_baseline_schedule_has_rotated_unique_full_episode_identities():
    models = ("a", "b", "c")
    rows = campaign.baseline_schedule(models, tasks=("B1", "B2", "C1", "C2"))

    assert len(rows) == 36
    assert len({campaign.episode_key(row) for row in rows}) == 36
    assert [(row["task"], row["model"]) for row in rows if row["repetition"] == 1] == [
        ("B1", "a"), ("B1", "b"), ("B1", "c"),
        ("B2", "a"), ("B2", "b"), ("B2", "c"),
        ("C1", "a"), ("C1", "b"), ("C1", "c"),
        ("C2", "a"), ("C2", "b"), ("C2", "c"),
    ]
    assert [(row["task"], row["model"]) for row in rows if row["repetition"] == 2][:3] == [
        ("B2", "b"), ("B2", "c"), ("B2", "a")
    ]


def test_approved_five_model_baseline_is_exactly_120_unique_episodes():
    rows = campaign.baseline_schedule(("a", "b", "c", "d", "e"))

    assert len(rows) == 120
    assert len({campaign.episode_key(row) for row in rows}) == 120


def test_frozen_real_task_manifest_captures_approved_counts_and_21h12_cap():
    from types import SimpleNamespace
    from benchmark import practical_tasks_v2

    models = {model: {"alias": model, "path": f"models/{model}.gguf", "sha256": model}
              for model in ("a", "b", "c", "d", "e")}
    runtime = SimpleNamespace(__file__=str(campaign.ROOT / "benchmark" / "practical_runtime_v2.py"))
    manifest = campaign.build_manifest(
        models, tasks_module=practical_tasks_v2, runtime_module=runtime,
        gpu_free_floor_mib=7000,
    )

    schedule = manifest["immutable"]["schedule"]
    assert schedule["baseline_episodes"] == 120
    assert schedule["maximum_tuning_episodes"] == 24
    assert schedule["holdout_episodes"] == 12
    assert schedule["maximum_baseline_seconds"] == 14 * 3600
    assert schedule["maximum_total_seconds"] == 21 * 3600 + 12 * 60
    assert manifest["immutable"]["gpu_free_floor_mib"] == 7000
    default_manifest = campaign.build_manifest(
        models, tasks_module=practical_tasks_v2, runtime_module=runtime,
    )
    assert default_manifest["immutable_sha256"] != manifest["immutable_sha256"]
    source_hashes = manifest["immutable"]["source_hashes"]
    assert "benchmark/practical_tasks_v2.py" in source_hashes
    assert "benchmark/practical_runtime_v2.py" in source_hashes
    assert "benchmark/practical_mcp_grading_v2.py" in source_hashes
    assert "benchmark/practical_driver_v2.py" in source_hashes


def test_full_identity_rejects_duplicate_but_distinguishes_profiles():
    row = {
        "protocol": campaign.PROTOCOL,
        "model": "m",
        "profile": "baseline",
        "task": "D1",
        "repetition": 2,
    }
    other_profile = {**row, "profile": "cache_on"}

    assert campaign.episode_key(row) != campaign.episode_key(other_profile)
    with pytest.raises(ValueError, match="duplicate"):
        campaign.ensure_unique_records([row, dict(row)])


def test_baseline_ranking_counts_successes_and_elapsed_from_failed_attempts():
    rows = []
    for model in ("fast", "complete"):
        for task in TASKS:
            for repetition in (1, 2, 3):
                ok = model == "complete" or task not in CORE or not (task == "B1" and repetition == 1)
                rows.append({
                    "protocol": campaign.PROTOCOL,
                    "model": model,
                    "profile": "baseline",
                    "task": task,
                    "repetition": repetition,
                    "status": "complete",
                    "correct": ok,
                    "autonomous": ok,
                    "failure": "passed" if ok else "wrong_result",
                    "seconds": 100 if model == "fast" and not ok else (10 if model == "fast" else 30),
                    "vram_mib": 300 if model == "fast" else 400,
                })

    ranking = campaign.rank_models(rows, ("fast", "complete"), metric_tasks=CORE)

    assert ranking[0]["model"] == "complete"
    assert ranking[1]["core_completed"] == 17
    assert ranking[1]["core_3_of_3"] == 5
    assert ranking[1]["core_elapsed_seconds"] == 270
    assert all(item["eligible"] for item in ranking)


def test_incomplete_baseline_coverage_is_never_eligible():
    rows = [
        {
            "protocol": campaign.PROTOCOL,
            "model": "m",
            "profile": "baseline",
            "task": task,
            "repetition": repetition,
            "status": "complete",
            "correct": True,
            "autonomous": True,
            "seconds": 1,
        }
        for task in TASKS
        for repetition in (1, 2, 3)
        if (task, repetition) != ("D2", 3)
    ]

    ranking = campaign.rank_models(rows, ("m",))

    assert ranking[0]["coverage_complete"] is False
    assert ranking[0]["eligible"] is False


def test_hard_leader_is_second_finalist_or_second_core_candidate_on_tie():
    core = [
        {"model": "primary", "eligible": True},
        {"model": "fallback", "eligible": True},
    ]
    hard = [{"model": "hard", "eligible": True}, {"model": "primary", "eligible": True}]

    assert campaign.select_finalists(core, hard) == ["primary", "hard"]
    assert campaign.select_finalists(core, [hard[1]]) == ["primary", "fallback"]


def test_tuning_and_holdout_schedules_have_approved_sizes_and_profiles():
    finalists = ("a", "b")
    cache_on = {"id": "cache_on", "context_tokens": 16384, "cache_prompt": True}
    context_32k = {"id": "context_32k", "context_tokens": 32768, "cache_prompt": True}

    cache_rows = campaign.tuning_schedule(finalists, cache_on, tasks=HARD)
    context_rows = campaign.tuning_schedule(finalists, context_32k, tasks=HARD)
    holdout_rows = campaign.holdout_schedule(
        finalists,
        {"a": context_32k, "b": cache_on},
        tasks=("H1", "H2"),
    )

    assert len(cache_rows) == len(context_rows) == len(holdout_rows) == 12
    assert {row["profile"] for row in cache_rows} == {"cache_on"}
    assert {row["profile"] for row in context_rows} == {"context_32k"}
    assert {row["profile"] for row in holdout_rows if row["model"] == "a"} == {"context_32k"}
    assert {row["profile"] for row in holdout_rows if row["model"] == "b"} == {"cache_on"}


def test_profile_choice_uses_completion_then_elapsed_then_memory():
    rows = []
    for profile, ok_count, seconds, vram in (
        ("baseline", 4, 10, 100),
        ("cache_on", 5, 100, 500),
        ("context_32k", 5, 20, 200),
    ):
        for task in HARD:
            for repetition in (1, 2, 3):
                index = len([row for row in rows if row["profile"] == profile])
                ok = index < ok_count
                rows.append({
                    "protocol": campaign.PROTOCOL,
                    "model": "m",
                    "profile": profile,
                    "task": task,
                    "repetition": repetition,
                    "status": "complete",
                    "correct": ok,
                    "autonomous": ok,
                    "failure": "passed" if ok else "wrong_result",
                    "seconds": seconds,
                    "vram_mib": vram,
                })

    assert campaign.select_profile(rows, ("m",), ("baseline", "cache_on", "context_32k"), tasks=HARD) == "context_32k"


def test_profile_winner_is_selected_independently_for_each_finalist():
    rows = []
    for model, wins in (("a", {"cache_on": 5, "baseline": 4}),
                        ("b", {"cache_on": 4, "baseline": 5})):
        for profile, success_count in wins.items():
            for index, (task, repetition) in enumerate(
                    (task, repetition) for task in HARD for repetition in (1, 2, 3)):
                success = index < success_count
                rows.append({
                    "protocol": campaign.PROTOCOL, "model": model, "profile": profile,
                    "task": task, "repetition": repetition, "status": "complete",
                    "correct": success, "autonomous": success,
                    "failure": "passed" if success else "wrong_result",
                })

    assert campaign.select_profiles_per_model(
        rows, ("a", "b"), ("baseline", "cache_on"), tasks=HARD,
    ) == {"a": "cache_on", "b": "baseline"}


def test_atomic_json_write_leaves_resumable_document(tmp_path):
    path = tmp_path / "records.json"
    campaign.atomic_write_json(path, {"records": [{"task": "B1"}]})

    assert json.loads(path.read_text(encoding="utf-8")) == {"records": [{"task": "B1"}]}
    assert list(tmp_path.iterdir()) == [path]


def test_summary_reports_success_median_all_elapsed_and_explicit_profile_config(tmp_path):
    rows = []
    for repetition, seconds, success in ((1, 10, True), (2, 30, False), (3, 20, True)):
        rows.append({
            "protocol": campaign.PROTOCOL, "stage": "cache_on", "model": "a",
            "profile": "cache_on", "profile_config": {
                "id": "cache_on", "context_tokens": 16384, "cache_prompt": True,
            },
            "task": "B1", "repetition": repetition, "status": "complete",
            "correct": success, "autonomous": success, "seconds": seconds,
            "failure": "passed" if success else "wrong_result",
            "tool_errors": 1, "vram_mib": 100, "ram_mib": 200,
            "model_contract": {
                "alias": "coder-Q4_K_M", "path": "models/coder-Q4_K_M.gguf",
                "sha256": "abcdef1234567890",
            },
            "artifact_identity": {
                "model_sha256": "abcdef1234567890",
                "snapshot_sha256": {".snapshot1.zip": "large-per-attempt-hash"},
            },
        })

    campaign._write_summaries(tmp_path, rows, _fake_tasks())
    summary = campaign._summary_rows(rows, _fake_tasks())[0]
    csv_text = (tmp_path / "summary.csv").read_text(encoding="utf-8")
    markdown = (tmp_path / "summary.md").read_text(encoding="utf-8")

    assert summary["all_time_seconds"] == 60
    assert summary["median_success_seconds"] == 15
    assert summary["basic_completed"] == 2
    assert summary["basic_episodes"] == 3
    assert summary["context_tokens"] == 16384
    assert summary["cache_prompt"] is True
    assert summary["max_output_tokens"] == 4096
    assert summary["model_artifact_basename"] == "coder-Q4_K_M.gguf"
    assert summary["model_sha256"] == "abcdef1234567890"
    assert summary["quantization"] == "Q4_K_M"
    assert "snapshot_sha256" not in summary["config_artifact_identity"]
    assert "median_success_seconds" in csv_text
    assert "2/3" in markdown
    assert "16384/cache-on/4096/q4_0/Q4_K_M" in markdown
    assert "coder-Q4_K_M.gguf abcdef123456" in markdown


def test_profile_probe_infrastructure_failure_is_retryable_and_not_permanent(tmp_path):
    class FlakyProbe:
        def __init__(self):
            self.calls = 0

        def probe_profile(self, model, profile, *, lab, output=None):
            self.calls += 1
            if self.calls == 1:
                return {"passed": False, "status": "infrastructure", "failure": "infrastructure"}
            return {"passed": True, "status": "passed"}

    runtime = FlakyProbe()
    manifest = {"probe_results": {}, "probe_failures": {}, "profile_blocks": {}}
    transient_skips = set()
    profile = {"id": "cache_on", "context_tokens": 16384, "cache_prompt": True}

    assert campaign._profile_probe(
        "m", profile, output=tmp_path, manifest=manifest, runtime=runtime,
        lab=tmp_path, transient_skips=transient_skips, rows=[],
    ) is False
    assert "m|cache_on" not in manifest["profile_blocks"]
    assert "m|cache_on" in manifest["probe_failures"]

    assert campaign._profile_probe(
        "m", profile, output=tmp_path, manifest=manifest, runtime=runtime,
        lab=tmp_path, transient_skips=set(), rows=[],
    ) is True
    assert "m|cache_on" in manifest["probe_results"]
    assert runtime.calls == 2


def test_tool_call_diagnostic_does_not_exclude_model_from_task_matrix(tmp_path):
    class NoToolCall:
        def probe_profile(self, model, profile, *, lab, output=None):
            return {
                "passed": False,
                "status": "capability_diagnostic",
                "failure": "tool_call_not_observed",
                "model": model,
                "profile": profile["id"],
            }

    key = "m|baseline"
    manifest = {"probe_results": {}, "profile_diagnostics": {}, "probe_failures": {},
                "profile_blocks": {}}

    allowed = campaign._profile_probe(
        "m", BASELINE, output=tmp_path, manifest=manifest, runtime=NoToolCall(),
        lab=tmp_path, transient_skips=set(), rows=[],
    )

    assert allowed is True
    assert manifest["profile_diagnostics"][key]["failure"] == "tool_call_not_observed"
    assert key not in manifest["profile_blocks"]
    assert key not in manifest["probe_failures"]


def test_retried_episode_upserts_resume_and_preserves_attempt_metrics(tmp_path):
    class InterruptOnce:
        def __init__(self):
            self.calls = 0

        def run_episode(self, *args, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return {"failure": "infrastructure", "seconds": 3, "tool_errors": 2, "vram_mib": 300}
            raise KeyboardInterrupt

    class Success:
        def run_episode(self, *args, **kwargs):
            return {
                "failure": None, "correct": True, "autonomous": True,
                "seconds": 4, "tool_errors": 1, "vram_mib": 250,
                "artifact_identity": {"model_hash": "abc"},
            }

    tasks = _fake_tasks()
    models = {"m": {"alias": "m", "sha256": "abc"}}
    output = tmp_path / "resume"
    output.mkdir()
    manifest = campaign.build_manifest(models, tasks_module=tasks, runtime_module=object())
    episode = campaign.baseline_schedule(("m",), tasks=("B1",))[0]
    rows = []

    with pytest.raises(KeyboardInterrupt):
        campaign._run_episode(
            episode, output=output, rows=rows, runtime=InterruptOnce(), models=models,
            lab=tmp_path, tasks_module=tasks, manifest=manifest,
        )
    assert rows[0]["status"] == "interrupted"
    assert len(campaign.load_records(output)) == 1

    record = campaign._run_episode(
        episode, output=output, rows=rows, runtime=Success(), models=models,
        lab=tmp_path, tasks_module=tasks, manifest=manifest,
    )

    assert len(rows) == 1
    assert record["status"] == "complete"
    assert record["attempt_count"] == 2
    assert record["seconds"] == 7
    assert record["tool_errors"] == 3
    assert record["vram_mib"] == 300
    assert len(record["attempt_results"]) == 2
    assert len(campaign.load_records(output)) == 1


def test_regrade_run_cli_writes_derived_results_without_inference(tmp_path, monkeypatch, capsys):
    class Runtime:
        def regrade_run(self, output):
            assert output == tmp_path
            return [{"task": "C2", "correct": True}]

    monkeypatch.setattr(campaign, "_load_runtime_and_tasks", lambda: (Runtime(), object()))

    assert campaign.main(["--regrade-run", "--output", str(tmp_path)]) == 0
    payload = json.loads((tmp_path / "regrades.json").read_text(encoding="utf-8"))
    assert payload["episodes"] == [{"task": "C2", "correct": True}]
    assert json.loads(capsys.readouterr().out)["inference_started"] is False


def _fake_tasks():
    from types import SimpleNamespace

    def seed_task(task, workspace):
        return f"task prompt {task}"

    return SimpleNamespace(
        TASKS=TASKS,
        HOLDOUTS=("H1", "H2"),
        TASK_SPECS={task: {
            "phases": 2 if task == "D1" else 1,
            "seconds": 720,
            "difficulty": (
                "basic" if task in {"B1", "B2"}
                else "everyday" if task in {"C1", "C2"}
                else "medium" if task in {"M1", "M2"}
                else "hard" if task in {"D1", "D2"}
                else "holdout"
            ),
        } for task in (*TASKS, "H1", "H2")},
        seed_task=seed_task,
        followup_prompt=lambda task: f"followup {task}",
        checks_source=lambda task, phase=1: f"check {task}:{phase}",
        reference_files=lambda task, variant=0, phase=1: {f"{task}-{phase}-{variant}.txt": f"reference {task}:{phase}:{variant}"},
        wrong_files=lambda task: [{"file": f"{task}.txt", "content": "mutant"}],
    )


class _FakeRuntime:
    def __init__(self):
        self.episode_calls = []
        self.probe_calls = []

    def validate_environment(self, *, lab):
        return {"passed": True, "checks": {"mock": True}, "runtime_versions": {"python": "3.12-test"}, "failures": []}

    def probe_profile(self, model, profile, *, lab, output=None):
        self.probe_calls.append((model, profile["id"]))
        return {"passed": True, "model": model, "profile": profile["id"]}

    def run_episode(self, model, task, profile, repetition, output, models, *, lab):
        self.episode_calls.append((model, task, profile["id"], repetition))
        return {
            "correct": True,
            "autonomous": True,
            "failure": None,
            "seconds": 10,
            "tool_errors": 0,
            "vram_mib": 100,
            "artifact_identity": {"model_hash": models[model]["sha256"]},
            "phase_results": [{"phase": 1, "correct": True}],
        }


@pytest.mark.parametrize("trigger_profile", ["cache_on", "context_32k"])
def test_tuning_quarantine_returns_review_required_without_selecting_profiles(tmp_path, trigger_profile):
    class ReviewingRuntime(_FakeRuntime):
        def run_episode(self, model, task, profile, repetition, output, models, *, lab):
            result = super().run_episode(model, task, profile, repetition, output, models, lab=lab)
            if profile['id'] == trigger_profile and task == 'D2':
                result.update(review_required=True, failure='task_review', model_tool_errors=0,
                              tool_review={'reason': 'unattributed_tool_error'})
            return result
    runtime = ReviewingRuntime()
    models = {model: {'alias': model, 'revision': 'test', 'path': model + '.gguf', 'sha256': 'a' * 64}
              for model in ('a', 'b')}
    manifest = campaign.run_campaign(tmp_path, models=models, tasks_module=_fake_tasks(),
                                     runtime=runtime, lab=tmp_path / 'lab')
    assert manifest['status'] == 'review_required'
    assert sum(task == 'D2' and profile == trigger_profile
               for _, task, profile, _ in runtime.episode_calls) == 1
    assert not any(task.startswith('H') for _, task, _, _ in runtime.episode_calls)
    advice = json.loads((tmp_path / 'recommendation.json').read_text())
    assert advice['candidate_model'] is None


def test_holdout_quarantine_returns_review_required_without_recommendation(tmp_path):
    class ReviewingRuntime(_FakeRuntime):
        def run_episode(self, model, task, profile, repetition, output, models, *, lab):
            result = super().run_episode(model, task, profile, repetition, output, models, lab=lab)
            if task in _fake_tasks().HOLDOUTS:
                result.update(review_required=True, failure='task_review', model_tool_errors=0,
                              tool_review={'reason': 'unattributed_tool_error'})
            return result

    runtime = ReviewingRuntime()
    models = {model: {'alias': model, 'revision': 'test', 'path': model + '.gguf', 'sha256': 'a' * 64}
              for model in ('a', 'b')}
    manifest = campaign.run_campaign(tmp_path, models=models, tasks_module=_fake_tasks(),
                                     runtime=runtime, lab=tmp_path / 'lab')
    assert manifest['status'] == 'review_required'
    reviewed_task = next(task for _, task, _, _ in runtime.episode_calls if task in _fake_tasks().HOLDOUTS)
    assert sum(task == reviewed_task for _, task, _, _ in runtime.episode_calls) == 1
    advice = json.loads((tmp_path / 'recommendation.json').read_text())
    assert advice['candidate_model'] is None


def test_mocked_campaign_runs_all_stages_then_resumes_without_repeating(tmp_path):
    models = {model: {"alias": model, "revision": "test", "path": f"models/{model}.gguf", "sha256": f"hash-{model}"}
              for model in ("a", "b")}
    runtime = _FakeRuntime()

    manifest = campaign.run_campaign(
        tmp_path,
        models=models,
        tasks_module=_fake_tasks(),
        runtime=runtime,
        lab=tmp_path / "lab",
    )

    assert manifest["status"] == "complete"
    assert manifest["finalists"] == ["a", "b"]
    assert manifest["record_count"] == 84
    assert manifest["stage_status"] == {
        "baseline": "complete", "cache_on": "complete", "context_32k": "complete", "holdout": "complete"
    }
    assert len(runtime.episode_calls) == 84
    assert len(runtime.probe_calls) == 6
    status = json.loads((tmp_path / "status.json").read_text(encoding="utf-8"))
    assert status["status"] == "complete"
    assert status["episodes_by_stage"]["cache_on"]["complete"] == 12
    assert status["episodes_by_stage"]["context_32k"]["complete"] == 12
    assert (tmp_path / "summary.csv").is_file()
    assert (tmp_path / "summary.md").is_file()
    assert (tmp_path / "recommendation.json").is_file()
    resumed = campaign.run_campaign(
        tmp_path,
        models=models,
        tasks_module=_fake_tasks(),
        runtime=runtime,
        lab=tmp_path / "lab",
    )
    assert resumed["status"] == "complete"
    assert len(runtime.episode_calls) == 84


def test_real_holdout_specs_are_not_folded_into_hard_summary():
    from benchmark import practical_tasks_v2

    rows = [{
        "protocol": campaign.PROTOCOL, "stage": "holdout", "profile": "baseline",
        "model": "fixture", "task": task, "repetition": repetition,
        "status": "complete", "correct": True, "autonomous": True, "seconds": 1,
        "failure": "passed",
    } for task in ("H1", "H2") for repetition in (1, 2, 3)]
    summary = campaign._summary_rows(rows, practical_tasks_v2)[0]
    assert summary["holdout_completed"] == 6
    assert summary["holdout_3_of_3"] == 2
    assert summary["hard_completed"] == 0
    assert summary["hard_3_of_3"] == 0


def test_runtime_versions_are_frozen_after_first_execution(tmp_path):
    models = {model: {"alias": model, "revision": "test", "path": f"models/{model}.gguf", "sha256": f"hash-{model}"}
              for model in ("a", "b")}
    runtime = _FakeRuntime()
    expected = campaign.build_manifest(models, tasks_module=_fake_tasks(), runtime_module=runtime)
    output = tmp_path / "versions"
    output.mkdir()
    expected["status"] = "interrupted"
    expected["runtime_versions"] = {"python": "3.11-old"}
    expected["runtime_versions_sha256"] = campaign._hash_value(expected["runtime_versions"])
    campaign.atomic_write_json(output / "manifest.json", expected)

    manifest = campaign.run_campaign(
        output,
        models=models,
        tasks_module=_fake_tasks(),
        runtime=runtime,
        lab=tmp_path / "lab",
    )

    assert manifest["status"] == "blocked"
    assert manifest["failure"] == "runtime_versions_changed"
    assert manifest["runtime_versions"] == {"python": "3.11-old"}
    assert runtime.episode_calls == []


def test_infrastructure_failure_retries_once_then_blocks_campaign(tmp_path):
    class InfrastructureRuntime(_FakeRuntime):
        def run_episode(self, model, task, profile, repetition, output, models, *, lab):
            self.episode_calls.append((model, task, profile["id"], repetition))
            return {"failure": "infrastructure", "correct": False, "autonomous": False, "seconds": 2}

    models = {model: {"alias": model, "revision": "test", "path": f"models/{model}.gguf", "sha256": f"hash-{model}"}
              for model in ("a", "b")}
    runtime = InfrastructureRuntime()

    manifest = campaign.run_campaign(
        tmp_path,
        models=models,
        tasks_module=_fake_tasks(),
        runtime=runtime,
        lab=tmp_path / "lab",
    )

    records = campaign.load_records(tmp_path)
    assert manifest["status"] == "blocked"
    assert len(runtime.episode_calls) == 2
    assert records[0]["status"] == "blocked"
    assert records[0]["attempt_count"] == 2
    assert records[0]["seconds"] == 4


def test_explicit_infrastructure_recovery_retains_prior_attempt_time(tmp_path):
    class RepairableRuntime(_FakeRuntime):
        broken = True

        def run_episode(self, *args, **kwargs):
            if self.broken:
                self.episode_calls.append(args[:4])
                return {"failure": "infrastructure", "correct": False,
                        "autonomous": False, "seconds": 2}
            return super().run_episode(*args, **kwargs)

    models = {name: {"alias": name, "path": f"models/{name}.gguf", "sha256": name,
                     "revision": "fixture"} for name in ("a", "b")}
    runtime = RepairableRuntime()
    kwargs = dict(models=models, tasks_module=_fake_tasks(), runtime=runtime, lab=tmp_path / "lab")
    assert campaign.run_campaign(tmp_path, **kwargs)["status"] == "blocked"
    runtime.broken = False
    assert campaign.run_campaign(tmp_path, **kwargs)["status"] == "blocked"
    assert len(runtime.episode_calls) == 2
    assert campaign.run_campaign(tmp_path, **kwargs, retry_blocked=True)["status"] == "complete"
    recovered = next(row for row in campaign.load_records(tmp_path) if row["attempt_count"] == 3)
    assert recovered["seconds"] == 14
    assert len(recovered["attempt_results"]) == 3



def test_summary_separates_functional_result_authored_tests_and_expected_errors(tmp_path):
    rows = [{"model": "m", "stage": "repair", "profile": "baseline", "task": "B2",
             "repetition": 1, "status": "complete", "correct": True, "autonomous": False,
             "functional_correct": True, "authored_tests_passed": False, "agent_finished": True,
             "tool_errors": 3, "expected_tool_errors": 2, "avoidable_tool_errors": 1,
             "seconds": 12}]
    campaign._write_summaries(tmp_path, rows, _fake_tasks())
    summary = campaign._summary_rows(rows, _fake_tasks())[0]
    assert summary["functional_correct"] == 1
    assert summary["authored_tests_passed"] == 0
    assert summary["agent_finished"] == 1
    assert summary["correct_autonomous"] == 0
    assert summary["expected_tool_errors"] == 2
    assert summary["avoidable_tool_errors"] == 1
    assert "functional_correct" in (tmp_path / "summary.csv").read_text()
    assert "Functional correct" in (tmp_path / "summary.md").read_text()


def test_retry_error_metrics_sum_every_attempt_and_reconcile():
    episode = {"model": "m", "profile": "baseline", "stage": "repair",
               "task": "M2", "repetition": 1}
    first = campaign._attempt_summary({"tool_errors": 3, "expected_tool_errors": 2,
                                      "avoidable_tool_errors": 1}, 1)
    second = campaign._attempt_summary({"tool_errors": 1, "expected_tool_errors": 0,
                                       "avoidable_tool_errors": 1}, 2)
    record = campaign._combined_record(episode, [first, second], status="complete",
                                       final={"correct": True, "autonomous": True})
    assert record["tool_errors"] == 4
    assert record["expected_tool_errors"] == 2
    assert record["avoidable_tool_errors"] == 2
    assert record["tool_errors"] == record["expected_tool_errors"] + record["avoidable_tool_errors"]


# --- Task 2: eligibility gate shared by every campaign consumer ---------------------


def _rank_row(correct: bool, failure: str | None, repetition: int, task: str = "B1"):
    return {
        "protocol": campaign.PROTOCOL, "model": "m", "profile": "baseline",
        "task": task, "repetition": repetition, "status": "complete",
        "correct": correct, "autonomous": correct, "failure": failure, "seconds": 5.0,
    }


def test_infrastructure_leak_rows_never_inflate_ranking():
    rows = [
        _rank_row(True, "infrastructure", 1),  # the audited failure/flag leak
        _rank_row(True, "passed", 2),
        _rank_row(True, "passed", 3),
    ]

    ranking = campaign.rank_models(rows, ("m",), metric_tasks=("B1",), required_tasks=("B1",))

    assert ranking[0]["core_completed"] == 2
    assert ranking[0]["core_3_of_3"] == 0
    assert ranking[0]["eligible"] is True
    assert ranking[0]["coverage_complete"] is True


def test_invalid_execution_runs_count_zero_in_ranking():
    rows = [
        _rank_row(False, "invalid_execution", 1),
        _rank_row(True, "passed", 2),
        _rank_row(True, "passed", 3),
    ]

    ranking = campaign.rank_models(rows, ("m",), metric_tasks=("B1",), required_tasks=("B1",))

    assert ranking[0]["core_completed"] == 2
    assert ranking[0]["core_3_of_3"] == 0


def test_profile_completion_uses_the_same_gate():
    rows = [
        _rank_row(True, "infrastructure", 1, "D1"),
        _rank_row(True, "passed", 1, "D2"),
    ]

    compared = campaign.rank_profiles(rows, ("m",), ("baseline",),
                                      tasks=("D1", "D2"), repetitions=(1,))

    assert compared[0]["completed"] == 1


def test_summary_counts_only_recorded_functional_verdicts():
    rows = [
        {"model": "m", "stage": "repair", "profile": "baseline", "task": "B2",
         "repetition": 1, "status": "complete", "correct": True, "autonomous": True,
         "seconds": 5.0},                     # legacy record without the field
        {"model": "m", "stage": "repair", "profile": "baseline", "task": "B2",
         "repetition": 2, "status": "complete", "correct": False, "autonomous": False,
         "functional_correct": None, "failure": "invalid_execution", "seconds": 5.0},
        {"model": "m", "stage": "repair", "profile": "baseline", "task": "B2",
         "repetition": 3, "status": "complete", "correct": True, "autonomous": True,
         "functional_correct": True, "failure": "passed", "seconds": 5.0},
    ]

    summary = campaign._summary_rows(rows, _fake_tasks())[0]

    assert summary["functional_correct"] == 1
    assert summary["functional_correct_evaluated"] == 1
    assert summary["correct_autonomous"] == 1  # missing cause cannot establish success
    assert summary["basic_3_of_3"] == 0        # rep2 never qualifies as success
    assert summary["basic_completed"] == 1


def test_holdout_advice_counts_only_eligible_completions():
    rows = [
        {"model": "a", "stage": "holdout", "task": "H1", "status": "complete",
         "correct": True, "autonomous": True, "failure": "infrastructure",
         "scoring_eligible": False, "repetition": 1},
        {"model": "b", "stage": "holdout", "task": "H1", "status": "complete",
         "correct": True, "autonomous": True, "failure": "passed", "repetition": 1},
    ]

    advice = campaign._holdout_advice(rows, ("a", "b"))

    assert advice["per_task_completed"]["H1"]["a"] == 0
    assert advice["per_task_completed"]["H1"]["b"] == 1
