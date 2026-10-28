"""Copy selected finished Qwen attempts into a historical reference archive.

The archive is deliberately separate from the final campaign ranking. This
module performs file copying only; it never runs inference or edits a source.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
from pathlib import Path
from typing import Any


DEFAULT_RESULTS_ROOT = Path("/home/foxtrot/local-llm-benchmark/results")
DEFAULT_FALLBACK_OUTPUT = DEFAULT_RESULTS_ROOT / "qwen-quant-harness-optimization-v4-recovery-r3-dns"
UNIT_ID_RE = re.compile(r"^[0-9a-fA-F]{64}$")


def _absolute(path: Path | str) -> Path:
    return Path(os.path.abspath(os.fspath(path)))


def _reject_symlink_components(path: Path | str) -> Path:
    """Reject any existing symlink in the path, including parent components."""
    absolute = _absolute(path)
    current = Path(absolute.anchor)
    for component in absolute.parts[1:]:
        current = current / component
        try:
            current.lstat()
        except FileNotFoundError:
            continue
        if current.is_symlink():
            raise ValueError(f"symlink is not allowed: {current}")
        if current != absolute and not current.is_dir():
            raise ValueError(f"path parent is not a directory: {current}")
    return absolute


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _load_json(path: Path) -> tuple[Any, bytes]:
    path = _reject_symlink_components(path)
    if not path.is_file():
        raise FileNotFoundError(f"JSON input is not a file: {path}")
    raw = path.read_bytes()
    try:
        return json.loads(raw), raw
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON in {path}: {exc}") from exc


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _catalog_ids(catalog: Any) -> set[str]:
    if not isinstance(catalog, dict) or not isinstance(catalog.get("artifacts"), list):
        raise ValueError("catalog must contain an artifacts list")
    ids = set()
    for artifact in catalog["artifacts"]:
        if not isinstance(artifact, dict) or not isinstance(artifact.get("artifact_id"), str):
            raise ValueError("every catalog artifact must have a string artifact_id")
        ids.add(artifact["artifact_id"])
    return ids


def _attempt_artifact_id(attempt: dict[str, Any]) -> str | None:
    unit = attempt.get("unit")
    return unit.get("artifact_id") if isinstance(unit, dict) else None


def _validated_roots(allowed_roots: list[Path | str]) -> list[Path]:
    roots = []
    for value in allowed_roots:
        root = _reject_symlink_components(value)
        roots.append(root.resolve(strict=False))
    if not roots:
        raise ValueError("at least one allowed source root is required")
    return roots


def _resolve_attempt_source(
    attempt: dict[str, Any],
    *,
    fallback_output: Path | str | None,
    allowed_roots: list[Path],
) -> tuple[Path, str | None, bool]:
    supplied = attempt.get("source_output")
    from_attempt = isinstance(supplied, str) and bool(supplied)
    source_text = supplied if from_attempt else fallback_output
    if not isinstance(source_text, (str, Path)) or not str(source_text):
        raise ValueError("attempt has no source_output and no fallback output was supplied")
    source = _reject_symlink_components(source_text).resolve(strict=False)
    if not any(_is_within(source, root) for root in allowed_roots):
        raise ValueError(f"source_output outside allowed roots: {source}")
    return source, supplied if from_attempt else None, from_attempt


def _raw_files(raw_attempt: Path) -> list[Path]:
    """Return regular files under a raw attempt, rejecting links and special files."""
    _reject_symlink_components(raw_attempt)
    if not raw_attempt.exists():
        return []
    if raw_attempt.is_file():
        return [raw_attempt]
    if not raw_attempt.is_dir():
        raise ValueError(f"raw attempt is not a regular file or directory: {raw_attempt}")

    files = []
    for entry in sorted(raw_attempt.rglob("*")):
        _reject_symlink_components(entry)
        if entry.is_dir():
            continue
        if not entry.is_file():
            raise ValueError(f"special file is not allowed in raw evidence: {entry}")
        files.append(entry)
    return files


def _copy_verified(source: Path, destination: Path) -> dict[str, Any]:
    _reject_symlink_components(source)
    if not source.is_file():
        raise ValueError(f"raw evidence changed or is not a file: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    size = 0
    with source.open("rb") as input_stream, destination.open("xb") as output_stream:
        for block in iter(lambda: input_stream.read(1024 * 1024), b""):
            digest.update(block)
            size += len(block)
            output_stream.write(block)
    expected = digest.hexdigest()
    actual = _sha256(destination)
    return {
        "source": str(source),
        "destination": str(destination),
        "size_bytes": size,
        "sha256": expected,
        "verified": actual == expected,
    }


def preserve(
    state_path: Path | str,
    catalog_path: Path | str,
    destination: Path | str,
    *,
    artifact_ids: set[str] | None = None,
    allowed_roots: list[Path | str] | None = None,
    fallback_output: Path | str | None = DEFAULT_FALLBACK_OUTPUT,
    usable_only: bool = False,
) -> dict[str, Any]:
    """Create a new, standalone archive of selected finished historical attempts."""
    state_path = _reject_symlink_components(state_path)
    catalog_path = _reject_symlink_components(catalog_path)
    state, state_bytes = _load_json(state_path)
    catalog, catalog_bytes = _load_json(catalog_path)
    if not isinstance(state, dict) or not isinstance(state.get("attempts"), list):
        raise ValueError("state must contain an attempts list")
    all_ids = _catalog_ids(catalog)
    selected_ids = all_ids if artifact_ids is None else set(artifact_ids)
    if not selected_ids:
        raise ValueError("at least one artifact ID must be selected")
    unknown = selected_ids - all_ids
    if unknown:
        raise ValueError(f"selected artifact IDs are absent from catalog: {sorted(unknown)}")
    roots = _validated_roots(allowed_roots or [DEFAULT_RESULTS_ROOT])
    fallback_path = fallback_output

    target = _reject_symlink_components(destination)
    if target.exists():
        raise FileExistsError(f"destination already exists: {target}")

    selected_attempts = []
    resolved_attempt_sources = []
    exclusions = []
    for attempt in state["attempts"]:
        if not isinstance(attempt, dict):
            raise ValueError("every state attempt must be an object")
        artifact_id = _attempt_artifact_id(attempt)
        if attempt.get("status") != "finished" or artifact_id not in selected_ids:
            continue
        result = attempt.get("result")
        result_status = result.get("status") if isinstance(result, dict) else None
        if usable_only and result_status not in {"complete", "model_failure"}:
            exclusions.append(
                {
                    "unit_id": attempt.get("unit_id"),
                    "number": attempt.get("number"),
                    "artifact_id": artifact_id,
                    "protocol_id": attempt.get("protocol_id"),
                    "status": attempt.get("status"),
                    "result_status": result_status,
                    "failure": result.get("failure") if isinstance(result, dict) else None,
                    "source_output": attempt.get("source_output"),
                    "reason": "result_status_not_reusable",
                }
            )
            continue
        unit_id = attempt.get("unit_id")
        number = attempt.get("number")
        if not isinstance(unit_id, str) or UNIT_ID_RE.fullmatch(unit_id) is None:
            raise ValueError(f"invalid unit_id in selected finished attempt: {unit_id!r}")
        if type(number) is not int or number <= 0:
            raise ValueError(f"attempt number must be a positive integer: {number!r}")
        source, original_source, source_from_attempt = _resolve_attempt_source(
            attempt, fallback_output=fallback_path, allowed_roots=roots
        )
        selected_attempts.append(attempt)
        resolved_attempt_sources.append(
            (attempt, source, original_source, source_from_attempt)
        )

    target.mkdir(parents=True, exist_ok=False)
    origins_by_path: dict[str, dict[str, Any]] = {}
    files_inventory: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []

    for attempt, source, original_source, source_from_attempt in resolved_attempt_sources:
        source_key = str(source)
        origin_key = hashlib.sha256(source_key.encode("utf-8")).hexdigest()[:16]
        if source_key not in origins_by_path:
            origin_info: dict[str, Any] = {
                "origin_id": origin_key,
                "source_output": source_key,
                "source_output_from_attempt": source_from_attempt,
                "source_output_value": original_source,
                "manifest_available": False,
            }
            source_manifest = source / "manifest.json"
            _reject_symlink_components(source_manifest)
            if source_manifest.is_file():
                manifest_destination = target / "origins" / origin_key / "manifest.json"
                manifest_destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source_manifest, manifest_destination)
                origin_info["manifest_available"] = True
                origin_info["manifest_destination"] = str(
                    manifest_destination.relative_to(target)
                )
                origin_info["manifest_sha256"] = _sha256(manifest_destination)
            origins_by_path[source_key] = origin_info

        unit_id = attempt["unit_id"]
        number = attempt["number"]
        raw_attempt = source / "units" / unit_id / str(number)
        raw_files = _raw_files(raw_attempt)
        if not raw_files:
            missing.append(
                {
                    "unit_id": unit_id,
                    "number": number,
                    "source_output": source_key,
                    "reason": "raw_attempt_missing",
                }
            )
            continue

        for raw_file in raw_files:
            relative_raw = raw_file.relative_to(raw_attempt) if raw_attempt.is_dir() else Path(raw_file.name)
            copied_to = (
                target / "raw" / origin_key / "units" / unit_id / str(number) / relative_raw
            )
            row = _copy_verified(raw_file, copied_to)
            row.update(
                {
                    "origin_id": origin_key,
                    "unit_id": unit_id,
                    "number": number,
                }
            )
            row["destination"] = str(Path(row["destination"]).relative_to(target))
            files_inventory.append(row)

    _write_json(target / "historical-reference" / "attempts.json", selected_attempts)
    archive_manifest = {
        "schema_version": 1,
        "purpose": "historical_reference_only",
        "ranking_eligible": False,
        "ranking_note": "Historical records are not imported into the final ranking; compatibility with final protocols is not established.",
        "selected_artifact_ids": sorted(selected_ids),
        "attempt_count": len(selected_attempts),
        "usable_only": usable_only,
        "exclusions": exclusions,
        "state_path": str(state_path),
        "state_sha256": hashlib.sha256(state_bytes).hexdigest(),
        "catalog_path": str(catalog_path),
        "catalog_sha256": hashlib.sha256(catalog_bytes).hexdigest(),
        "origins": list(origins_by_path.values()),
    }
    _write_json(target / "manifest.json", archive_manifest)
    inventory = {
        "schema_version": 1,
        "files": files_inventory,
        "missing": missing,
        "all_evidence_verified": not missing and all(
            row["verified"] for row in files_inventory
        ),
    }
    _write_json(target / "inventory.json", inventory)
    return {"manifest": archive_manifest, "inventory": inventory}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Copy selected finished Qwen attempts into a historical reference archive."
    )
    parser.add_argument("--state", required=True, type=Path)
    parser.add_argument("--catalog", required=True, type=Path)
    parser.add_argument("--destination", required=True, type=Path)
    parser.add_argument("--artifact-id", action="append", dest="artifact_ids")
    parser.add_argument("--allowed-root", action="append", type=Path, dest="allowed_roots")
    parser.add_argument("--fallback-output", type=Path, default=DEFAULT_FALLBACK_OUTPUT)
    parser.add_argument(
        "--usable-only",
        action="store_true",
        help="retain only finished attempts with result.status complete or model_failure",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = preserve(
            args.state,
            args.catalog,
            args.destination,
            artifact_ids=set(args.artifact_ids) if args.artifact_ids else None,
            allowed_roots=args.allowed_roots or [DEFAULT_RESULTS_ROOT],
            fallback_output=args.fallback_output,
            usable_only=args.usable_only,
        )
    except (OSError, ValueError) as exc:
        print(f"qwen-final-retain: {exc}", file=sys.stderr)
        return 2
    inventory = result["inventory"]
    print(
        f"Saved {result['manifest']['attempt_count']} historical attempts; "
        f"copied {len(inventory['files'])} files; missing raw attempts: {len(inventory['missing'])}; "
        f"all evidence verified: {inventory['all_evidence_verified']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
