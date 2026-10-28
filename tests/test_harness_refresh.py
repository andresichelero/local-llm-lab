"""Offline safety checks for the authorized side-by-side update workflow."""

import importlib.util
import io
import os
from pathlib import Path
import tarfile
from types import SimpleNamespace

import pytest

spec = importlib.util.spec_from_file_location(
    "harness_refresh", Path(__file__).parents[1] / "scripts/refresh_qwen_harnesses.py"
)
refresh = importlib.util.module_from_spec(spec)
spec.loader.exec_module(refresh)

qualification_spec = importlib.util.spec_from_file_location(
    "harness_qualification",
    Path(__file__).parents[1] / "scripts/qualify_qwen_harness_refresh.py",
)
qualification = importlib.util.module_from_spec(qualification_spec)
qualification_spec.loader.exec_module(qualification)


def archive(path, name):
    with tarfile.open(path, "w") as tar:
        entry = tarfile.TarInfo(name)
        entry.size = 2
        tar.addfile(entry, io.BytesIO(b"ok"))


def test_archive_cannot_escape_new_runtime_root(tmp_path):
    path = tmp_path / "bad.tar"
    archive(path, "../escaped")
    target = tmp_path / "runtime"
    target.mkdir()
    with pytest.raises(ValueError, match="escapes"):
        refresh.safe_extract(path, target)
    assert not (tmp_path / "escaped").exists()


def test_archive_extracts_valid_runtime_without_crossing_root(tmp_path):
    path = tmp_path / "valid.tar"
    archive(path, "node/bin/notice")
    target = tmp_path / "runtime"
    target.mkdir()
    refresh.safe_extract(path, target)
    assert (target / "node/bin/notice").read_bytes() == b"ok"


def test_low_disk_blocks_installation_before_mutation(monkeypatch, tmp_path):
    monkeypatch.setattr(
        refresh.shutil, "disk_usage", lambda p: SimpleNamespace(free=refresh.FLOOR - 1)
    )
    with pytest.raises(RuntimeError, match="8 GiB"):
        refresh.disk_guard(tmp_path)


def test_registry_package_identity_must_match_requested_official_name(monkeypatch):
    monkeypatch.setattr(refresh, "get_json", lambda url: {"name": "unrelated-package"})
    with pytest.raises(ValueError, match="identity mismatch"):
        refresh.resolve_item({"id": "codex", "kind": "npm", "package": "@openai/codex"})


def test_harness_environment_does_not_inherit_user_credentials(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENAI_API_KEY", "do-not-inherit")
    env = refresh.clean_env(tmp_path / "isolated")
    assert "OPENAI_API_KEY" not in env
    assert env["HOME"] == str(tmp_path / "isolated")
    assert env["HEADROOM_OFFLINE"] == "1"


def test_python_candidates_respect_discovered_requires_python():
    versions = {
        "3.14": "3.14.9",
        "3.13": "3.13.17",
        "3.12": "3.12.15",
    }

    assert refresh.compatible_python_minors("<3.13,>=3.10", versions) == ["3.12"]
    assert refresh.compatible_python_minors("==3.12.*", versions) == ["3.12"]
    assert refresh.compatible_python_minors(">=3.12", versions) == [
        "3.14",
        "3.13",
        "3.12",
    ]


def test_resume_records_interrupted_item_and_preserves_completed_items(tmp_path):
    log = tmp_path / "aider-install.log"
    log.write_text("preserve this failure evidence")
    pi = {"status": "installed", "root": "/packages/pi"}
    aider = {"status": "installing", "root": "/packages/aider"}
    state = {"items": {"pi": pi, "aider": aider}}

    refresh.mark_interrupted(state, "aider", [log])

    assert state["items"]["pi"] is pi
    assert aider["status"] == "interrupted"
    assert state["interruptions"] == [
        {
            "id": "aider",
            "previous_status": "installing",
            "logs": [str(log)],
        }
    ]
    assert log.read_text() == "preserve this failure evidence"


def test_resume_reuses_only_the_exact_installed_package_version(tmp_path):
    package = tmp_path / "pi" / "node_modules" / "@example" / "pi"
    package.mkdir(parents=True)
    manifest = package / "package.json"
    manifest.write_text('{"name":"@example/pi","version":"1.2.3"}')
    executable = tmp_path / "pi" / "node_modules" / ".bin" / "pi"
    executable.parent.mkdir()
    executable.write_text("cli")
    item = {"id": "pi", "kind": "npm", "package": "@example/pi", "version": "1.2.3"}
    entry = {
        "status": "installed",
        "root": str(tmp_path / "pi"),
        "executables": [str(executable)],
    }

    assert refresh.item_matches_install(item, entry)

    executable.unlink()
    assert not refresh.item_matches_install(item, entry)

    executable.write_text("cli")
    manifest.write_text('{"name":"@example/pi","version":"1.2.2"}')
    assert not refresh.item_matches_install(item, entry)


def test_resume_rejects_python_install_outside_compatible_candidates(tmp_path):
    root = tmp_path / "aider" / "python-3.14"
    (root / "bin").mkdir(parents=True)
    (root / "bin" / "python").write_text("python")
    item = {
        "id": "aider",
        "kind": "pypi",
        "package": "aider-chat",
        "version": "0.86.2",
    }
    entry = {
        "status": "installed",
        "root": str(root),
        "python": "3.14",
    }

    assert not refresh.item_matches_install(item, entry, python_candidates=["3.12"])


def test_audit_summary_retains_direct_package_and_fix_details():
    audit = {
        "metadata": {"vulnerabilities": {"high": 1, "critical": 0, "total": 1}},
        "vulnerabilities": {
            "direct-package": {
                "severity": "high",
                "isDirect": True,
                "range": "<2.0.0",
                "fixAvailable": False,
                "via": [{"name": "nested-package", "title": "Example advisory"}],
            },
            "nested-package": {
                "severity": "high",
                "isDirect": False,
                "range": "<2.0.0",
                "fixAvailable": False,
                "via": [{"name": "nested-package", "title": "Example advisory"}],
            },
        },
    }

    assert qualification.audit_summary(audit) == {
        "counts": {"high": 1, "critical": 0, "total": 1},
        "vulnerable_packages": 2,
        "direct": [
            {
                "package": "direct-package",
                "severity": "high",
                "range": "<2.0.0",
                "fix_available": False,
                "via": [{"name": "nested-package", "title": "Example advisory"}],
            }
        ],
    }


def test_hermes_qualification_uses_only_its_isolated_runtime_tools(tmp_path):
    data_home = tmp_path / "hermes-data"
    tool_bins = [
        data_home / "tools" / "python-3.14" / "bin",
        data_home / "tools" / "uv-0.13" / "bin",
        data_home / "tools" / "node-26" / "bin",
    ]
    for path in tool_bins:
        path.mkdir(parents=True)
    (data_home / "tools" / "documentation").mkdir(parents=True)
    env = {"PATH": "/usr/bin:/bin"}

    qualification.add_hermes_tools_to_path(env, data_home)

    assert env["PATH"].split(os.pathsep) == [
        str(tool_bins[2]),
        str(tool_bins[0]),
        str(tool_bins[1]),
        "/usr/bin",
        "/bin",
    ]
