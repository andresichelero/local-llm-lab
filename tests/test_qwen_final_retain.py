import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import qwen_final_retain


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2), encoding="utf-8")


def _attempt(unit_id: str, artifact_id: str, status: str, number: int, stage: str):
    return {
        "unit_id": unit_id,
        "unit": {"unit_id": unit_id, "artifact_id": artifact_id, "stage": stage},
        "protocol_id": f"legacy-{stage}",
        "status": status,
        "number": number,
        "source_output": None,
        "result": {"stage": stage, "status": "historical-result"},
    }


def _fixture(tmp_path: Path):
    root = tmp_path / "results"
    origin = root / "legacy-campaign"
    unit_id = "a" * 64
    first = _attempt(unit_id, "artifact-kept", "finished", 1, "qualification")
    first["source_output"] = str(origin)
    second = _attempt(unit_id, "artifact-kept", "finished", 2, "capacity")
    second["source_output"] = str(origin)
    unfinished = _attempt("b" * 64, "artifact-kept", "retryable_infrastructure", 1, "capacity")
    unfinished["source_output"] = str(origin)
    other_artifact = _attempt("c" * 64, "artifact-other", "finished", 1, "qualification")
    other_artifact["source_output"] = str(origin)

    raw1 = origin / "units" / unit_id / "1" / "result.json"
    raw2 = origin / "units" / unit_id / "2" / "trace.bin"
    raw1.parent.mkdir(parents=True)
    raw1.write_text('{"raw":"one"}\n', encoding="utf-8")
    raw2.parent.mkdir(parents=True)
    raw2.write_bytes(b"two\x00raw")
    _write_json(origin / "manifest.json", {"protocol_id": "legacy-qualification"})

    state_path = tmp_path / "state.json"
    catalog_path = tmp_path / "catalog.json"
    _write_json(state_path, {"attempts": [first, unfinished, other_artifact, second]})
    _write_json(catalog_path, {"artifacts": [{"artifact_id": "artifact-kept"}, {"artifact_id": "artifact-other"}]})
    return root, origin, state_path, catalog_path, [first, second], [raw1, raw2]


def test_preserves_only_selected_finished_attempts_and_all_their_stages(tmp_path):
    root, _, state_path, catalog_path, expected, _ = _fixture(tmp_path)
    destination = tmp_path / "archive"

    qwen_final_retain.preserve(
        state_path,
        catalog_path,
        destination,
        artifact_ids={"artifact-kept"},
        allowed_roots=[root],
    )

    saved = json.loads((destination / "historical-reference" / "attempts.json").read_text(encoding="utf-8"))
    assert saved == expected
    assert [row["unit"]["stage"] for row in saved] == ["qualification", "capacity"]
    assert all(row["protocol_id"].startswith("legacy-") for row in saved)
    archive_manifest = json.loads((destination / "manifest.json").read_text(encoding="utf-8"))
    assert archive_manifest["purpose"] == "historical_reference_only"
    assert archive_manifest["ranking_eligible"] is False


def test_copies_raw_files_with_verified_hashes_and_origin_manifest(tmp_path):
    root, origin, state_path, catalog_path, _, raw_files = _fixture(tmp_path)
    destination = tmp_path / "archive"

    qwen_final_retain.preserve(
        state_path,
        catalog_path,
        destination,
        artifact_ids={"artifact-kept"},
        allowed_roots=[root],
    )

    inventory = json.loads((destination / "inventory.json").read_text(encoding="utf-8"))
    copied = [destination / row["destination"] for row in inventory["files"]]
    assert len(copied) == 2
    assert {path.read_bytes() for path in copied} == {path.read_bytes() for path in raw_files}
    assert {row["sha256"] for row in inventory["files"]} == {
        hashlib.sha256(path.read_bytes()).hexdigest() for path in raw_files
    }
    assert all(row["verified"] is True for row in inventory["files"])
    origins = list((destination / "origins").glob("*/manifest.json"))
    assert len(origins) == 1
    assert json.loads(origins[0].read_text(encoding="utf-8")) == {
        "protocol_id": "legacy-qualification"
    }
    assert str(origin) in json.loads((destination / "manifest.json").read_text())["origins"][0]["source_output"]


def test_records_missing_raw_evidence_without_claiming_integrity(tmp_path):
    root, origin, state_path, catalog_path, _, _ = _fixture(tmp_path)
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["attempts"] = [state["attempts"][0]]
    state["attempts"][0]["number"] = 9
    _write_json(state_path, state)
    destination = tmp_path / "archive"

    qwen_final_retain.preserve(
        state_path,
        catalog_path,
        destination,
        artifact_ids={"artifact-kept"},
        allowed_roots=[root],
    )

    inventory = json.loads((destination / "inventory.json").read_text(encoding="utf-8"))
    assert inventory["missing"] == [
        {
            "unit_id": "a" * 64,
            "number": 9,
            "source_output": str(origin),
            "reason": "raw_attempt_missing",
        }
    ]
    assert inventory["all_evidence_verified"] is False


def test_falls_back_to_legacy_source_for_attempt_without_source_output(tmp_path):
    root, origin, state_path, catalog_path, _, _ = _fixture(tmp_path)
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["attempts"] = [state["attempts"][0]]
    del state["attempts"][0]["source_output"]
    _write_json(state_path, state)
    destination = tmp_path / "archive"

    qwen_final_retain.preserve(
        state_path,
        catalog_path,
        destination,
        artifact_ids={"artifact-kept"},
        allowed_roots=[root],
        fallback_output=origin,
    )

    saved = json.loads((destination / "historical-reference" / "attempts.json").read_text())
    assert "source_output" not in saved[0]
    archive = json.loads((destination / "manifest.json").read_text())
    assert archive["origins"][0]["source_output"] == str(origin)
    assert archive["origins"][0]["source_output_from_attempt"] is False


def test_cli_usable_only_keeps_model_results_and_records_exclusions_with_real_state_hash(
    tmp_path, capsys
):
    root, origin, state_path, catalog_path, _, _ = _fixture(tmp_path)
    unit_id = "d" * 64
    complete = _attempt(unit_id, "artifact-kept", "finished", 1, "qualification")
    complete.update(source_output=str(origin), result={"status": "complete"})
    model_failure = _attempt("e" * 64, "artifact-kept", "finished", 1, "capacity")
    model_failure.update(source_output=str(origin), result={"status": "model_failure"})
    restart_block = _attempt("f" * 64, "artifact-kept", "finished", 1, "capacity")
    restart_block.update(
        source_output=str(origin),
        result={"status": "blocked", "failure": "infrastructure_restart_limit"},
    )
    dns_block = _attempt("1" * 64, "artifact-kept", "finished", 1, "capacity")
    dns_block.update(
        source_output=str(origin),
        result={"status": "blocked", "failure": "unattributed_review"},
    )
    _write_json(origin / "units" / unit_id / "1" / "result.json", {"result": "complete"})
    _write_json(origin / "units" / ("e" * 64) / "1" / "result.json", {"result": "model_failure"})
    state = {"attempts": [complete, model_failure, restart_block, dns_block]}
    _write_json(state_path, state)
    original_state_bytes = state_path.read_bytes()
    destination = tmp_path / "usable-archive"

    result = qwen_final_retain.main(
        [
            "--state",
            str(state_path),
            "--catalog",
            str(catalog_path),
            "--destination",
            str(destination),
            "--artifact-id",
            "artifact-kept",
            "--allowed-root",
            str(root),
            "--fallback-output",
            str(root / "unused-fallback"),
            "--usable-only",
        ]
    )

    assert result == 0
    assert "missing raw attempts: 0" in capsys.readouterr().out
    saved = json.loads((destination / "historical-reference" / "attempts.json").read_text())
    assert [row["result"]["status"] for row in saved] == ["complete", "model_failure"]
    archive = json.loads((destination / "manifest.json").read_text())
    assert archive["state_sha256"] == hashlib.sha256(original_state_bytes).hexdigest()
    assert archive["usable_only"] is True
    assert archive["exclusions"] == [
        {
            "unit_id": "f" * 64,
            "number": 1,
            "artifact_id": "artifact-kept",
            "protocol_id": "legacy-capacity",
            "status": "finished",
            "result_status": "blocked",
            "failure": "infrastructure_restart_limit",
            "source_output": str(origin),
            "reason": "result_status_not_reusable",
        },
        {
            "unit_id": "1" * 64,
            "number": 1,
            "artifact_id": "artifact-kept",
            "protocol_id": "legacy-capacity",
            "status": "finished",
            "result_status": "blocked",
            "failure": "unattributed_review",
            "source_output": str(origin),
            "reason": "result_status_not_reusable",
        },
    ]


@pytest.mark.parametrize(
    "unit_id,number",
    [("../outside", 1), ("a" * 64, 0), ("a" * 64, -1), ("a" * 63 + "g", 1)],
)
def test_rejects_invalid_unit_identity_or_attempt_number(tmp_path, unit_id, number):
    root, _, state_path, catalog_path, _, _ = _fixture(tmp_path)
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["attempts"] = [_attempt(unit_id, "artifact-kept", "finished", number, "capacity")]
    state["attempts"][0]["source_output"] = str(root / "legacy-campaign")
    _write_json(state_path, state)

    with pytest.raises(ValueError):
        qwen_final_retain.preserve(
            state_path,
            catalog_path,
            tmp_path / "archive",
            artifact_ids={"artifact-kept"},
            allowed_roots=[root],
        )


def test_rejects_source_output_outside_allowed_root_and_existing_destination(tmp_path):
    _, _, state_path, catalog_path, _, _ = _fixture(tmp_path)
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["attempts"] = [_attempt("a" * 64, "artifact-kept", "finished", 1, "capacity")]
    state["attempts"][0]["source_output"] = str(tmp_path / "outside")
    _write_json(state_path, state)

    with pytest.raises(ValueError, match="outside allowed roots"):
        qwen_final_retain.preserve(
            state_path,
            catalog_path,
            tmp_path / "archive",
            artifact_ids={"artifact-kept"},
            allowed_roots=[tmp_path / "results"],
        )

    destination = tmp_path / "already-there"
    destination.mkdir()
    with pytest.raises(FileExistsError):
        qwen_final_retain.preserve(
            state_path,
            catalog_path,
            destination,
            artifact_ids={"artifact-kept"},
            allowed_roots=[tmp_path],
        )


def test_rejects_symlink_in_source_evidence(tmp_path):
    root, origin, state_path, catalog_path, _, _ = _fixture(tmp_path)
    link = origin / "units" / ("a" * 64) / "1" / "linked.bin"
    try:
        link.symlink_to(origin / "manifest.json")
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are unavailable in this environment")
    destination = tmp_path / "archive"

    with pytest.raises(ValueError, match="symlink"):
        qwen_final_retain.preserve(
            state_path,
            catalog_path,
            destination,
            artifact_ids={"artifact-kept"},
            allowed_roots=[root],
        )
