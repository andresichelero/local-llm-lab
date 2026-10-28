from __future__ import annotations

import hashlib
import io
import json
import tempfile
import unittest
from collections import namedtuple
from pathlib import Path
from unittest.mock import patch

from benchmark import qwen_artifacts as artifacts


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _artifact(data: bytes, *, path: str = "model.gguf") -> dict[str, object]:
    return {
        "artifact_id": "qwen3.5-9b-test-" + "a" * 40,
        "model_id": "9B",
        "repo_id": "publisher/model",
        "revision": "a" * 40,
        "revision_ref": "main",
        "quantfmt": "GGUF-Q4_K_M",
        "engine": "llama.cpp",
        "source_base": {"status": "unverified", "model_id": "Qwen/Qwen3.5-9B"},
        "files": [{"path": path, "size": len(data), "sha256": _sha(data)}],
        "total_bytes": len(data),
    }


class FakeResponse(io.BytesIO):
    def __init__(
        self, body: bytes, *, status: int, headers: dict[str, str] | None = None
    ) -> None:
        super().__init__(body)
        self.status = status
        self.headers = headers or {}

    def getcode(self) -> int:
        return self.status

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


class QwenArtifactCatalogTests(unittest.TestCase):
    def test_each_gguf_quantization_file_gets_its_own_artifact(self) -> None:
        commit = "9" * 40
        spec = {
            "repo_id": "unsloth/Qwen3.5-9B-GGUF",
            "model_id": "9B",
            "kind": "gguf",
            "engine": "llama.cpp",
        }
        names = (
            "Qwen3.5-9B-Q4_K_M.gguf",
            "Qwen3.5-9B-Q4_K_S.gguf",
            "Qwen3.5-9B-UD-Q4_K_XL.gguf",
        )
        siblings = [
            {
                "rfilename": name,
                "size": index + 1,
                "lfs": {"sha256": _sha(name.encode())},
            }
            for index, name in enumerate(names)
        ]

        found = artifacts._build_artifacts(
            spec,
            "main",
            commit,
            {
                "sha": commit,
                "cardData": {"base_model": "Qwen/Qwen3.5-9B"},
                "siblings": siblings,
            },
            [],
        )

        self.assertEqual(len(found), 3)
        self.assertTrue(all(len(item["files"]) == 1 for item in found))
        self.assertEqual(
            {item["quantfmt"] for item in found},
            {"Q4_K_M", "Q4_K_S", "UD-Q4_K_XL"},
        )

    def test_only_explicit_numbered_gguf_shards_are_grouped(self) -> None:
        commit = "8" * 40
        spec = {
            "repo_id": "publisher/Qwen3.5-9B-GGUF",
            "model_id": "9B",
            "kind": "gguf",
            "engine": "llama.cpp",
        }
        names = (
            "Qwen3.5-9B-Q4_K_M-00001-of-00002.gguf",
            "Qwen3.5-9B-Q4_K_M-00002-of-00002.gguf",
            "Qwen3.5-9B-Q4_K_S.gguf",
        )
        siblings = [
            {
                "rfilename": name,
                "size": index + 1,
                "lfs": {"sha256": _sha(name.encode())},
            }
            for index, name in enumerate(names)
        ]
        found = artifacts._build_artifacts(
            spec,
            "main",
            commit,
            {
                "sha": commit,
                "cardData": {"base_model": "Qwen/Qwen3.5-9B"},
                "siblings": siblings,
            },
            [],
        )

        grouped = next(item for item in found if item["quantfmt"] == "Q4_K_M")
        separate = next(item for item in found if item["quantfmt"] == "Q4_K_S")
        self.assertEqual(len(grouped["files"]), 2)
        self.assertEqual(len(separate["files"]), 1)

    def test_repartition_is_offline_and_preserves_non_gguf_metadata(self) -> None:
        commit = "7" * 40
        names = (
            "Qwen3.5-9B-Q4_K_M.gguf",
            "Qwen3.5-9B-Q4_K_S.gguf",
            "Qwen3.5-9B-UD-Q4_K_XL.gguf",
        )
        grouped_files = [
            {
                "path": name,
                "size": index + 1,
                "sha256": _sha(name.encode()),
                "sha256_source": "lfs",
            }
            for index, name in enumerate(names)
        ]
        old_gguf = {
            "artifact_id": "old-grouped-gguf",
            "model_id": "9B",
            "repo_id": "unsloth/Qwen3.5-9B-GGUF",
            "revision": commit,
            "revision_ref": "main",
            "quantfmt": "GGUF-Q4_K",
            "engine": "llama.cpp",
            "source_base": {"status": "publisher_declared"},
            "files": grouped_files,
            "total_bytes": sum(item["size"] for item in grouped_files),
        }
        exl = {
            "artifact_id": "pinned-exl",
            "model_id": "9B",
            "repo_id": "turboderp/Qwen3.5-9B-exl3",
            "revision": "6" * 40,
            "revision_ref": "2.50bpw",
            "quantfmt": "EXL3-2.50BPW",
            "engine": "exllamav3",
            "files": [
                {"path": "model.safetensors", "size": 1, "sha256": "a" * 64},
                {"path": "config.json", "size": 1, "sha256": "b" * 64},
                {"path": "tokenizer.json", "size": 1, "sha256": "c" * 64},
            ],
            "total_bytes": 3,
        }
        catalog = {
            "schema_version": 1,
            "generated_at": "2026-10-25T00:00:00Z",
            "source": {"api": "https://huggingface.co/api"},
            "artifacts": [old_gguf, exl],
            "warnings": [],
            "repository_log": [
                {
                    "repo_id": "unsloth/Qwen3.5-9B-GGUF",
                    "refs": [
                        {
                            "revision_ref": "main",
                            "revision": commit,
                            "artifact_count": 1,
                        },
                    ],
                }
            ],
            "deduplication": {"unique_sha256_count": 4, "duplicate_sha256": []},
        }

        with patch.object(
            artifacts, "_request_json", side_effect=AssertionError("must stay offline")
        ) as get_json:
            updated = artifacts.repartition_gguf_catalog(catalog)

        gguf = [item for item in updated["artifacts"] if item["engine"] == "llama.cpp"]
        refreshed_exl = next(
            item for item in updated["artifacts"] if item["engine"] == "exllamav3"
        )
        self.assertEqual(
            {item["quantfmt"] for item in gguf}, {"Q4_K_M", "Q4_K_S", "UD-Q4_K_XL"}
        )
        self.assertTrue(all(len(item["files"]) == 1 for item in gguf))
        self.assertEqual(refreshed_exl, exl)
        self.assertEqual(updated["generated_at"], catalog["generated_at"])
        self.assertEqual(updated["repository_log"][0]["refs"][0]["artifact_count"], 3)
        self.assertEqual(updated["catalog_update"]["hub_api_requests"], 0)
        self.assertEqual(get_json.call_count, 0)

    def test_discovery_pins_branch_commit_and_excludes_gguf_sidecars(self) -> None:
        commit = "b" * 40
        repo_specs = (
            {
                "repo_id": "bartowski/Qwen_Qwen3.5-9B-GGUF",
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
        )

        def get_json(url: str) -> dict[str, object]:
            if url.endswith("/refs"):
                name = "2.50bpw" if "turboderp" in url else "main"
                return {"branches": [{"name": name, "targetCommit": commit}]}
            is_exl = "turboderp" in url
            model_files = (
                [
                    {
                        "rfilename": "model.safetensors",
                        "size": 6,
                        "lfs": {"sha256": _sha(b"weight")},
                    },
                    {
                        "rfilename": "config.json",
                        "size": 2,
                        "lfs": {"sha256": _sha(b"{}")},
                    },
                    {
                        "rfilename": "tokenizer_config.json",
                        "size": 2,
                        "lfs": {"sha256": _sha(b"{}")},
                    },
                    {
                        "rfilename": "tokenizer.json",
                        "size": 2,
                        "lfs": {"sha256": _sha(b"{}")},
                    },
                ]
                if is_exl
                else [
                    {
                        "rfilename": "Qwen-Q4_K_M.gguf",
                        "size": 6,
                        "lfs": {"sha256": _sha(b"weight")},
                    },
                    {
                        "rfilename": "mmproj-F16.gguf",
                        "size": 4,
                        "lfs": {"sha256": _sha(b"mmpr")},
                    },
                    {
                        "rfilename": "imatrix.dat",
                        "size": 3,
                        "lfs": {"sha256": _sha(b"mat")},
                    },
                    {"rfilename": "README.md", "size": 2, "blobId": "git-blob"},
                ]
            )
            return {
                "sha": commit,
                "cardData": {
                    "base_model": "Qwen/Qwen3.5-9B",
                    "base_model_relation": "quantized",
                },
                "siblings": model_files,
            }

        with (
            patch.object(artifacts, "_REPO_SPECS", repo_specs),
            patch.object(artifacts, "_request_json", side_effect=get_json),
        ):
            catalog = artifacts.discover_catalog()

        exl = [
            item
            for item in catalog["artifacts"]
            if item["repo_id"] == "turboderp/Qwen3.5-9B-exl3"
        ]
        gguf = [
            item
            for item in catalog["artifacts"]
            if item["repo_id"] == "bartowski/Qwen_Qwen3.5-9B-GGUF"
        ]
        self.assertEqual(len(exl), 1)
        self.assertEqual(exl[0]["revision"], commit)
        self.assertEqual(exl[0]["revision_ref"], "2.50bpw")
        self.assertEqual(
            [item["path"] for item in exl[0]["files"]],
            [
                "config.json",
                "model.safetensors",
                "tokenizer.json",
                "tokenizer_config.json",
            ],
        )
        self.assertEqual(exl[0]["source_base"]["status"], "publisher_declared")
        self.assertEqual(
            [item["path"] for item in gguf[0]["files"]], ["Qwen-Q4_K_M.gguf"]
        )

    def test_exl3_catalog_hashes_pinned_config_and_tokenizer_git_blobs(self) -> None:
        commit = "c" * 40
        spec = (
            {
                "repo_id": "turboderp/Qwen3.5-9B-exl3",
                "model_id": "9B",
                "kind": "exl3",
                "engine": "exllamav3",
            },
        )
        content = {
            "config.json": b'{"model_type":"qwen3_5"}',
            "generation_config.json": b'{"temperature":0.6}',
            "tokenizer_config.json": b'{"add_bos_token":false}',
            "tokenizer.json": b'{"version":"1.0"}',
            "special_tokens_map.json": b'{"bos_token":"<s>"}',
            "added_tokens.json": b'{"<extra>":0}',
            "chat_template.jinja": b"{{ messages }}",
            "vocab.json": b'{"<unk>":0}',
            "merges.txt": b"#version: 0.2\n",
            "tokenizer.model": b"sentencepiece-model",
        }
        weight = b"exl3weights"
        siblings = [
            {
                "rfilename": "model.safetensors",
                "size": len(weight),
                "lfs": {"sha256": _sha(weight)},
            },
            *[
                {
                    "rfilename": path,
                    "size": len(value),
                    "blobId": hashlib.sha1(
                        b"blob " + str(len(value)).encode() + b"\0" + value
                    ).hexdigest(),
                }
                for path, value in content.items()
                if path != "tokenizer.model"
            ],
            {
                "rfilename": "tokenizer.model",
                "size": len(content["tokenizer.model"]),
                "lfs": {"sha256": _sha(content["tokenizer.model"])},
            },
            {"rfilename": "README.md", "size": 12, "blobId": "e" * 40},
        ]
        metadata_requests: list[str] = []

        def get_json(url: str) -> dict[str, object]:
            if url.endswith("/refs"):
                return {"branches": [{"name": "2.50bpw", "targetCommit": commit}]}
            return {
                "sha": commit,
                "cardData": {"base_model": "Qwen/Qwen3.5-9B"},
                "siblings": siblings,
            }

        def get_file(request: object, timeout: float) -> FakeResponse:
            url = request.full_url
            path = url.rsplit("/", 1)[-1]
            metadata_requests.append(url)
            return FakeResponse(
                content[path],
                status=200,
                headers={"Content-Length": str(len(content[path]))},
            )

        with (
            patch.object(artifacts, "_REPO_SPECS", spec),
            patch.object(artifacts, "_request_json", side_effect=get_json),
            patch.object(artifacts.urllib.request, "urlopen", side_effect=get_file),
        ):
            catalog = artifacts.discover_catalog()

        artifact = catalog["artifacts"][0]
        files = {entry["path"]: entry for entry in artifact["files"]}
        self.assertEqual(set(files), {"model.safetensors", *content})
        self.assertEqual(files["config.json"]["sha256"], _sha(content["config.json"]))
        self.assertNotEqual(files["config.json"]["sha256"], "d" * 40)
        self.assertEqual(files["config.json"]["sha256_source"], "resolved_content")
        self.assertEqual(files["tokenizer.model"]["sha256_source"], "lfs")
        self.assertTrue(all(f"/resolve/{commit}/" in url for url in metadata_requests))
        self.assertEqual(len(metadata_requests), len(content) - 1)
        self.assertEqual(catalog["warnings"], [])

    def test_refresh_updates_only_existing_pinned_exl3_records(self) -> None:
        commit = "f" * 40
        weight = b"weights"
        config = b'{"model_type":"qwen3_5"}'
        tokenizer_config = b'{"add_bos_token":false}'
        tokenizer = b'{"version":"1.0"}'
        old_exl = {
            "artifact_id": "old-exl3",
            "model_id": "9B",
            "repo_id": "turboderp/Qwen3.5-9B-exl3",
            "revision": commit,
            "revision_ref": "2.50bpw",
            "quantfmt": "EXL3-2.50BPW",
            "engine": "exllamav3",
            "source_base": {"status": "publisher_declared"},
            "files": [
                {
                    "path": "model.safetensors",
                    "size": len(weight),
                    "sha256": _sha(weight),
                }
            ],
            "total_bytes": len(weight),
        }
        unrelated = {
            "artifact_id": "untouched-gguf",
            "model_id": "9B",
            "repo_id": "bartowski/model",
            "revision": "a" * 40,
            "files": [{"path": "model.gguf", "size": 1, "sha256": "a" * 64}],
        }
        catalog = {
            "schema_version": 1,
            "generated_at": "2026-10-25T00:00:00Z",
            "source": {"weight_policy": "old"},
            "artifacts": [old_exl, unrelated],
            "repository_log": [
                {
                    "repo_id": "turboderp/Qwen3.5-9B-exl3",
                    "refs": [
                        {
                            "revision_ref": "2.50bpw",
                            "revision": commit,
                            "artifact_count": 1,
                        },
                    ],
                },
                {"repo_id": "bartowski/model", "status": "queried"},
            ],
            "warnings": [],
            "deduplication": {"unique_sha256_count": 2, "duplicate_sha256": []},
        }
        siblings = [
            {
                "rfilename": "model.safetensors",
                "size": len(weight),
                "lfs": {"sha256": _sha(weight)},
            },
            {
                "rfilename": "config.json",
                "size": len(config),
                "lfs": {"sha256": _sha(config)},
            },
            {
                "rfilename": "tokenizer_config.json",
                "size": len(tokenizer_config),
                "lfs": {"sha256": _sha(tokenizer_config)},
            },
            {
                "rfilename": "tokenizer.json",
                "size": len(tokenizer),
                "lfs": {"sha256": _sha(tokenizer)},
            },
        ]
        with patch.object(
            artifacts,
            "_request_json",
            return_value={
                "sha": commit,
                "cardData": {"base_model": "Qwen/Qwen3.5-9B"},
                "siblings": siblings,
            },
        ) as get_json:
            updated = artifacts.refresh_exl3_metadata(catalog)

        get_json.assert_called_once_with(
            "https://huggingface.co/api/models/turboderp/Qwen3.5-9B-exl3/revision/"
            + commit
            + "?blobs=true"
        )
        self.assertEqual(updated["generated_at"], catalog["generated_at"])
        self.assertEqual(updated["artifacts"][1], unrelated)
        self.assertEqual(catalog["artifacts"][0], old_exl)
        self.assertIn(
            "config.json", {entry["path"] for entry in updated["artifacts"][0]["files"]}
        )
        self.assertEqual(updated["exl3_metadata_refresh"]["revision_count"], 1)
        self.assertEqual(
            updated["repository_log"][0]["refs"][0]["metadata_file_count"], 3
        )
        self.assertEqual(updated["repository_log"][1], catalog["repository_log"][1])

    def test_save_catalog_writes_json_and_returns_destination(self) -> None:
        catalog = {"schema_version": 1, "artifacts": []}
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "reports" / "catalog.json"
            self.assertEqual(artifacts.save_catalog(destination, catalog), destination)
            self.assertEqual(
                json.loads(destination.read_text(encoding="utf-8")), catalog
            )


class QwenArtifactDownloaderTests(unittest.TestCase):
    def setUp(self) -> None:
        disk_usage = namedtuple("DiskUsage", "total used free")
        self.disk_usage = patch.object(
            artifacts.shutil, "disk_usage", return_value=disk_usage(10**12, 0, 10**12)
        )
        self.disk_usage.start()
        self.addCleanup(self.disk_usage.stop)

    def test_resumes_only_valid_206_and_returns_single_file(self) -> None:
        content = b"abcdefghij"
        artifact = _artifact(content)
        observed_range: list[str | None] = []

        def open_url(request: object, timeout: float) -> FakeResponse:
            observed_range.append(request.get_header("Range"))
            return FakeResponse(
                content[4:],
                status=206,
                headers={
                    "Content-Range": f"bytes 4-9/{len(content)}",
                    "Content-Length": "6",
                },
            )

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            partial = root / ".objects" / f"{_sha(content)}.part"
            partial.parent.mkdir()
            partial.write_bytes(content[:4])
            with patch.object(
                artifacts.urllib.request, "urlopen", side_effect=open_url
            ):
                result = artifacts.ensure_artifact(artifact, root)

            self.assertEqual(observed_range, ["bytes=4-"])
            self.assertEqual(result.read_bytes(), content)
            self.assertEqual(result.name, "model.gguf")

    def test_single_shard_exl3_always_returns_folder_with_config_and_tokenizer(
        self,
    ) -> None:
        files = {
            "model.safetensors": b"weights",
            "config.json": b'{"model_type":"qwen3_5"}',
            "tokenizer.json": b'{"version":"1.0"}',
        }
        artifact = _artifact(files["model.safetensors"], path="model.safetensors")
        artifact.update(engine="exllamav3", quantfmt="EXL3-2.50BPW")
        artifact["files"] = [
            {"path": path, "size": len(content), "sha256": _sha(content)}
            for path, content in files.items()
        ]
        artifact["total_bytes"] = sum(len(content) for content in files.values())

        def open_url(request: object, timeout: float) -> FakeResponse:
            path = request.full_url.rsplit("/", 1)[-1]
            content = files[path]
            return FakeResponse(
                content, status=200, headers={"Content-Length": str(len(content))}
            )

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch.object(
                artifacts.urllib.request, "urlopen", side_effect=open_url
            ):
                result = artifacts.ensure_artifact(artifact, root)
            self.assertEqual(result, root / artifact["artifact_id"])
            self.assertTrue(result.is_dir())
            self.assertEqual({path.name for path in result.iterdir()}, set(files))
            self.assertEqual(
                {path.name: path.read_bytes() for path in result.iterdir()}, files
            )

    def test_exl3_with_one_file_still_returns_artifact_folder(self) -> None:
        content = b"single-exl3-shard"
        artifact = _artifact(content, path="model.safetensors")
        artifact.update(engine="exllamav3", quantfmt="EXL3-2.50BPW")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch.object(
                artifacts.urllib.request,
                "urlopen",
                return_value=FakeResponse(
                    content, status=200, headers={"Content-Length": str(len(content))}
                ),
            ) as open_url:
                result = artifacts.ensure_artifact(artifact, root)
                cached_result = artifacts.ensure_artifact(artifact, root)
            self.assertEqual(result, root / artifact["artifact_id"])
            self.assertEqual(cached_result, result)
            self.assertTrue(result.is_dir())
            self.assertEqual((result / "model.safetensors").read_bytes(), content)
            self.assertEqual(open_url.call_count, 1)

    def test_server_ignoring_range_replaces_partial_instead_of_appending(self) -> None:
        content = b"complete-object"
        artifact = _artifact(content)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            partial = root / ".objects" / f"{_sha(content)}.part"
            partial.parent.mkdir()
            partial.write_bytes(b"stale-prefix")
            with patch.object(
                artifacts.urllib.request,
                "urlopen",
                return_value=FakeResponse(
                    content, status=200, headers={"Content-Length": str(len(content))}
                ),
            ):
                result = artifacts.ensure_artifact(artifact, root)
            self.assertEqual(result.read_bytes(), content)

    def test_invalid_content_range_does_not_append_or_replace_partial(self) -> None:
        content = b"abcdefghij"
        artifact = _artifact(content)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            partial = root / ".objects" / f"{_sha(content)}.part"
            partial.parent.mkdir()
            partial.write_bytes(content[:4])
            with (
                patch.object(
                    artifacts.urllib.request,
                    "urlopen",
                    return_value=FakeResponse(
                        content[4:],
                        status=206,
                        headers={
                            "Content-Range": "bytes 3-9/10",
                            "Content-Length": "7",
                        },
                    ),
                ),
                self.assertRaises(artifacts.ArtifactError),
            ):
                artifacts.ensure_artifact(artifact, root)
            self.assertEqual(partial.read_bytes(), content[:4])

    def test_rejects_traversal_before_network_access(self) -> None:
        artifact = _artifact(b"safe", path="../escape.gguf")
        with tempfile.TemporaryDirectory() as temporary:
            with patch.object(artifacts.urllib.request, "urlopen") as open_url:
                with self.assertRaises(artifacts.ArtifactError):
                    artifacts.ensure_artifact(artifact, temporary)
            open_url.assert_not_called()

    def test_cache_limit_stops_before_download_and_keeps_existing_files(self) -> None:
        content = b"large"
        artifact = _artifact(content)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            existing = root / "user-model.bin"
            existing.write_bytes(b"preserve")
            with patch.object(artifacts.urllib.request, "urlopen") as open_url:
                with self.assertRaises(artifacts.ArtifactError):
                    artifacts.ensure_artifact(artifact, root, max_cache_bytes=1)
            open_url.assert_not_called()
            self.assertEqual(existing.read_bytes(), b"preserve")

    def test_duplicate_hashes_download_once_and_return_a_folder_for_shards(
        self,
    ) -> None:
        content = b"shared-shard"
        artifact = _artifact(content)
        artifact["files"] = [
            {
                "path": "model-00001.safetensors",
                "size": len(content),
                "sha256": _sha(content),
            },
            {
                "path": "model-00002.safetensors",
                "size": len(content),
                "sha256": _sha(content),
            },
        ]
        artifact["total_bytes"] = len(content) * 2
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch.object(
                artifacts.urllib.request,
                "urlopen",
                return_value=FakeResponse(
                    content, status=200, headers={"Content-Length": str(len(content))}
                ),
            ) as open_url:
                result = artifacts.ensure_artifact(artifact, root)
            self.assertEqual(result, root / artifact["artifact_id"])
            self.assertEqual((result / "model-00001.safetensors").read_bytes(), content)
            self.assertEqual((result / "model-00002.safetensors").read_bytes(), content)
            self.assertEqual(open_url.call_count, 1)
            self.assertEqual(
                (result / "model-00001.safetensors").stat().st_ino,
                (result / "model-00002.safetensors").stat().st_ino,
            )

    def test_corrupt_existing_destination_is_preserved_without_network_access(
        self,
    ) -> None:
        content = b"expected"
        artifact = _artifact(content)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            destination = root / artifact["artifact_id"] / "model.gguf"
            destination.parent.mkdir()
            destination.write_bytes(b"existing-user-data")
            with patch.object(artifacts.urllib.request, "urlopen") as open_url:
                with self.assertRaises(artifacts.ArtifactError):
                    artifacts.ensure_artifact(artifact, root)
            open_url.assert_not_called()
            self.assertEqual(destination.read_bytes(), b"existing-user-data")

    def test_cli_writes_catalog_and_jsonl_discovery_log(self) -> None:
        catalog = {
            "generated_at": "2026-10-25T00:00:00Z",
            "artifacts": [],
            "repository_log": [{"repo_id": "Qwen/Qwen3.5-9B", "status": "queried"}],
            "warnings": ["one warning"],
            "deduplication": {"unique_sha256_count": 0},
        }
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "artifact-catalog.json"
            with patch.object(artifacts, "discover_catalog", return_value=catalog):
                self.assertEqual(
                    artifacts.main(["--discover", "--output", str(output)]), 0
                )
            log = output.with_name("discovery-log.jsonl")
            events = [
                json.loads(line)["event"]
                for line in log.read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual(events, ["repository", "warning"])

    def test_reuses_valid_existing_destination_without_downloading(self) -> None:
        content = b"already-present"
        artifact = _artifact(content)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            destination = root / artifact["artifact_id"] / "model.gguf"
            destination.parent.mkdir()
            destination.write_bytes(content)
            with patch.object(artifacts.urllib.request, "urlopen") as open_url:
                result = artifacts.ensure_artifact(artifact, root)
            self.assertEqual(result, destination)
            open_url.assert_not_called()


if __name__ == "__main__":
    unittest.main()
