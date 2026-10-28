"""Resolve and install a side-by-side harness matrix; never runs model inference."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import tarfile
import time
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
LAB = Path("/home/foxtrot/local-llm-benchmark")
BASE = LAB / "envs/qwen-harness-refresh-20261025"
REPORT = ROOT / "results/reports/qwen-harness-refresh-20261025"
CONFIG = ROOT / "benchmark/configs/qwen-harness-matrix-v1.json"
FLOOR = 8 * 1024**3


def atomic(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False))
    temporary.replace(path)


def get_json(url):
    for attempt in range(3):
        try:
            with urlopen(
                Request(url, headers={"User-Agent": "LocalLLMLab-harness-refresh/1"}),
                timeout=40,
            ) as response:
                return json.load(response)
        except HTTPError:
            raise
        except (OSError, ValueError):
            if attempt == 2:
                raise
            time.sleep(2)


def disk_guard(path=LAB):
    if shutil.disk_usage(path).free < FLOOR:
        raise RuntimeError("WSL free disk is below the fixed 8 GiB floor")


def compatible_python_minors(requires_python, versions):
    from pip._vendor.packaging.specifiers import SpecifierSet
    from pip._vendor.packaging.version import Version

    specifier = SpecifierSet(requires_python or "")
    return [
        minor
        for minor, version in versions.items()
        if not specifier or specifier.contains(Version(version), prereleases=True)
    ]


def mark_interrupted(state, name, logs):
    entry = state.get("items", {}).get(name)
    if not entry or entry.get("status") != "installing":
        return False
    event = {
        "id": name,
        "previous_status": "installing",
        "logs": [str(path) for path in logs],
    }
    state.setdefault("interruptions", []).append(event)
    entry["status"] = "interrupted"
    entry["interrupted_logs"] = event["logs"]
    return True


def item_matches_install(item, entry, python_candidates=None):
    if entry.get("status") not in {"installed", "staged"}:
        return False
    root = Path(entry.get("root", ""))
    if not root.is_dir():
        return False
    if item["kind"] == "npm":
        manifest = root / "node_modules" / item["package"] / "package.json"
        try:
            package = json.loads(manifest.read_text())
        except (OSError, ValueError):
            return False
        executables = entry.get("executables", [])
        return (
            package.get("name") == item["package"]
            and package.get("version") == item.get("version")
            and all(Path(path).exists() for path in executables)
        )
    if item["kind"] == "pypi":
        if python_candidates is not None and entry.get("python") not in python_candidates:
            return False
        python = root / "bin/python"
        if not python.is_file():
            return False
        version = subprocess.run(
            [str(python), "--version"],
            env=clean_env(BASE / "homes/resume-check"),
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        version_text = version.stdout or version.stderr
        if version.returncode or not version_text.strip().startswith(
            "Python " + str(entry.get("python")) + "."
        ):
            return False
        check = subprocess.run(
            [
                str(python),
                "-c",
                "import importlib.metadata,sys; print(importlib.metadata.version(sys.argv[1]))",
                item["package"],
            ],
            env=clean_env(BASE / "homes/resume-check"),
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        return check.returncode == 0 and check.stdout.strip() == item.get("version")
    pin = (item.get("source") or {}).get("commit")
    if not pin or not (root / ".git").exists():
        return False
    check = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    return check.returncode == 0 and check.stdout.strip() == pin


def source_pin(url):
    repo = url.removeprefix("https://github.com/").removesuffix(".git")
    data = get_json("https://api.github.com/repos/" + repo)
    branch = data["default_branch"]
    try:
        release = get_json("https://api.github.com/repos/" + repo + "/releases/latest")
        ref = release["tag_name"]
        channel = "stable-release"
    except HTTPError as exc:
        if exc.code != 404:
            raise
        release = {}
        ref = branch
        channel = "upstream-default-branch-no-stable-release"
    commits = get_json(
        "https://api.github.com/repos/"
        + repo
        + "/commits?per_page=1&sha="
        + quote(ref, safe="")
    )
    return {
        "repository": data["html_url"],
        "ref": ref,
        "commit": commits[0]["sha"],
        "channel": channel,
        "release_url": release.get("html_url"),
    }


def resolve_item(item):
    out = dict(item)
    if item["kind"] == "npm":
        meta = get_json(
            "https://registry.npmjs.org/" + quote(item["package"], safe="") + "/latest"
        )
        if meta.get("name") != item["package"]:
            raise ValueError("npm package identity mismatch")
        out.update(
            version=meta["version"],
            engines=meta.get("engines"),
            bin=meta.get("bin"),
            integrity=meta["dist"].get("integrity"),
            tarball=meta["dist"]["tarball"],
            package_repository=meta.get("repository"),
            registry="https://registry.npmjs.org",
        )
    elif item["kind"] == "pypi":
        meta = get_json(
            "https://pypi.org/pypi/" + quote(item["package"], safe="") + "/json"
        )
        info = meta["info"]
        out.update(
            version=info["version"],
            requires_python=info.get("requires_python"),
            extras=info.get("provides_extra") or [],
            project_urls=info.get("project_urls"),
            requires_dist=info.get("requires_dist"),
            registry="https://pypi.org/simple",
        )
    else:
        out.update(source=source_pin(item["upstream"]))
    return out


def resolve():
    config = json.loads(CONFIG.read_text())
    result = {
        "date_reference": "2026-10-25",
        "inference": False,
        "base": str(BASE),
        "harnesses": [],
        "plugins": [],
        "resolution_errors": [],
    }
    for group in ("harnesses", "plugins"):
        for item in config[group]:
            try:
                resolved = resolve_item(item)
                result[group].append(resolved)
                print(
                    "resolved",
                    item["id"],
                    resolved.get("version") or resolved.get("source"),
                    flush=True,
                )
            except Exception as exc:
                result["resolution_errors"].append(
                    {"id": item["id"], "error": f"{type(exc).__name__}: {exc}"}
                )
    releases = get_json("https://nodejs.org/dist/index.json")
    lts = next(
        r for r in releases if r.get("lts") and "linux-x64" in r.get("files", [])
    )
    result["node"] = {k: lts.get(k) for k in ("version", "date", "lts", "npm")}
    try:
        release = get_json(
            "https://api.github.com/repos/ggml-org/llama.cpp/releases/latest"
        )
        result["llama_release"] = {
            "tag": release["tag_name"],
            "url": release["html_url"],
            "assets": [
                {
                    "name": a["name"],
                    "url": a["browser_download_url"],
                    "size": a["size"],
                    "digest": a.get("digest"),
                }
                for a in release["assets"]
            ],
        }
    except Exception as exc:
        result["resolution_errors"].append({"id": "llama.cpp", "error": str(exc)})
    atomic(REPORT / "discovery.json", result)
    return result


def clean_env(home, node=None):
    home.mkdir(parents=True, exist_ok=True)
    env = {
        "HOME": str(home),
        "PATH": (str(node / "bin") + ":" if node else "") + "/usr/bin:/bin",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PYTHONDONTWRITEBYTECODE": "1",
        "XDG_CONFIG_HOME": str(home / "config"),
        "XDG_CACHE_HOME": str(home / "cache"),
        "XDG_DATA_HOME": str(home / "data"),
        "UV_CACHE_DIR": str(BASE / "cache/uv"),
        "UV_PYTHON_INSTALL_DIR": str(BASE / "runtimes/python"),
        "UV_NO_CONFIG": "1",
        "PIP_DISABLE_PIP_VERSION_CHECK": "1",
        "DO_NOT_TRACK": "1",
        "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
        "OPENCODE_DISABLE_AUTOUPDATE": "1",
        "HEADROOM_OFFLINE": "1",
        "HEADROOM_BEACON": "off",
        "HEADROOM_TELEMETRY": "off",
        "LITELLM_LOCAL_MODEL_COST_MAP": "True",
        "CREWAI_DISABLE_TELEMETRY": "true",
        "NPM_CONFIG_USERCONFIG": str(home / "empty-npmrc"),
    }
    (home / "empty-npmrc").touch(exist_ok=True)
    return env


def run(name, args, *, env, timeout=1200, cwd=BASE, check=True):
    disk_guard()
    REPORT.mkdir(parents=True, exist_ok=True)
    log = REPORT / "logs" / (name + "-" + str(time.time_ns()) + ".log")
    log.parent.mkdir(exist_ok=True)
    started = time.monotonic()
    with log.open("w") as stream:
        process = subprocess.Popen(
            [str(a) for a in args],
            cwd=cwd,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=stream,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        try:
            deadline = started + timeout
            while process.poll() is None:
                disk_guard()
                if time.monotonic() >= deadline:
                    raise subprocess.TimeoutExpired(args, timeout)
                time.sleep(2)
            code = process.returncode
        except BaseException:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
            raise
    event = {
        "name": name,
        "argv": [str(a) for a in args],
        "returncode": code,
        "seconds": round(time.monotonic() - started, 2),
        "log": str(log),
    }
    print(json.dumps(event), flush=True)
    if check and code:
        raise RuntimeError(f"{name} failed ({code}); see {log}")
    return event


def download(url, path, maximum=1024**3):
    disk_guard()
    path.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    with (
        urlopen(
            Request(url, headers={"User-Agent": "LocalLLMLab-harness-refresh/1"}),
            timeout=90,
        ) as source,
        path.open("wb") as target,
    ):
        total = 0
        while data := source.read(1024**2):
            total += len(data)
            if total > maximum:
                raise ValueError("download exceeds preparation bound")
            disk_guard()
            target.write(data)
            digest.update(data)
    return digest.hexdigest()


def safe_extract(archive, target):
    target = target.resolve()
    with tarfile.open(archive) as tar:
        for item in tar.getmembers():
            destination = (target / item.name).resolve()
            if not destination.is_relative_to(target):
                raise ValueError("archive escapes runtime root")
        tar.extractall(target, filter="data")


def install_node(snapshot, existing=None):
    version = snapshot["node"]["version"]
    if not re.fullmatch(r"v\d+\.\d+\.\d+", version):
        raise ValueError("invalid Node release")
    name = "node-" + version + "-linux-x64.tar.xz"
    node = BASE / "runtimes" / name.removesuffix(".tar.xz")
    executable = node / "bin/node"
    if executable.is_file():
        installed = subprocess.run(
            [str(executable), "--version"], capture_output=True, text=True, timeout=15
        )
        if installed.returncode == 0 and installed.stdout.strip() == version:
            meta = dict(existing or {})
            meta.update(version=version, root=str(node), reused_existing=True)
            return node, meta
    base = "https://nodejs.org/dist/" + version + "/"
    with urlopen(base + "SHASUMS256.txt", timeout=40) as response:
        sums = dict(
            line.split(maxsplit=1)[::-1]
            for line in response.read().decode().splitlines()
            if line.strip()
        )
    expected = sums[name]
    archive = BASE / "downloads" / name
    digest = download(base + name, archive)
    if digest != expected:
        raise ValueError("Node SHA-256 mismatch")
    target = BASE / "runtimes"
    target.mkdir(parents=True, exist_ok=True)
    safe_extract(archive, target)
    node = target / name.removesuffix(".tar.xz")
    return node, {"version": version, "sha256": digest, "root": str(node)}


def install(snapshot):
    BASE.mkdir(parents=True, exist_ok=True)
    state_path = REPORT / "installation.json"
    state = json.loads(state_path.read_text()) if state_path.exists() else {
        "base": str(BASE), "inference": False, "items": {}, "runtime": {},
        "status": "installing",
    }
    if state.get("base") != str(BASE):
        raise RuntimeError("installation state belongs to a different runtime root")
    state.setdefault("items", {})
    state.setdefault("runtime", {})
    state.setdefault("inference", False)
    state["status"] = "installing"
    atomic(REPORT / "installation.json", state)
    node, meta = install_node(snapshot, state["runtime"].get("node"))
    state["runtime"]["node"] = meta
    atomic(REPORT / "installation.json", state)
    env = clean_env(BASE / "bootstrap-home", node)
    boot = BASE / "bootstrap"
    if not (boot / "bin/python").exists():
        run("bootstrap-venv", [sys.executable, "-m", "venv", boot], env=env)
    uv = boot / "bin/uv"
    if not uv.is_file():
        run(
            "bootstrap-pip-uv",
            [
                boot / "bin/python",
                "-m",
                "pip",
                "install",
                "--upgrade",
                "pip",
                "uv",
                "--index-url",
                "https://pypi.org/simple",
            ],
            env=env,
        )
    interpreters = dict(state["runtime"].get("python", {}))
    for minor in ("3.14", "3.13", "3.12"):
        path = Path(interpreters[minor]) if minor in interpreters else None
        if path is None or not path.is_file():
            found = sorted(
                (BASE / "runtimes/python").glob(
                    "cpython-" + minor + ".*-linux-x86_64-gnu/bin/python" + minor
                )
            )
            path = found[-1] if found else None
        if path is not None:
            version = subprocess.run(
                [str(path), "--version"], capture_output=True, text=True, timeout=15
            )
            version_text = version.stdout or version.stderr
            if version.returncode or not version_text.strip().startswith("Python " + minor + "."):
                path = None
        if path is None:
            run(
                "python-" + minor,
                [uv, "python", "install", "--install-dir", BASE / "runtimes/python", minor],
                env=env,
            )
            found = sorted(
                (BASE / "runtimes/python").glob(
                    "cpython-" + minor + ".*-linux-x86_64-gnu/bin/python" + minor
                )
            )
            if not found:
                raise RuntimeError("managed Python missing " + minor)
            path = found[-1]
        interpreters[minor] = str(path)
        state["runtime"]["python"] = interpreters
        atomic(REPORT / "installation.json", state)
    python_versions = {
        minor: subprocess.check_output([path, "--version"], env=env, text=True).strip().split()[-1]
        for minor, path in interpreters.items()
    }
    for item in snapshot["harnesses"] + snapshot["plugins"]:
        name = item["id"]
        entry = state["items"].get(name)
        candidates = (
            compatible_python_minors(item.get("requires_python"), python_versions)
            if item["kind"] == "pypi"
            else None
        )
        if entry and item_matches_install(item, entry, candidates):
            if item["kind"] == "pypi":
                entry["requires_python"] = item.get("requires_python")
                entry["compatible_python"] = candidates
                atomic(REPORT / "installation.json", state)
            print("reused", name, entry.get("version") or entry.get("source"), flush=True)
            continue
        if entry and entry.get("status") == "installing":
            old_logs = sorted((REPORT / "logs").glob(name + "-*"))
            mark_interrupted(state, name, old_logs)
        if entry is None:
            entry = {}
            state["items"][name] = entry
        entry.update(
            kind=item["kind"],
            version=item.get("version"),
            source=item.get("source"),
            status="installing",
        )
        atomic(REPORT / "installation.json", state)
        prefix = BASE / "packages" / name
        home = BASE / "homes" / name
        itemenv = clean_env(home, node)
        try:
            if item["kind"] == "npm":
                prefix.mkdir(parents=True, exist_ok=True)
                run(
                    name + "-install",
                    [
                        node / "bin/npm",
                        "install",
                        "--prefix",
                        prefix,
                        "--save-exact",
                        "--no-fund",
                        "--no-audit",
                        "--registry",
                        "https://registry.npmjs.org",
                        item["package"] + "@" + item["version"],
                    ],
                    env=itemenv,
                    timeout=1800,
                )
                bins = prefix / "node_modules/.bin"
                entry.update(
                    status="installed",
                    root=str(prefix),
                    executables=[str(p) for p in bins.iterdir()]
                    if bins.exists()
                    else [],
                )
                atomic(REPORT / "installation.json", state)
                entry["audit"] = run(
                    name + "-audit",
                    [
                        node / "bin/npm",
                        "audit",
                        "--prefix",
                        prefix,
                        "--json",
                        "--registry",
                        "https://registry.npmjs.org",
                    ],
                    env=itemenv,
                    timeout=180,
                    check=False,
                )
                atomic(REPORT / "installation.json", state)
            elif item["kind"] == "pypi":
                candidates = candidates or []
                entry["requires_python"] = item.get("requires_python")
                entry["compatible_python"] = candidates
                if not candidates:
                    raise RuntimeError(
                        "no managed Python satisfies requires_python="
                        + str(item.get("requires_python"))
                    )
                attempts = entry.setdefault("attempts", [])
                for minor in candidates:
                    venv = prefix / ("python-" + minor)
                    if not (venv / "bin/python").is_file():
                        run(
                            name + "-venv-" + minor,
                            [uv, "venv", "--python", interpreters[minor], venv],
                            env=itemenv,
                        )
                    extra = ""
                    if name == "headroom":
                        supported = set(item.get("extras", []))
                        chosen = [x for x in ("proxy", "mcp") if x in supported]
                        extra = "[" + ",".join(chosen) + "]" if chosen else ""
                    package = item["package"] + extra + "==" + item["version"]
                    installed = run(
                        name + "-install-" + minor,
                        [
                            uv,
                            "pip",
                            "install",
                            "--python",
                            venv / "bin/python",
                            "--index-url",
                            "https://pypi.org/simple",
                            "--upgrade",
                            "pip",
                            package,
                        ],
                        env=itemenv,
                        timeout=1800,
                        check=False,
                    )
                    attempts.append(installed)
                    atomic(REPORT / "installation.json", state)
                    if installed["returncode"] == 0:
                        checked = run(
                            name + "-check",
                            [venv / "bin/python", "-m", "pip", "check"],
                            env=itemenv,
                        )
                        frozen = run(
                            name + "-freeze",
                            [venv / "bin/python", "-m", "pip", "freeze", "--all"],
                            env=itemenv,
                        )
                        entry.update(
                            status="installed",
                            root=str(venv),
                            python=minor,
                            extras=extra,
                            dependency_check=checked,
                            dependency_freeze=frozen,
                        )
                        atomic(REPORT / "installation.json", state)
                        break
                else:
                    raise RuntimeError(
                        "all compatible Python dependency installations failed"
                    )
            else:
                pin = item["source"]
                source = BASE / "sources" / name
                if name == "hermes":
                    installer = BASE / "downloads/hermes-install.sh"
                    entry["installer_sha256"] = download(
                        "https://raw.githubusercontent.com/NousResearch/hermes-agent/"
                        + pin["commit"]
                        + "/scripts/install.sh",
                        installer,
                        4 * 1024**2,
                    )
                    itemenv["HERMES_HOME"] = str(home / "hermes-data")
                    run(
                        name + "-install",
                        [
                            "bash",
                            installer,
                            "--commit",
                            pin["commit"],
                            "--dir",
                            source,
                            "--hermes-home",
                            home / "hermes-data",
                            "--non-interactive",
                            "--skip-browser",
                            "--skip-computer-use",
                        ],
                        env=itemenv,
                        timeout=2400,
                    )
                    entry.update(
                        status="installed",
                        root=str(source),
                        home=str(home),
                        note="Official PM installer, browser/desktop/computer-use optional payloads excluded",
                    )
                else:
                    if not source.exists():
                        run(
                            name + "-clone",
                            [
                                "git",
                                "clone",
                                "--depth",
                                "1",
                                "--branch",
                                pin["ref"],
                                pin["repository"],
                                source,
                            ],
                            env=itemenv,
                        )
                    else:
                        existing_commit = subprocess.run(
                            ["git", "-C", str(source), "rev-parse", "HEAD"],
                            capture_output=True,
                            text=True,
                            timeout=30,
                            check=False,
                        )
                        if existing_commit.returncode or existing_commit.stdout.strip() != pin["commit"]:
                            raise RuntimeError("existing source directory is not the requested pin")
                    lock = source / "package-lock.json"
                    if (source / "package.json").exists():
                        run(
                            name + "-dependencies",
                            [
                                node / "bin/npm",
                                "install",
                                "--omit=dev",
                                "--no-fund",
                                "--no-audit",
                            ],
                            cwd=source,
                            env=itemenv,
                        )
                    entry.update(
                        status="staged",
                        root=str(source),
                        lockfile=str(lock) if lock.exists() else None,
                    )
            atomic(REPORT / "installation.json", state)
        except Exception as exc:
            entry.update(status="blocked", error=f"{type(exc).__name__}: {exc}")
        atomic(REPORT / "installation.json", state)
    state["status"] = (
        "installed_with_blocks"
        if any(x["status"] == "blocked" for x in state["items"].values())
        else "installed"
    )
    atomic(REPORT / "installation.json", state)
    print(
        json.dumps(
            {
                "status": state["status"],
                "items": {k: v["status"] for k, v in state["items"].items()},
            },
            indent=2,
        )
    )
    return state


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--install", action="store_true")
    args = parser.parse_args()
    REPORT.mkdir(parents=True, exist_ok=True)
    discovery = REPORT / "discovery.json"
    snapshot = (
        json.loads(discovery.read_text())
        if args.install and discovery.exists()
        else resolve()
    )
    if args.install:
        if sys.platform != "linux":
            raise RuntimeError("installation must run inside WSL/Linux")
        import fcntl

        BASE.mkdir(parents=True, exist_ok=True)
        with (BASE / "refresh.lock").open("a") as ownership:
            fcntl.flock(ownership, fcntl.LOCK_EX | fcntl.LOCK_NB)
            install(snapshot)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
