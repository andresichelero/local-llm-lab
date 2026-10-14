"""Small passive lifecycle and workspace-metadata recorder for cascade runs."""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path, PureWindowsPath
from typing import Any

_PHASES = {
    "setup", "initial_agent", "visible_feedback", "model_transition",
    "repair_agent", "grading", "finalization",
}
_EVENTS = {
    "run_start", "phase_start", "phase_end", "snapshot_start", "snapshot_end",
    "evidence_error", "agent_spawn", "agent_exit", "sampler_start", "sampler_end",
    "model_transition", "visible_feedback", "grader_result", "run_end",
}
_SOURCES = {"cascade", "observer", "agent_process", "sampler", "final_grader"}
_DETAIL_KEYS = {
    "status", "duration_ns", "exit_code", "timed_out", "passed", "sample_count",
    "component", "error_type", "escalated", "result", "reason", "snapshot_id",
    "evidence_status",
}
_SECRET_PARTS = ("secret", "token", "credential", "password", "private_key")
_SECRET_SUFFIXES = {".pem", ".key", ".p12", ".pfx", ".crt", ".cer"}
_SECRET_NAMES = {".env", ".env.local", ".env.production", "id_rsa", "id_ed25519"}
_SKIP_DIRS = {".git", ".hg", ".svn", "node_modules", "__pycache__"}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _is_secret(name: str) -> bool:
    lowered = name.lower()
    return (
        lowered in _SECRET_NAMES
        or lowered.startswith(".env")
        or lowered.endswith(tuple(_SECRET_SUFFIXES))
        or any(part in lowered for part in _SECRET_PARTS)
    )


def _hash_file(path: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    with os.fdopen(descriptor, "rb") as source:
        if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
            raise OSError("not a regular file")
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
    return size, digest.hexdigest()


def _safe_hash_records(allowlist: object) -> list[dict[str, Any]]:
    if not isinstance(allowlist, list):
        raise ValueError("hash allowlist must be a list")
    records: list[dict[str, Any]] = []
    normalized: list[tuple[str, str, Path]] = []
    for item in allowlist:
        if not isinstance(item, dict):
            raise ValueError("invalid hash allowlist entry")
        category, relative, raw_file = item.get("category"), item.get("path"), item.get("file")
        file_path = Path(raw_file) if isinstance(raw_file, (str, os.PathLike)) else None
        if not isinstance(category, str) or not re.fullmatch(r"[a-z][a-z0-9_-]{0,40}", category):
            raise ValueError("invalid hash category")
        if (
            not isinstance(relative, str)
            or Path(relative).is_absolute()
            or PureWindowsPath(relative).is_absolute()
            or ".." in Path(relative).parts
        ):
            raise ValueError("invalid relative hash path")
        if file_path is None:
            raise ValueError("invalid hash file")
        normalized.append((category, Path(relative).as_posix(), file_path))

    for category, relative, file_path in sorted(normalized, key=lambda value: (value[0], value[1])):
        try:
            metadata = file_path.lstat()
            if not stat.S_ISREG(metadata.st_mode):
                raise OSError("not a regular file")
            size, digest = _hash_file(file_path)
            records.append({
                "category": category,
                "path": relative,
                "size_bytes": size,
                "sha256": digest,
                "status": "measured",
                "reason": None,
            })
        except OSError:
            records.append({
                "category": category,
                "path": relative,
                "size_bytes": None,
                "sha256": None,
                "status": "unavailable",
                "reason": "file_unavailable_or_not_regular",
            })
    return records


class RunObserver:
    """Own exactly three observer files, with exclusive creation and flushes."""

    def __init__(self, run_dir: Path, manifest: dict[str, Any]) -> None:
        self.run_dir = Path(run_dir)
        self.run_id = str(uuid.uuid4())
        self._seq = 0
        self._finalized = False
        self._incomplete = False
        self._active_phases: set[str] = set()
        self._event_file = None
        self._snapshot_file = None
        self._manifest_path = self.run_dir / "observer-manifest.json"
        self._events_path = self.run_dir / "observer-events.jsonl"
        self._snapshots_path = self.run_dir / "workspace-snapshots.jsonl"
        owned = (self._manifest_path, self._events_path, self._snapshots_path)
        if any(path.exists() for path in owned):
            raise FileExistsError("observer artifacts already exist")

        safe_manifest = {key: value for key, value in manifest.items() if key not in {
            "hash_allowlist", "snapshot_hash_allowlist",
        }}
        safe_manifest.update({
            "run_id": self.run_id,
            "hashes": _safe_hash_records(manifest.get("hash_allowlist", [])),
            "workspace_hash_allowlist": self._validate_snapshot_allowlist(
                manifest.get("snapshot_hash_allowlist", [])
            ),
        })
        self._event_file = self._events_path.open("x", encoding="utf-8")
        try:
            self._snapshot_file = self._snapshots_path.open("x", encoding="utf-8")
            with self._manifest_path.open("x", encoding="utf-8") as output:
                output.write(json.dumps(safe_manifest, sort_keys=True) + "\n")
                output.flush()
                os.fsync(output.fileno())
        except BaseException:
            self._event_file.close()
            self._events_path.unlink(missing_ok=True)
            if self._snapshot_file is not None:
                self._snapshot_file.close()
            self._snapshots_path.unlink(missing_ok=True)
            raise
        self._snapshot_allowlist = set(safe_manifest["workspace_hash_allowlist"])
        self.record("run_start", source="observer", details={"status": "started"})

    @staticmethod
    def _validate_snapshot_allowlist(value: object) -> list[str]:
        if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
            raise ValueError("snapshot hash allowlist must be a list of relative paths")
        paths = []
        for item in value:
            path = Path(item)
            if path.is_absolute() or PureWindowsPath(item).is_absolute() or ".." in path.parts or not item:
                raise ValueError("invalid snapshot hash path")
            paths.append(path.as_posix())
        return sorted(set(paths))

    @staticmethod
    def _details(details: dict[str, Any] | None) -> dict[str, Any]:
        if details is None:
            return {}
        if not isinstance(details, dict) or not set(details).issubset(_DETAIL_KEYS):
            raise ValueError("event details contain an unsupported key")
        bounded: dict[str, Any] = {}
        for key, value in details.items():
            if isinstance(value, str):
                if len(value) > 80:
                    raise ValueError("event detail is too long")
                bounded[key] = value
            elif value is None or type(value) in (bool, int, float):
                bounded[key] = value
            else:
                raise ValueError("event details must be scalar metadata")
        return bounded

    def record(
        self,
        event_type: str,
        phase_id: str | None = None,
        *,
        agent_id: str | None = None,
        parent_agent_id: str | None = None,
        turn_id: str | None = None,
        source: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        if self._finalized:
            raise RuntimeError("observer is finalized")
        if event_type not in _EVENTS or (phase_id is not None and phase_id not in _PHASES):
            raise ValueError("unsupported event or phase")
        if source is not None and source not in _SOURCES:
            raise ValueError("unsupported event source")
        self._seq += 1
        event = {
            "event_id": f"{self.run_id}:{self._seq}",
            "run_id": self.run_id,
            "event_seq": self._seq,
            "event_type": event_type,
            "phase_id": phase_id,
            "agent_id": agent_id,
            "parent_agent_id": parent_agent_id,
            "turn_id": turn_id,
            "source": source,
            "timestamp_utc": _utc_now(),
            "monotonic_ns": time.monotonic_ns(),
            "details": self._details(details),
        }
        self._event_file.write(json.dumps(event, sort_keys=True) + "\n")
        self._event_file.flush()

    def start_phase(
        self,
        name: str,
        *,
        agent_id: str | None = None,
        parent_agent_id: str | None = None,
        turn_id: str | None = None,
        source: str | None = None,
    ) -> str:
        if name not in _PHASES:
            raise ValueError("unsupported phase")
        phase_id = name
        if phase_id in self._active_phases:
            raise RuntimeError("phase is already active")
        self._active_phases.add(phase_id)
        self.record("phase_start", phase_id, agent_id=agent_id, parent_agent_id=parent_agent_id,
                    turn_id=turn_id, source=source, details={"status": "started"})
        return phase_id

    def end_phase(
        self,
        phase_id: str,
        status: str,
        *,
        agent_id: str | None = None,
        parent_agent_id: str | None = None,
        turn_id: str | None = None,
        source: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        if phase_id not in self._active_phases:
            raise RuntimeError("phase is not active")
        bounded = dict(details or {})
        bounded["status"] = status
        self.record("phase_end", phase_id, agent_id=agent_id, parent_agent_id=parent_agent_id,
                    turn_id=turn_id, source=source, details=bounded)
        self._active_phases.remove(phase_id)

    def snapshot(
        self,
        label: str,
        workspace_root: Path,
        *,
        agent_id: str | None = None,
        parent_agent_id: str | None = None,
        turn_id: str | None = None,
        source: str | None = None,
    ) -> dict[str, Any]:
        if not re.fullmatch(r"(before|after)_(initial_agent|repair_agent)", label):
            raise ValueError("unsupported snapshot label")
        phase_id = "initial_agent" if "initial_agent" in label else "repair_agent"
        event_seq = self._seq + 1
        event_id = f"{self.run_id}:{event_seq}"
        snapshot_id = f"{label}:{event_seq}"
        self.record("snapshot_start", phase_id, agent_id=agent_id, parent_agent_id=parent_agent_id,
                    turn_id=turn_id, source=source, details={"snapshot_id": snapshot_id})
        root = Path(workspace_root)
        entries: list[dict[str, Any]] = []
        counts = {"secret_excluded": 0, "metadata_excluded": 0}
        errors = 0
        allowed_hashes = self._snapshot_allowlist
        root_stat = root.lstat()
        if not stat.S_ISDIR(root_stat.st_mode):
            errors += 1

        def walk(directory: Path, relative_dir: Path = Path()) -> bool:
            nonlocal errors
            try:
                iterator = os.scandir(directory)
            except OSError:
                errors += 1
                return False
            with iterator:
                try:
                    children = sorted(iterator, key=lambda entry: entry.name)
                except OSError:
                    errors += 1
                    return False
                for child in children:
                    name = child.name
                    relative = (relative_dir / name).as_posix()
                    if _is_secret(name):
                        counts["secret_excluded"] += 1
                        continue
                    if name in _SKIP_DIRS:
                        counts["metadata_excluded"] += 1
                        continue
                    try:
                        metadata = child.stat(follow_symlinks=False)
                        mode = metadata.st_mode
                        if stat.S_ISLNK(mode):
                            kind = "symlink"
                        elif stat.S_ISDIR(mode):
                            kind = "directory"
                        elif stat.S_ISREG(mode):
                            kind = "file"
                        else:
                            kind = "other"
                        entry: dict[str, Any] = {
                            "path": relative,
                            "kind": kind,
                            "mode": stat.S_IMODE(mode),
                            "size_bytes": metadata.st_size if kind != "symlink" else None,
                            "mtime_ns": metadata.st_mtime_ns,
                            "sha256": None,
                            "hash_status": "not_allowlisted",
                        }
                        if relative in allowed_hashes and kind == "file":
                            try:
                                size, digest = _hash_file(Path(child.path))
                                entry["size_bytes"] = size
                                entry["sha256"] = digest
                                entry["hash_status"] = "measured"
                            except OSError:
                                errors += 1
                                entry["hash_status"] = "unavailable"
                        elif relative in allowed_hashes and kind == "symlink":
                            errors += 1
                            entry["hash_status"] = "unavailable"
                        entries.append(entry)
                        if kind == "directory":
                            entry_index = len(entries) - 1
                            if not walk(Path(child.path), relative_dir / name):
                                del entries[entry_index:]
                    except OSError:
                        errors += 1
            return True

        if stat.S_ISDIR(root_stat.st_mode):
            walk(root)
        status = "incomplete" if errors else "complete"
        record = {
            "snapshot_id": snapshot_id,
            "event_id": event_id,
            "event_seq": event_seq,
            "label": label,
            "run_id": self.run_id,
            "phase_id": phase_id,
            "timestamp_utc": _utc_now(),
            "monotonic_ns": time.monotonic_ns(),
            "agent_id": agent_id,
            "parent_agent_id": parent_agent_id,
            "turn_id": turn_id,
            "source": source,
            "status": status,
            "entries": entries,
            "skipped_counts": counts,
            "error_count": errors,
        }
        self._snapshot_file.write(json.dumps(record, sort_keys=True) + "\n")
        self._snapshot_file.flush()
        if errors:
            self._incomplete = True
        self.record("snapshot_end", phase_id, agent_id=agent_id, parent_agent_id=parent_agent_id,
                    turn_id=turn_id, source=source,
                    details={"snapshot_id": snapshot_id, "status": status})
        return {"status": status, "error_count": errors}

    def finalize(
        self,
        outcome: str,
        evidence_status: str,
        *,
        agent_id: str | None = None,
        parent_agent_id: str | None = None,
        turn_id: str | None = None,
        source: str | None = None,
        error: str | None = None,
    ) -> None:
        if self._finalized:
            raise RuntimeError("observer is finalized")
        if outcome not in {"pass", "fail", "error", "incomplete"}:
            raise ValueError("unsupported outcome")
        if evidence_status not in {"complete", "incomplete"}:
            raise ValueError("unsupported evidence status")
        if self._active_phases:
            self._incomplete = True
        status = "incomplete" if self._incomplete else evidence_status
        details: dict[str, Any] = {
            "result": outcome, "status": status, "evidence_status": status,
        }
        if error is not None:
            details["reason"] = re.sub(r"[^a-z0-9_-]", "_", error.lower())[:80]
        self.record("run_end", source=source or "observer", agent_id=agent_id,
                    parent_agent_id=parent_agent_id, turn_id=turn_id, details=details)
        self._finalized = True
        self._event_file.close()
        self._snapshot_file.close()
