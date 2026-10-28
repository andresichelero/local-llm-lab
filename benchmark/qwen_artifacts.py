"""Discover and safely cache Qwen3.5 model artifacts from the Hugging Face Hub."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any


HF_API = "https://huggingface.co/api"
HF_RESOLVE = "https://huggingface.co"
DEFAULT_MAX_CACHE_BYTES = 60 * 1024**3
MAX_METADATA_HASH_BYTES = 64 * 1024**2
_CHUNK_SIZE = 1024 * 1024
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
_SAFE_COMPONENT_RE = re.compile(r"^[A-Za-z0-9._-]+$")
_EXL3_BRANCHES = (
    "2.00bpw",
    "2.50bpw",
    "3.00bpw",
    "3.50bpw",
    "4.00bpw",
    "5.00bpw",
    "6.00bpw",
)


class ArtifactError(ValueError):
    """Raised when an artifact is unsafe, incomplete, or fails verification."""


# These repositories cover the official checkpoints, the requested GGUF/EXL3
# publishers, and representative direct-base quantization formats found on HF.
# A repository's card declaration is checked before community weights are listed.
_REPO_SPECS: tuple[dict[str, Any], ...] = (
    {
        "repo_id": "Qwen/Qwen3.5-4B",
        "model_id": "4B",
        "kind": "direct",
        "engine": "transformers",
    },
    {
        "repo_id": "Qwen/Qwen3.5-9B",
        "model_id": "9B",
        "kind": "direct",
        "engine": "transformers",
    },
    {
        "repo_id": "unsloth/Qwen3.5-4B-GGUF",
        "model_id": "4B",
        "kind": "gguf",
        "engine": "llama.cpp",
    },
    {
        "repo_id": "unsloth/Qwen3.5-9B-GGUF",
        "model_id": "9B",
        "kind": "gguf",
        "engine": "llama.cpp",
    },
    {
        "repo_id": "bartowski/Qwen_Qwen3.5-4B-GGUF",
        "model_id": "4B",
        "kind": "gguf",
        "engine": "llama.cpp",
    },
    {
        "repo_id": "bartowski/Qwen_Qwen3.5-9B-GGUF",
        "model_id": "9B",
        "kind": "gguf",
        "engine": "llama.cpp",
    },
    {
        "repo_id": "mradermacher/Qwen3.5-4B-GGUF",
        "model_id": "4B",
        "kind": "gguf",
        "engine": "llama.cpp",
    },
    {
        "repo_id": "mradermacher/Qwen3.5-4B-i1-GGUF",
        "model_id": "4B",
        "kind": "gguf",
        "engine": "llama.cpp",
    },
    {
        "repo_id": "mradermacher/Qwen3.5-9B-GGUF",
        "model_id": "9B",
        "kind": "gguf",
        "engine": "llama.cpp",
    },
    {
        "repo_id": "mradermacher/Qwen3.5-9B-i1-GGUF",
        "model_id": "9B",
        "kind": "gguf",
        "engine": "llama.cpp",
    },
    {
        "repo_id": "turboderp/Qwen3.5-9B-exl3",
        "model_id": "9B",
        "kind": "exl3",
        "engine": "exllamav3",
    },
    {
        "repo_id": "cyankiwi/Qwen3.5-4B-AWQ-4bit",
        "model_id": "4B",
        "kind": "safetensors",
        "quantfmt": "AWQ-4bit",
        "engine": "transformers/awq",
    },
    {
        "repo_id": "cyankiwi/Qwen3.5-9B-AWQ-4bit",
        "model_id": "9B",
        "kind": "safetensors",
        "quantfmt": "AWQ-4bit",
        "engine": "transformers/awq",
    },
    {
        "repo_id": "J-Fraudster/Qwen3.5-4B-W4A16-AutoRound-GPTQ",
        "model_id": "4B",
        "kind": "safetensors",
        "quantfmt": "GPTQ-W4A16-AutoRound",
        "engine": "transformers/gptqmodel",
    },
    {
        "repo_id": "J-Fraudster/Qwen3.5-9B-W4A16-AutoRound-GPTQ",
        "model_id": "9B",
        "kind": "safetensors",
        "quantfmt": "GPTQ-W4A16-AutoRound",
        "engine": "transformers/gptqmodel",
    },
    {
        "repo_id": "RedHatAI/Qwen3.5-4B-FP8-dynamic",
        "model_id": "4B",
        "kind": "safetensors",
        "quantfmt": "FP8-dynamic",
        "engine": "transformers",
    },
    {
        "repo_id": "RedHatAI/Qwen3.5-9B-FP8-dynamic",
        "model_id": "9B",
        "kind": "safetensors",
        "quantfmt": "FP8-dynamic",
        "engine": "transformers",
    },
    {
        "repo_id": "RedHatAI/Qwen3.5-4B-quantized.w4a16",
        "model_id": "4B",
        "kind": "safetensors",
        "quantfmt": "OpenVINO-W4A16",
        "engine": "openvino",
    },
    {
        "repo_id": "RedHatAI/Qwen3.5-9B-quantized.w4a16",
        "model_id": "9B",
        "kind": "safetensors",
        "quantfmt": "OpenVINO-W4A16",
        "engine": "openvino",
    },
    {
        "repo_id": "mlx-community/Qwen3.5-4B-MLX-4bit",
        "model_id": "4B",
        "kind": "safetensors",
        "quantfmt": "MLX-4bit",
        "engine": "mlx-lm",
    },
    {
        "repo_id": "mlx-community/Qwen3.5-9B-MLX-4bit",
        "model_id": "9B",
        "kind": "safetensors",
        "quantfmt": "MLX-4bit",
        "engine": "mlx-lm",
    },
    {
        "repo_id": "taobao-mnn/Qwen3.5-4B-MNN",
        "model_id": "4B",
        "kind": "mnn",
        "quantfmt": "MNN",
        "engine": "MNN",
    },
    {
        "repo_id": "taobao-mnn/Qwen3.5-9B-MNN",
        "model_id": "9B",
        "kind": "mnn",
        "quantfmt": "MNN",
        "engine": "MNN",
    },
)


def _request_json(url: str) -> dict[str, Any]:
    request = urllib.request.Request(
        url, headers={"User-Agent": "qwen-artifact-catalog/1.0"}
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        data = json.load(response)
    if not isinstance(data, dict):
        raise ArtifactError(f"Unexpected Hub API response type at {url}")
    return data


def _repo_url(repo_id: str, suffix: str) -> str:
    return f"{HF_API}/models/{urllib.parse.quote(repo_id, safe='/')}{suffix}"


def _normalize_base_models(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str)]
    return []


def _base_record(
    repo_id: str, model_id: str, card_data: dict[str, Any]
) -> dict[str, Any]:
    official_id = f"Qwen/Qwen3.5-{model_id}"
    if repo_id == official_id:
        return {
            "status": "verified",
            "model_id": official_id,
            "evidence": "artifact is served directly by the official Qwen repository",
        }

    declared = _normalize_base_models(card_data.get("base_model"))
    accepted = {official_id, f"{official_id}-Base"}
    matching = [item for item in declared if item in accepted]
    if matching:
        return {
            "status": "publisher_declared",
            "model_id": official_id,
            "declared_model_id": matching[0],
            "evidence": "Hugging Face model card base_model metadata; tensor equivalence not checked",
        }
    return {
        "status": "unverified",
        "model_id": official_id,
        "declared_model_id": declared[0] if declared else None,
        "evidence": "no exact Qwen3.5 base_model declaration in repository metadata",
    }


def _is_sidecar(name: str) -> bool:
    lower = name.lower()
    return any(token in lower for token in ("mmproj", "imatrix", "mtp"))


def _gguf_shard_parts(path: str) -> tuple[str, int, int] | None:
    stem = PurePosixPath(path).stem
    match = re.fullmatch(r"(.+?)[._-](\d{5})-of-(\d{5})", stem, re.IGNORECASE)
    if not match:
        return None
    return match.group(1), int(match.group(2)), int(match.group(3))


def _quant_from_gguf(path: str, model_id: str) -> str:
    stem = PurePosixPath(path).stem
    model_prefix = re.compile(
        rf"^(?:Qwen_)?Qwen3\.5[-_]{re.escape(model_id)}(?=$|[._-])", re.IGNORECASE
    )
    quant = model_prefix.sub("", stem, count=1).lstrip("._-")
    if not quant:
        quant = stem
    i1 = re.match(r"^i1[._-]+(.+)$", quant, re.IGNORECASE)
    if i1:
        quant = "I1-" + i1.group(1)
    return quant.upper()


def _gguf_artifact_groups(
    files: list[dict[str, Any]],
    model_id: str,
    warnings: list[str],
    repo_id: str,
) -> list[tuple[str, list[dict[str, Any]]]]:
    singles: list[tuple[str, list[dict[str, Any]]]] = []
    shards: dict[tuple[str, str, int], list[tuple[int, dict[str, Any]]]] = {}
    for record in files:
        shard = _gguf_shard_parts(record["path"])
        if shard is None:
            singles.append((_quant_from_gguf(record["path"], model_id), [record]))
            continue
        prefix, index, total = shard
        quantfmt = _quant_from_gguf(prefix + ".gguf", model_id)
        key = (quantfmt, prefix.lower(), total)
        shards.setdefault(key, []).append((index, record))

    groups = list(singles)
    for (quantfmt, prefix, total), members in sorted(shards.items()):
        indexes = [index for index, _ in members]
        if len(members) != total or sorted(indexes) != list(range(1, total + 1)):
            warnings.append(
                f"{repo_id}: incomplete GGUF shard set for {prefix}; skipped"
            )
            continue
        groups.append((quantfmt, [record for _, record in sorted(members)]))
    return groups


def _weight_records(
    siblings: list[Any], kind: str, model_id: str, repo_id: str
) -> tuple[list[dict[str, Any]], list[str]]:
    selected: list[dict[str, Any]] = []
    warnings: list[str] = []
    for sibling in siblings:
        if not isinstance(sibling, dict):
            continue
        name = sibling.get("rfilename")
        if not isinstance(name, str):
            continue
        lower = name.lower()
        if _is_sidecar(name):
            continue
        if kind == "gguf" and not lower.endswith(".gguf"):
            continue
        if kind == "direct" and not lower.endswith(".safetensors"):
            continue
        if kind in {"safetensors", "exl3"} and not lower.endswith(".safetensors"):
            continue
        if (
            kind == "mnn"
            and not lower.endswith((".mnn", ".mnn.weight"))
            and PurePosixPath(lower).name != "embeddings_bf16.bin"
        ):
            continue

        lfs = sibling.get("lfs") if isinstance(sibling.get("lfs"), dict) else {}
        size = lfs.get("size", sibling.get("size"))
        digest = lfs.get("sha256")
        if (
            not isinstance(size, int)
            or isinstance(size, bool)
            or size < 0
            or not isinstance(digest, str)
            or not _SHA256_RE.fullmatch(digest)
        ):
            warnings.append(
                f"{repo_id}: skipped {name}; missing exact LFS size or SHA-256"
            )
            continue
        selected.append(
            {"path": name, "size": size, "sha256": digest, "sha256_source": "lfs"}
        )

    if kind == "direct" and not selected:
        warnings.append(f"{repo_id}: no direct safetensors model weights were listed")
    if kind != "direct" and not selected:
        warnings.append(f"{repo_id}: no eligible model weight files were listed")
    return selected, warnings


def _is_exl3_metadata_path(path: str) -> bool:
    name = PurePosixPath(path).name.lower()
    if name.startswith(("readme", "license", "notice", "copying")):
        return False
    suffix = PurePosixPath(name).suffix
    return suffix in {".json", ".jinja", ".model", ".txt", ".vocab", ".merges"}


def _resolved_content_sha256(
    repo_id: str, revision: str, path: str, expected_size: int
) -> str:
    if expected_size > MAX_METADATA_HASH_BYTES:
        raise ArtifactError(
            f"metadata blob is too large to hash safely: {path} ({expected_size} bytes)"
        )
    url = f"{HF_RESOLVE}/{urllib.parse.quote(repo_id, safe='/')}/resolve/{revision}/{urllib.parse.quote(path, safe='/')}"
    request = urllib.request.Request(
        url, headers={"User-Agent": "qwen-artifact-catalog/1.0"}
    )
    try:
        response_context = urllib.request.urlopen(request, timeout=20)
    except urllib.error.HTTPError as exc:
        raise ArtifactError(
            f"metadata download failed with HTTP {exc.code}: {repo_id}/{path}"
        ) from exc
    digest = hashlib.sha256()
    actual_size = 0
    with response_context as response:
        status = getattr(response, "status", None)
        if status is None:
            status = response.getcode()
        if status != 200:
            raise ArtifactError(
                f"metadata download returned HTTP {status}: {repo_id}/{path}"
            )
        while True:
            chunk = response.read(_CHUNK_SIZE)
            if not chunk:
                break
            actual_size += len(chunk)
            if actual_size > expected_size or actual_size > MAX_METADATA_HASH_BYTES:
                raise ArtifactError(
                    f"metadata download exceeded its recorded size: {repo_id}/{path}"
                )
            digest.update(chunk)
    if actual_size != expected_size:
        raise ArtifactError(
            f"metadata size mismatch for {repo_id}/{path}: expected {expected_size}, got {actual_size}"
        )
    return digest.hexdigest()


def _exl3_metadata_records(
    siblings: list[Any],
    repo_id: str,
    revision: str,
    warnings: list[str],
    hash_cache: dict[tuple[str, str, int], str] | None = None,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    cache = hash_cache if hash_cache is not None else {}
    for sibling in siblings:
        if not isinstance(sibling, dict):
            continue
        path = sibling.get("rfilename")
        if not isinstance(path, str) or not _is_exl3_metadata_path(path):
            continue
        lfs = sibling.get("lfs") if isinstance(sibling.get("lfs"), dict) else {}
        size = lfs.get("size", sibling.get("size"))
        if not isinstance(size, int) or isinstance(size, bool) or size < 0:
            warnings.append(
                f"{repo_id}@{revision}: skipped metadata {path}; missing exact size"
            )
            continue
        digest = lfs.get("sha256")
        if isinstance(digest, str) and _SHA256_RE.fullmatch(digest):
            hash_source = "lfs"
        else:
            blob_id = sibling.get("blobId")
            if isinstance(blob_id, str) and re.fullmatch(r"[0-9a-f]{40}", blob_id):
                cache_identity = blob_id
            else:
                cache_identity = f"{revision}:{path}"
            cache_key = (repo_id, cache_identity, size)
            try:
                digest = cache.get(cache_key)
                if digest is None:
                    digest = _resolved_content_sha256(repo_id, revision, path, size)
                    cache[cache_key] = digest
                hash_source = "resolved_content"
            except (OSError, urllib.error.URLError, ArtifactError) as exc:
                warnings.append(
                    f"{repo_id}@{revision}: skipped metadata {path}; SHA-256 unavailable ({type(exc).__name__}: {exc})"
                )
                continue
        records.append(
            {"path": path, "size": size, "sha256": digest, "sha256_source": hash_source}
        )

    names = {PurePosixPath(record["path"]).name.lower() for record in records}
    missing = []
    if "config.json" not in names:
        missing.append("config.json")
    if "tokenizer_config.json" not in names:
        missing.append("tokenizer_config.json")
    if (
        not ({"tokenizer.json", "tokenizer.model"} & names)
        and not {"vocab.json", "merges.txt"} <= names
    ):
        missing.append("tokenizer files")
    if missing:
        warnings.append(
            f"{repo_id}@{revision}: EXL3 metadata manifest is missing {', '.join(missing)}"
        )
    return records


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug[:48] or "artifact"


def _artifact_id(
    model_id: str,
    repo_id: str,
    revision: str,
    quantfmt: str,
    files: list[dict[str, Any]],
) -> str:
    identity = {
        "model_id": model_id,
        "repo_id": repo_id,
        "revision": revision,
        "quantfmt": quantfmt,
        "files": [
            {"path": item["path"], "size": item["size"], "sha256": item["sha256"]}
            for item in files
        ],
    }
    digest = hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:16]
    return f"qwen-{model_id.lower()}-{_slug(repo_id)}-{_slug(quantfmt)}-{digest}"


def _revision_refs(spec: dict[str, Any], refs: dict[str, Any]) -> list[tuple[str, str]]:
    wanted = set(_EXL3_BRANCHES) if spec["kind"] == "exl3" else {"main"}
    result: list[tuple[str, str]] = []
    branches = refs.get("branches", [])
    if not isinstance(branches, list):
        return result
    for branch in branches:
        if not isinstance(branch, dict):
            continue
        name, target = branch.get("name"), branch.get("targetCommit")
        if (
            isinstance(name, str)
            and name in wanted
            and isinstance(target, str)
            and _COMMIT_RE.fullmatch(target)
        ):
            result.append((name, target))
    return result


def _build_artifacts(
    spec: dict[str, Any],
    revision_ref: str,
    revision: str,
    info: dict[str, Any],
    warnings: list[str],
    metadata_hash_cache: dict[tuple[str, str, int], str] | None = None,
) -> list[dict[str, Any]]:
    repo_id = str(spec["repo_id"])
    model_id = str(spec["model_id"])
    kind = str(spec["kind"])
    returned_sha = info.get("sha")
    if returned_sha != revision:
        warnings.append(
            f"{repo_id}@{revision_ref}: revision response did not resolve to the requested commit; skipped"
        )
        return []
    card_data = info.get("cardData") if isinstance(info.get("cardData"), dict) else {}
    source_base = _base_record(repo_id, model_id, card_data)
    if source_base["status"] == "unverified":
        if source_base.get("declared_model_id"):
            warnings.append(
                f"{repo_id}@{revision_ref}: declared base {source_base['declared_model_id']} does not match the requested Qwen3.5 model; skipped"
            )
            return []
        warnings.append(
            f"{repo_id}@{revision_ref}: no base_model declaration; artifact retained as unverified"
        )
    siblings = info.get("siblings", [])
    if not isinstance(siblings, list):
        warnings.append(f"{repo_id}@{revision_ref}: missing repository tree; skipped")
        return []
    files, file_warnings = _weight_records(siblings, kind, model_id, repo_id)
    warnings.extend(file_warnings)
    if any("missing exact LFS size or SHA-256" in warning for warning in file_warnings):
        warnings.append(
            f"{repo_id}@{revision_ref}: incomplete model-weight manifest; skipped"
        )
        return []
    if not files:
        return []
    if kind == "exl3":
        metadata_warnings: list[str] = []
        metadata_files = _exl3_metadata_records(
            siblings, repo_id, revision, metadata_warnings, metadata_hash_cache
        )
        warnings.extend(metadata_warnings)
        if any(
            "skipped metadata" in warning or "metadata manifest is missing" in warning
            for warning in metadata_warnings
        ):
            warnings.append(
                f"{repo_id}@{revision_ref}: incomplete EXL3 configuration/tokenizer manifest; skipped"
            )
            return []
        files.extend(metadata_files)

    groups: list[tuple[str, list[dict[str, Any]]]]
    if kind == "gguf":
        groups = _gguf_artifact_groups(files, model_id, warnings, repo_id)
    else:
        if kind == "direct":
            quantfmt = "HF-Safetensors"
        elif kind == "exl3":
            quantfmt = "EXL3-" + revision_ref.removesuffix("bpw") + "BPW"
        else:
            quantfmt = str(spec["quantfmt"])
        groups = [(quantfmt, files)]

    artifacts: list[dict[str, Any]] = []
    for quantfmt, group_files in groups:
        group_files.sort(key=lambda item: item["path"])
        artifacts.append(
            {
                "artifact_id": _artifact_id(
                    model_id, repo_id, revision, quantfmt, group_files
                ),
                "model_id": model_id,
                "repo_id": repo_id,
                "revision": revision,
                "revision_ref": revision_ref,
                "quantfmt": quantfmt,
                "engine": spec["engine"],
                "source_base": source_base,
                "files": group_files,
                "total_bytes": sum(item["size"] for item in group_files),
            }
        )
    return artifacts


def _dedup_summary(artifacts: list[dict[str, Any]]) -> dict[str, Any]:
    locations: dict[str, list[dict[str, str]]] = {}
    for artifact in artifacts:
        for file_record in artifact["files"]:
            locations.setdefault(file_record["sha256"], []).append(
                {
                    "artifact_id": artifact["artifact_id"],
                    "path": file_record["path"],
                }
            )
    duplicates = [
        {"sha256": digest, "references": refs}
        for digest, refs in sorted(locations.items())
        if len(refs) > 1
    ]
    return {"unique_sha256_count": len(locations), "duplicate_sha256": duplicates}


def discover_catalog() -> dict[str, Any]:
    """Discover pinned model-weight metadata without downloading model weights."""
    artifacts: list[dict[str, Any]] = []
    warnings: list[str] = []
    repository_log: list[dict[str, Any]] = []
    metadata_hash_cache: dict[tuple[str, str, int], str] = {}
    for spec in _REPO_SPECS:
        repo_id = str(spec["repo_id"])
        entry: dict[str, Any] = {
            "repo_id": repo_id,
            "model_id": spec["model_id"],
            "kind": spec["kind"],
        }
        try:
            refs = _request_json(_repo_url(repo_id, "/refs"))
        except (
            OSError,
            urllib.error.URLError,
            json.JSONDecodeError,
            ArtifactError,
        ) as exc:
            warning = f"{repo_id}: refs lookup failed: {type(exc).__name__}: {exc}"
            warnings.append(warning)
            entry.update({"status": "unavailable", "detail": warning})
            repository_log.append(entry)
            continue

        revisions = _revision_refs(spec, refs)
        if not revisions:
            warning = f"{repo_id}: requested immutable revision refs were not published"
            warnings.append(warning)
            entry.update({"status": "no_requested_refs", "detail": warning})
            repository_log.append(entry)
            continue

        ref_records: list[dict[str, Any]] = []
        for revision_ref, revision in revisions:
            try:
                info = _request_json(
                    _repo_url(repo_id, f"/revision/{revision}?blobs=true")
                )
                current = _build_artifacts(
                    spec, revision_ref, revision, info, warnings, metadata_hash_cache
                )
            except (
                OSError,
                urllib.error.URLError,
                json.JSONDecodeError,
                ArtifactError,
            ) as exc:
                warning = f"{repo_id}@{revision_ref}: metadata lookup failed: {type(exc).__name__}: {exc}"
                warnings.append(warning)
                ref_records.append(
                    {
                        "revision_ref": revision_ref,
                        "revision": revision,
                        "status": "unavailable",
                        "detail": warning,
                    }
                )
                continue
            artifacts.extend(current)
            ref_records.append(
                {
                    "revision_ref": revision_ref,
                    "revision": revision,
                    "status": "cataloged" if current else "no_model_weights",
                    "artifact_count": len(current),
                }
            )
        entry.update({"status": "queried", "refs": ref_records})
        repository_log.append(entry)

    artifacts.sort(
        key=lambda item: (
            item["model_id"],
            item["repo_id"],
            item["quantfmt"],
            item["revision"],
            item["artifact_id"],
        )
    )
    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z"),
        "source": {
            "api": HF_API,
            "revision_policy": "each artifact is pinned to the exact commit SHA resolved from the Hub refs endpoint",
            "scope": "official Qwen checkpoints; Unsloth, bartowski, mradermacher static/i1 GGUF, turboderp EXL3; representative direct-base AWQ, GPTQ, FP8, OpenVINO, MLX, and MNN formats",
            "weight_policy": "model weights plus EXL3 configuration/tokenizer metadata; GGUF mmproj, imatrix, and MTP sidecars are excluded",
            "provenance_policy": "official source repository is verified; community source is publisher_declared only when exact Qwen3.5 base_model metadata is present",
        },
        "repository_log": repository_log,
        "warnings": warnings,
        "deduplication": _dedup_summary(artifacts),
        "artifacts": artifacts,
    }


def save_catalog(path: str | os.PathLike[str], catalog: dict[str, Any]) -> Path:
    """Atomically save the catalog as stable, UTF-8 JSON."""
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(catalog, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=destination.parent,
            prefix=f".{destination.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary.write(encoded)
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_name = temporary.name
        os.replace(temporary_name, destination)
    finally:
        if temporary_name and os.path.exists(temporary_name):
            os.unlink(temporary_name)
    return destination


def refresh_exl3_metadata(catalog: dict[str, Any]) -> dict[str, Any]:
    """Refresh only pinned EXL3 revisions in an existing catalog.

    Other artifact records and the catalog's original discovery timestamp are
    preserved. Model weights are read only through Hub metadata; only small
    non-LFS configuration/tokenizer blobs are fetched to calculate SHA-256.
    """
    if not isinstance(catalog, dict) or not isinstance(catalog.get("artifacts"), list):
        raise ArtifactError("catalog must contain an artifacts list")
    spec = next((item for item in _REPO_SPECS if item.get("kind") == "exl3"), None)
    if spec is None:
        raise ArtifactError("no EXL3 repository is configured")
    selected = [
        (index, item)
        for index, item in enumerate(catalog["artifacts"])
        if isinstance(item, dict)
        and item.get("repo_id") == spec["repo_id"]
        and item.get("engine") == "exllamav3"
    ]
    if not selected:
        raise ArtifactError("existing catalog has no pinned EXL3 artifacts to refresh")

    refreshed: dict[tuple[str, str], dict[str, Any]] = {}
    metadata_hash_cache: dict[tuple[str, str, int], str] = {}
    metadata_file_counts: dict[tuple[str, str], int] = {}
    for _, artifact in selected:
        revision, revision_ref = artifact.get("revision"), artifact.get("revision_ref")
        if (
            not isinstance(revision, str)
            or not _COMMIT_RE.fullmatch(revision)
            or not isinstance(revision_ref, str)
        ):
            raise ArtifactError("existing EXL3 artifact has no pinned revision and ref")
        key = (revision, revision_ref)
        if key in refreshed:
            continue
        info = _request_json(
            _repo_url(str(spec["repo_id"]), f"/revision/{revision}?blobs=true")
        )
        build_warnings: list[str] = []
        replacements = _build_artifacts(
            spec, revision_ref, revision, info, build_warnings, metadata_hash_cache
        )
        if build_warnings or len(replacements) != 1:
            detail = (
                "; ".join(build_warnings)
                if build_warnings
                else f"expected one EXL3 artifact, found {len(replacements)}"
            )
            raise ArtifactError(
                f"could not refresh EXL3 metadata for {revision_ref}: {detail}"
            )
        refreshed[key] = replacements[0]
        metadata_file_counts[key] = sum(
            not record["path"].lower().endswith(".safetensors")
            for record in replacements[0]["files"]
        )

    updated = json.loads(json.dumps(catalog))
    replaced_artifacts = []
    for artifact in updated["artifacts"]:
        if (
            isinstance(artifact, dict)
            and artifact.get("repo_id") == spec["repo_id"]
            and artifact.get("engine") == "exllamav3"
        ):
            key = (artifact["revision"], artifact["revision_ref"])
            replaced_artifacts.append(refreshed[key])
        else:
            replaced_artifacts.append(artifact)
    updated["artifacts"] = replaced_artifacts
    updated["deduplication"] = _dedup_summary(replaced_artifacts)
    refreshed_at = (
        datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    )
    updated["exl3_metadata_refresh"] = {
        "updated_at": refreshed_at,
        "repository": spec["repo_id"],
        "revision_count": len(refreshed),
        "metadata_file_count": sum(metadata_file_counts.values()),
        "metadata_hash_policy": "LFS SHA-256 when published; otherwise SHA-256 computed from commit-pinned resolve content",
    }
    source = updated.get("source")
    if isinstance(source, dict):
        source["weight_policy"] = (
            "model weights plus EXL3 config/tokenizer metadata; GGUF mmproj, imatrix, and MTP sidecars are excluded"
        )
    for entry in updated.get("repository_log", []):
        if isinstance(entry, dict) and entry.get("repo_id") == spec["repo_id"]:
            entry["metadata_refreshed_at"] = refreshed_at
            for ref_entry in entry.get("refs", []):
                if isinstance(ref_entry, dict):
                    ref_key = (ref_entry.get("revision"), ref_entry.get("revision_ref"))
                    if ref_key in metadata_file_counts:
                        ref_entry["metadata_file_count"] = metadata_file_counts[ref_key]
    return updated


def repartition_gguf_catalog(catalog: dict[str, Any]) -> dict[str, Any]:
    """Derive a corrected catalog by splitting existing GGUF file metadata only.

    This performs no Hub requests. Every non-sharded GGUF file becomes one
    artifact; only complete, explicitly numbered shard sets remain together.
    Non-GGUF artifacts and their pinned metadata are preserved.
    """
    if not isinstance(catalog, dict) or not isinstance(catalog.get("artifacts"), list):
        raise ArtifactError("catalog must contain an artifacts list")
    updated = json.loads(json.dumps(catalog))
    artifacts: list[dict[str, Any]] = []
    warnings = list(updated.get("warnings", []))
    artifact_counts: dict[tuple[str, str, str], int] = {}
    for artifact in updated["artifacts"]:
        if not isinstance(artifact, dict) or artifact.get("engine") != "llama.cpp":
            artifacts.append(artifact)
            continue
        files = artifact.get("files")
        if (
            not isinstance(files, list)
            or not files
            or not all(
                isinstance(record, dict)
                and str(record.get("path", "")).lower().endswith(".gguf")
                for record in files
            )
        ):
            artifacts.append(artifact)
            continue
        groups = _gguf_artifact_groups(
            files, str(artifact["model_id"]), warnings, str(artifact["repo_id"])
        )
        for quantfmt, group_files in groups:
            replacement = dict(artifact)
            replacement["quantfmt"] = quantfmt
            replacement["files"] = sorted(group_files, key=lambda item: item["path"])
            replacement["total_bytes"] = sum(item["size"] for item in group_files)
            replacement["artifact_id"] = _artifact_id(
                str(replacement["model_id"]),
                str(replacement["repo_id"]),
                str(replacement["revision"]),
                quantfmt,
                replacement["files"],
            )
            artifacts.append(replacement)
            key = (
                replacement["repo_id"],
                replacement.get("revision_ref", ""),
                replacement["revision"],
            )
            artifact_counts[key] = artifact_counts.get(key, 0) + 1

    artifacts.sort(
        key=lambda item: (
            item.get("model_id", ""),
            item.get("repo_id", ""),
            item.get("quantfmt", ""),
            item.get("revision", ""),
            item.get("artifact_id", ""),
        )
    )
    updated["artifacts"] = artifacts
    updated["deduplication"] = _dedup_summary(artifacts)
    updated["warnings"] = warnings
    updated["catalog_version"] = 2
    updated["supersedes"] = "artifact-catalog.json"
    updated["catalog_update"] = {
        "source_generated_at": catalog.get("generated_at"),
        "updated_at": datetime.now(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z"),
        "operation": "repartition existing GGUF files into one artifact per quantization; preserve explicit complete shard groups",
        "hub_api_requests": 0,
    }
    source = updated.get("source")
    if isinstance(source, dict):
        source["gguf_quantization_policy"] = (
            "one quantization per GGUF artifact; combine only complete explicitly numbered shard sets"
        )
    for repository in updated.get("repository_log", []):
        if not isinstance(repository, dict):
            continue
        for ref in repository.get("refs", []):
            if not isinstance(ref, dict):
                continue
            key = (
                repository.get("repo_id"),
                ref.get("revision_ref", ""),
                ref.get("revision"),
            )
            if key in artifact_counts:
                ref["artifact_count"] = artifact_counts[key]
    return updated


def _validated_artifact(artifact: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
    artifact_id = artifact.get("artifact_id")
    if (
        not isinstance(artifact_id, str)
        or not _SAFE_COMPONENT_RE.fullmatch(artifact_id)
        or artifact_id in {".", ".."}
    ):
        raise ArtifactError("artifact_id must be one safe path component")
    repo_id = artifact.get("repo_id")
    revision = artifact.get("revision")
    if not isinstance(repo_id, str) or not re.fullmatch(
        r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo_id
    ):
        raise ArtifactError("repo_id is invalid")
    if not isinstance(revision, str) or not _COMMIT_RE.fullmatch(revision):
        raise ArtifactError("revision must be a 40-character commit SHA")
    raw_files = artifact.get("files")
    if not isinstance(raw_files, list) or not raw_files:
        raise ArtifactError("artifact must list at least one file")
    files: list[dict[str, Any]] = []
    paths: set[str] = set()
    for item in raw_files:
        if not isinstance(item, dict):
            raise ArtifactError("artifact file entry must be an object")
        raw_path, size, digest = item.get("path"), item.get("size"), item.get("sha256")
        if (
            not isinstance(raw_path, str)
            or "\\" in raw_path
            or raw_path.startswith("/")
        ):
            raise ArtifactError("file path must be a relative POSIX path")
        parsed_path = PurePosixPath(raw_path)
        if (
            not raw_path
            or any(part in {"", ".", ".."} for part in parsed_path.parts)
            or ":" in parsed_path.parts[0]
        ):
            raise ArtifactError("file path contains an unsafe component")
        if raw_path in paths:
            raise ArtifactError("artifact contains duplicate file paths")
        if not isinstance(size, int) or isinstance(size, bool) or size < 0:
            raise ArtifactError("file size must be a non-negative integer")
        if not isinstance(digest, str) or not _SHA256_RE.fullmatch(digest):
            raise ArtifactError(
                "file SHA-256 must be 64 lowercase hexadecimal characters"
            )
        paths.add(raw_path)
        files.append({"path": raw_path, "size": size, "sha256": digest})
    return artifact_id, files


def _hash_file(path: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(_CHUNK_SIZE), b""):
            digest.update(chunk)
            size += len(chunk)
    return size, digest.hexdigest()


def _matches_file(path: Path, record: dict[str, Any]) -> bool:
    if not path.is_file() or path.is_symlink():
        return False
    size, digest = _hash_file(path)
    return size == record["size"] and digest == record["sha256"]


def _assert_no_symlink_path(path: Path, root: Path) -> None:
    current = path
    while current != root and root in current.parents:
        if current.is_symlink():
            raise ArtifactError(f"refusing symlink inside cache: {current}")
        current = current.parent
    if current != root:
        raise ArtifactError("resolved cache path escaped cache root")


def _cache_bytes(root: Path) -> int:
    total = 0
    inodes: set[tuple[int, int]] = set()
    for directory, subdirs, filenames in os.walk(root, followlinks=False):
        base = Path(directory)
        subdirs[:] = [name for name in subdirs if not (base / name).is_symlink()]
        for filename in filenames:
            path = base / filename
            try:
                info = path.stat(follow_symlinks=False)
            except OSError:
                continue
            if not path.is_symlink() and (info.st_dev, info.st_ino) not in inodes:
                inodes.add((info.st_dev, info.st_ino))
                total += info.st_size
    return total


def _response_status(response: Any) -> int:
    status = getattr(response, "status", None)
    if isinstance(status, int):
        return status
    code = response.getcode()
    return int(code) if code is not None else 200


def _content_range(response: Any) -> str | None:
    headers = getattr(response, "headers", {})
    if hasattr(headers, "get"):
        value = headers.get("Content-Range")
        return str(value) if value is not None else None
    return None


def _header_int(response: Any, name: str) -> int | None:
    headers = getattr(response, "headers", {})
    value = headers.get(name) if hasattr(headers, "get") else None
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _download_object(
    repo_id: str,
    revision: str,
    record: dict[str, Any],
    object_path: Path,
    max_cache_bytes: int,
    root: Path,
) -> None:
    digest, expected_size = record["sha256"], record["size"]
    partial = object_path.with_suffix(".part")
    if object_path.exists():
        if _matches_file(object_path, record):
            return
        raise ArtifactError(
            f"existing content object is invalid and was preserved: {object_path}"
        )
    if partial.exists() and partial.is_symlink():
        raise ArtifactError(f"refusing symlink partial file: {partial}")
    offset = partial.stat().st_size if partial.exists() else 0
    if offset > expected_size:
        raise ArtifactError(
            f"existing partial exceeds expected size and was preserved: {partial}"
        )
    if offset == expected_size and partial.exists():
        if _matches_file(partial, record):
            os.replace(partial, object_path)
            return
        raise ArtifactError(
            f"full-sized partial has an invalid hash and was preserved: {partial}"
        )

    used = _cache_bytes(root)
    remaining_for_file = expected_size - offset
    if used + remaining_for_file > max_cache_bytes:
        raise ArtifactError(
            f"cache limit would be exceeded ({used + remaining_for_file} > {max_cache_bytes} bytes)"
        )
    if shutil.disk_usage(root).free < remaining_for_file:
        raise ArtifactError(
            f"insufficient free disk space for {remaining_for_file} more bytes"
        )

    relative_url = f"/{urllib.parse.quote(repo_id, safe='/')}/resolve/{revision}/{urllib.parse.quote(record['path'], safe='/')}"
    request = urllib.request.Request(
        HF_RESOLVE + relative_url, headers={"User-Agent": "qwen-artifact-cache/1.0"}
    )
    if offset:
        request.add_header("Range", f"bytes={offset}-")
    try:
        response_context = urllib.request.urlopen(request, timeout=60)
    except urllib.error.HTTPError as exc:
        raise ArtifactError(
            f"download failed with HTTP {exc.code} for {repo_id}/{record['path']}"
        ) from exc

    with response_context as response:
        status = _response_status(response)
        mode: str
        if status == 206:
            content_range = _content_range(response)
            match = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+)", content_range or "")
            if not match:
                raise ArtifactError("HTTP 206 response has an invalid Content-Range")
            start, end, total = map(int, match.groups())
            if start != offset or total != expected_size or end < start or end >= total:
                raise ArtifactError(
                    "HTTP 206 Content-Range does not match the requested artifact"
                )
            content_length = _header_int(response, "Content-Length")
            if content_length is not None and content_length != end - start + 1:
                raise ArtifactError(
                    "HTTP 206 Content-Length does not match Content-Range"
                )
            mode = "ab" if offset else "wb"
        elif status == 200:
            # A server that ignores Range starts from byte zero. Always replace.
            mode = "wb"
        else:
            raise ArtifactError(
                f"unexpected HTTP status {status} while downloading model weights"
            )

        partial.parent.mkdir(parents=True, exist_ok=True)
        with partial.open(mode) as destination:
            while True:
                chunk = response.read(_CHUNK_SIZE)
                if not chunk:
                    break
                destination.write(chunk)
            destination.flush()
            os.fsync(destination.fileno())

    actual_size, actual_sha = _hash_file(partial)
    if actual_size != expected_size:
        raise ArtifactError(
            f"downloaded size mismatch for {record['path']}: expected {expected_size}, got {actual_size}"
        )
    if actual_sha != digest:
        raise ArtifactError(f"downloaded SHA-256 mismatch for {record['path']}")
    os.replace(partial, object_path)


def ensure_artifact(
    artifact: dict[str, Any],
    cache_root: str | os.PathLike[str],
    *,
    max_cache_bytes: int = DEFAULT_MAX_CACHE_BYTES,
) -> Path:
    """Download and verify one catalog artifact into a content-deduplicated cache.

    Existing valid files are reused. Downloads are resumed only after a validated
    HTTP 206 Content-Range; an HTTP 200 response always replaces the partial file.
    """
    artifact_id, records = _validated_artifact(artifact)
    returns_directory = artifact.get("engine") == "exllamav3" or str(
        artifact.get("quantfmt", "")
    ).startswith("EXL3-")
    if (
        not isinstance(max_cache_bytes, int)
        or isinstance(max_cache_bytes, bool)
        or max_cache_bytes < 0
    ):
        raise ArtifactError("max_cache_bytes must be a non-negative integer")

    raw_root = Path(cache_root)
    if raw_root.is_symlink():
        raise ArtifactError("cache_root must not be a symlink")
    raw_root.mkdir(parents=True, exist_ok=True)
    root = raw_root.resolve()
    artifact_dir = root / artifact_id
    if artifact_dir.exists() and artifact_dir.is_symlink():
        raise ArtifactError(f"refusing symlink artifact directory: {artifact_dir}")
    artifact_dir.mkdir(parents=True, exist_ok=True)

    destinations: list[Path] = []
    all_present = True
    for record in records:
        destination = artifact_dir.joinpath(*PurePosixPath(record["path"]).parts)
        _assert_no_symlink_path(destination, root)
        if destination.exists():
            if not _matches_file(destination, record):
                raise ArtifactError(
                    f"existing destination is invalid and was preserved: {destination}"
                )
        else:
            all_present = False
        destinations.append(destination)
    if all_present:
        return (
            artifact_dir
            if returns_directory or len(destinations) != 1
            else destinations[0]
        )

    objects_dir = root / ".objects"
    if objects_dir.exists() and objects_dir.is_symlink():
        raise ArtifactError("refusing symlink content object directory")
    objects_dir.mkdir(exist_ok=True)
    required_digests = {
        record["sha256"]
        for record, destination in zip(records, destinations)
        if not destination.exists()
    }
    for record in records:
        if record["sha256"] not in required_digests:
            continue
        object_path = objects_dir / record["sha256"]
        _assert_no_symlink_path(object_path, root)
        _download_object(
            str(artifact["repo_id"]),
            str(artifact["revision"]),
            record,
            object_path,
            max_cache_bytes,
            root,
        )
        required_digests.remove(record["sha256"])

    for record, destination in zip(records, destinations):
        if destination.exists():
            continue
        object_path = objects_dir / record["sha256"]
        _assert_no_symlink_path(destination, root)
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.link(object_path, destination)
        except FileExistsError:
            if not _matches_file(destination, record):
                raise ArtifactError(
                    f"concurrent destination is invalid and was preserved: {destination}"
                )
        except OSError as exc:
            raise ArtifactError(
                f"cache filesystem cannot materialize deduplicated content: {exc}"
            ) from exc
    return (
        artifact_dir if returns_directory or len(destinations) != 1 else destinations[0]
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--discover",
        action="store_true",
        help="query Hugging Face metadata without downloading weights",
    )
    mode.add_argument(
        "--refresh-exl3-existing",
        action="store_true",
        help="refresh only pinned EXL3 entries in the existing output catalog",
    )
    parser.add_argument(
        "--output", required=True, help="path for artifact-catalog.json"
    )
    args = parser.parse_args(argv)
    try:
        if args.discover:
            catalog = discover_catalog()
        else:
            catalog = refresh_exl3_metadata(
                json.loads(Path(args.output).read_text(encoding="utf-8"))
            )
        saved = save_catalog(args.output, catalog)
        _save_discovery_log(saved.with_name("discovery-log.jsonl"), catalog)
    except (OSError, json.JSONDecodeError, ArtifactError, urllib.error.URLError) as exc:
        print(f"qwen-artifacts: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    print(f"saved {len(catalog['artifacts'])} artifacts to {saved}")
    print(
        f"unique SHA-256 files: {catalog['deduplication']['unique_sha256_count']}; warnings: {len(catalog['warnings'])}"
    )
    return 0


def _save_discovery_log(path: Path, catalog: dict[str, Any]) -> Path:
    """Write repository lookup outcomes and warnings as compact JSONL."""
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        {"event": "repository", "generated_at": catalog["generated_at"], **item}
        for item in catalog.get("repository_log", [])
    ]
    rows.extend(
        {"event": "warning", "generated_at": catalog["generated_at"], "detail": warning}
        for warning in catalog.get("warnings", [])
    )
    contents = "".join(
        json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows
    )
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary.write(contents)
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_name = temporary.name
        os.replace(temporary_name, path)
    finally:
        if temporary_name and os.path.exists(temporary_name):
            os.unlink(temporary_name)
    return path


if __name__ == "__main__":
    raise SystemExit(main())
