import json

import pytest

from benchmark.qwen_optimization import (
    Campaign,
    choose_finalists,
    fingerprint,
    make_units,
    seed_recovery_state,
    write_json,
)


def artifact(name="a", model="4B"):
    return {"artifact_id": name, "model_id": model, "engine": "llama.cpp"}


def test_recovery_preserves_finished_failure_and_retries_interrupted(tmp_path):
    queue = Campaign(tmp_path, {"protocol_id": "test-v1"})
    queue.add(make_units([artifact("a"), artifact("b")], "qualification"))
    first = queue.pending()[0]
    queue.begin(first)
    queue.finish(first, {"status": "model_failure", "passed": 4})
    second = queue.pending()[0]
    queue.begin(second)
    recovered = Campaign(tmp_path, {"protocol_id": "test-v1"})
    assert [u["artifact_id"] for u in recovered.pending()] == ["b"]
    assert recovered.records()[0]["result"]["status"] == "model_failure"
    assert recovered.state["attempts"][1]["status"] == "interrupted"


def test_changed_inputs_refuse_resume(tmp_path):
    Campaign(tmp_path, {"protocol_id": "one", "max_calls": 120})
    with pytest.raises(ValueError, match="immutable"):
        Campaign(tmp_path, {"protocol_id": "one", "max_calls": 121})


def test_individual_block_does_not_block_other_artifacts(tmp_path):
    queue = Campaign(tmp_path, {"protocol_id": "test-v1"})
    queue.add(make_units([artifact("a"), artifact("b")], "qualification"))
    first = queue.pending()[0]
    queue.begin(first)
    queue.finish(first, {"status": "blocked", "failure": "engine_unavailable"})
    assert queue.pending()[0]["artifact_id"] == "b"


def test_finalists_are_distinct_and_require_actual_quality():
    rows = [
        dict(
            artifact(x),
            qualification_passed=12,
            development_complete=n,
            median_seconds=t,
            max_context=c,
            peak_vram_mib=v,
            protocol_valid=True,
            development_total=6,
            context_verified=True,
        )
        for x, n, t, c, v in [
            ("a", 6, 10, 32768, 4000),
            ("b", 5, 9, 65536, 3900),
            ("c", 4, 3, 131072, 2000),
        ]
    ]
    result = choose_finalists(rows)
    assert result["4B"]["efficiency"]["artifact_id"] == "a"
    assert result["4B"]["context"]["artifact_id"] == "b"
    assert result["9B"]["status"] == "insufficient_evidence"


def test_no_false_finalist_from_missing_measurements():
    assert (
        choose_finalists([dict(artifact(), qualification_passed=12)])["4B"]["status"]
        == "insufficient_evidence"
    )


def test_corrupt_manifest_digest_refuses_resume(tmp_path):
    import json

    Campaign(tmp_path, {"protocol_id": "test-v1"})
    path = tmp_path / "manifest.json"
    value = json.loads(path.read_text())
    value["input_digest"] = "corrupt"
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="digest"):
        Campaign(tmp_path, {"protocol_id": "test-v1"})


def test_persistent_schedule_is_idempotent(tmp_path):
    queue = Campaign(tmp_path, {"protocol_id": "test-v1"})
    units = make_units([artifact()], "capacity", contexts=[16384, 32768])
    queue.add(units)
    queue.add(units)
    assert len(queue.pending()) == 2


def test_output_token_profile_is_part_of_each_measurement_unit():
    unit = make_units(
        [artifact()], "qualification", output_tokens=8192
    )[0]
    assert unit["output_tokens"] == 8192


def test_only_two_infrastructure_restarts_allowed(tmp_path):
    queue = Campaign(tmp_path, {"protocol_id": "test-v1"})
    queue.add(make_units([artifact()], "qualification"))
    for _ in range(3):
        unit = queue.pending()[0]
        queue.begin(unit)
        queue.defer(unit, {"status": "blocked", "failure": "transient_transport"})
    assert not queue.pending()
    assert queue.records()[-1]["result"]["failure"] == "infrastructure_restart_limit"


def test_zero_development_success_cannot_be_a_finalist():
    row = dict(
        artifact(),
        qualification_passed=12,
        development_complete=0,
        development_total=6,
        median_seconds=1,
        max_context=32768,
        peak_vram_mib=3000,
        protocol_valid=True,
        context_verified=True,
    )
    assert choose_finalists([row])["4B"]["status"] == "insufficient_evidence"


def test_resource_block_preserves_pending_unit_and_keeps_queue_alive(tmp_path):
    queue = Campaign(tmp_path, {"protocol_id": "test-v1"})
    queue.add(make_units([artifact("a"), artifact("b")], "qualification"))
    first, second = queue.pending()
    queue.begin(first)
    queue.wait_resources(
        first,
        {"status": "blocked", "failure": "gpu_reserve"},
        {"gpu": 7100, "ram": 3000, "disk": 20 * 1024**3},
    )
    assert [u["artifact_id"] for u in queue.pending()] == ["a", "b"]


def test_seed_recovery_copies_stopped_history_with_protocol_provenance(tmp_path):
    source = tmp_path / "v4"
    output = tmp_path / "v4-recovery-r1"
    source.mkdir()
    immutable = {"protocol_id": "qwen-quant-harness-optimization-v4", "config": {"floor": 10}}
    write_json(
        source / "manifest.json",
        {"immutable": immutable, "input_digest": fingerprint(immutable)},
    )
    unit_a, unit_b = make_units([artifact("a"), artifact("b")], "qualification")
    original_state = {
        "units": [unit_a, unit_b],
        "attempts": [
            {
                "unit_id": unit_a["unit_id"],
                "unit": unit_a,
                "status": "finished",
                "number": 1,
                "result": {"status": "complete", "passed": 12, "total": 12},
            },
            {
                "unit_id": unit_b["unit_id"],
                "unit": unit_b,
                "status": "resource_waiting",
                "number": 1,
                "result": {"status": "resource_blocked", "failure": "infrastructure"},
            },
        ],
        "resource_wait": {unit_b["unit_id"]: {"gpu": 1000, "ram": 2000, "disk": 3000}},
        "status": "running",
        "updated_at": "2026-10-26T00:00:00+00:00",
    }
    write_json(source / "state.json", original_state)
    source_state_bytes = (source / "state.json").read_bytes()

    origin = seed_recovery_state(
        source,
        output,
        recovery_protocol_id="qwen-quant-harness-optimization-v4-recovery-r1",
    )

    recovered = json.loads((output / "state.json").read_text())
    assert recovered["status"] == "recovery_prepared"
    assert recovered["units"] == original_state["units"]
    assert [a["status"] for a in recovered["attempts"]] == ["finished", "resource_waiting"]
    assert all(a["protocol_id"] == immutable["protocol_id"] for a in recovered["attempts"])
    assert recovered["resource_wait"] == original_state["resource_wait"]
    assert origin["source_protocol_id"] == immutable["protocol_id"]
    assert origin["recovery_protocol_id"] == "qwen-quant-harness-optimization-v4-recovery-r1"
    assert origin["imported_finished_attempts"] == 1
    assert (source / "state.json").read_bytes() == source_state_bytes
    recovery_protocol = "qwen-quant-harness-optimization-v4-recovery-r1"
    resumed = Campaign(output, {"protocol_id": recovery_protocol})
    assert [unit["unit_id"] for unit in resumed.pending()] == [unit_b["unit_id"]]
    resumed.begin(resumed.pending()[0])
    assert resumed.state["attempts"][-1]["protocol_id"] == recovery_protocol


def test_seed_recovery_requeues_only_dns_blocked_units_in_new_output(tmp_path):
    source = tmp_path / "r2"
    output = tmp_path / "r3"
    source.mkdir()
    immutable = {"protocol_id": "qwen-recovery-r2", "config": {"floor": 10}}
    write_json(
        source / "manifest.json",
        {"immutable": immutable, "input_digest": fingerprint(immutable)},
    )
    complete, dns_only, model_failure, mixed = make_units(
        [artifact("complete"), artifact("dns"), artifact("model"), artifact("mixed")],
        "development",
    )
    dns_result = {
        "status": "blocked",
        "failure": "unattributed_review",
        "error": "URLError: <urlopen error [Errno -3] Temporary failure in name resolution>",
        "model_failure": False,
    }
    attempts = [
        {"unit_id": complete["unit_id"], "unit": complete, "status": "finished", "number": 1,
         "result": {"status": "complete", "passed": 6}},
        {"unit_id": dns_only["unit_id"], "unit": dns_only, "status": "finished", "number": 1,
         "result": dns_result},
        {"unit_id": model_failure["unit_id"], "unit": model_failure, "status": "finished", "number": 1,
         "result": {"status": "model_failure", "failure": "budget_exhausted", "model_failure": True}},
        {"unit_id": mixed["unit_id"], "unit": mixed, "status": "finished", "number": 1,
         "result": {"status": "model_failure", "failure": "model_no_progress", "model_failure": True}},
        {"unit_id": mixed["unit_id"], "unit": mixed, "status": "finished", "number": 2,
         "result": dns_result},
    ]
    original_state = {"units": [complete, dns_only, model_failure, mixed], "attempts": attempts,
                      "resource_wait": {}, "status": "paused", "updated_at": "2026-10-26T00:00:00Z"}
    write_json(source / "state.json", original_state)
    original_state_bytes = (source / "state.json").read_bytes()

    origin = seed_recovery_state(
        source,
        output,
        recovery_protocol_id="qwen-recovery-r3",
        requeue_dns_failures=True,
    )

    recovered = json.loads((output / "state.json").read_text())
    assert recovered["attempts"][0]["status"] == "finished"
    assert recovered["attempts"][1]["status"] == "retryable_infrastructure"
    assert recovered["attempts"][1]["result"] == dns_result
    assert recovered["attempts"][1]["source_status"] == "finished"
    assert recovered["attempts"][2]["status"] == "finished"
    assert recovered["attempts"][3]["status"] == "finished"
    assert recovered["attempts"][4]["status"] == "finished"
    assert origin["requeued_dns_attempts"] == 1
    assert origin["requeued_dns_unit_ids"] == [dns_only["unit_id"]]
    assert (source / "state.json").read_bytes() == original_state_bytes

    resumed = Campaign(output, {"protocol_id": "qwen-recovery-r3"})
    assert [unit["unit_id"] for unit in resumed.pending()] == [dns_only["unit_id"]]
