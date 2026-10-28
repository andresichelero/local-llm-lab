"""Install an isolated, pinned EXL3/TabbyAPI runtime. Never loads a model."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import signal
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
LAB = Path("/home/foxtrot/local-llm-benchmark")
BASE = LAB / "envs/qwen-engines-20261025"
REPORT = ROOT / "results/reports/qwen-optimization-20261025/engines.json"


def fetch(url):
    with urllib.request.urlopen(
        urllib.request.Request(url, headers={"User-Agent": "LocalLLMLab/1"}), timeout=45
    ) as stream:
        return json.load(stream)


def main():
    from benchmark.qwen_optimization import write_json

    BASE.mkdir(parents=True, exist_ok=True)
    state = {"status": "preparing", "inference": False, "base": str(BASE)}
    env = {
        "PATH": "/usr/bin:/bin",
        "HOME": str(BASE / "home"),
        "UV_CACHE_DIR": "/mnt/d/Usuario/Downloads/LLM/qwen-optimization-cache/uv-engines",
        "UV_NO_PROGRESS": "1",
        "HF_HUB_DISABLE_TELEMETRY": "1",
        "DO_NOT_TRACK": "1",
        "PIP_DISABLE_PIP_VERSION_CHECK": "1",
        "UV_LINK_MODE": "copy",
    }
    Path(env["HOME"]).mkdir(exist_ok=True)

    def run(label, args, timeout=2400):
        if shutil.disk_usage(LAB).free < 8 * 1024**3:
            raise RuntimeError("WSL disk below 8 GiB floor")
        logfile = BASE / (label + ".log")
        with logfile.open("ab") as log:
            process = subprocess.Popen(
                [str(x) for x in args],
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            started = time.monotonic()
            try:
                while process.poll() is None:
                    if shutil.disk_usage(LAB).free < 8 * 1024**3:
                        raise RuntimeError("WSL disk reached 8 GiB floor")
                    if time.monotonic() - started > timeout:
                        raise TimeoutError(label + " exceeded deadline")
                    time.sleep(2)
            except BaseException:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
                raise
        state.setdefault("commands", []).append(
            {"label": label, "returncode": process.returncode, "log": str(logfile)}
        )
        write_json(REPORT, state)
        if process.returncode:
            raise RuntimeError(f"{label} failed ({process.returncode}); see {logfile}")

    try:
        release = fetch(
            "https://api.github.com/repos/turboderp-org/exllamav3/releases/latest"
        )
        assets = [
            a
            for a in release["assets"]
            if "cp312-cp312-linux_x86_64" in a["name"]
            and "+cu132.torch2.13.0-" in a["name"]
        ]
        if len(assets) != 1:
            raise RuntimeError(
                "no unambiguous current Linux/Python3.12 CUDA13.2/Torch2.13 wheel"
            )
        asset = assets[0]
        if not str(asset.get("digest", "")).startswith("sha256:"):
            raise RuntimeError("upstream wheel has no SHA256 digest")
        pin = fetch("https://api.github.com/repos/theroyallab/tabbyAPI/commits/main")[
            "sha"
        ]
        state.update(
            exllamav3={"version": release["tag_name"], "wheel": asset},
            tabby={"commit": pin},
        )
        write_json(REPORT, state)
        uv = LAB / "envs/qwen-harness-refresh-20261025/bootstrap/bin/uv"
        python = (
            LAB
            / "envs/qwen-harness-refresh-20261025/runtimes/python/cpython-3.12.15-linux-x86_64-gnu/bin/python3.12"
        )
        venv = BASE / "venv"
        if not (venv / "bin/python").exists():
            run("venv", [uv, "venv", "--python", python, "--seed", venv])
        wheel = BASE / asset["name"]
        if not wheel.exists():
            temporary = wheel.with_suffix(".part")
            with (
                urllib.request.urlopen(
                    asset["browser_download_url"], timeout=120
                ) as source,
                temporary.open("wb") as target,
            ):
                shutil.copyfileobj(source, target)
            temporary.replace(wheel)
        with wheel.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        if digest != asset["digest"].split(":", 1)[1]:
            raise RuntimeError("EXL3 wheel SHA256 mismatch")
        installed = subprocess.run(
            [
                str(venv / "bin/python"),
                "-c",
                'import importlib.metadata;print(importlib.metadata.version("torch"))',
            ],
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        if installed.stdout.strip() != "2.13.0+cu132":
            run(
                "torch",
                [
                    uv,
                    "pip",
                    "install",
                    "--python",
                    venv / "bin/python",
                    "torch==2.13.0",
                    "--index-url",
                    "https://download.pytorch.org/whl/cu132",
                ],
            )
        # DrvFS copy_file_range produced ENOMEM despite ample RAM; use a native
        # ext4 cache for this wheel so installation stays on the same filesystem.
        env["UV_CACHE_DIR"] = str(BASE / "uv-cache")
        run("exllamav3", [uv, "pip", "install", "--python", venv / "bin/python", wheel])
        source = BASE / "tabbyAPI"
        if not source.exists():
            run(
                "tabby-clone",
                [
                    "git",
                    "clone",
                    "--depth",
                    "1",
                    "https://github.com/theroyallab/tabbyAPI",
                    source,
                ],
            )
        run("tabby-pin", ["git", "-C", source, "checkout", "--detach", pin])
        run(
            "tabby-dependencies",
            [uv, "pip", "install", "--python", venv / "bin/python", source],
        )
        run("dependency-check", [venv / "bin/python", "-m", "pip", "check"])
        run("freeze", [venv / "bin/python", "-m", "pip", "freeze", "--all"])
        run(
            "import",
            [
                venv / "bin/python",
                "-c",
                "import torch,exllamav3;print(torch.__version__,torch.version.cuda);print(exllamav3.__file__)",
            ],
        )
        state.update(
            status="installed_import_qualified",
            python=str(venv / "bin/python"),
            model_compatibility="pending_real_load",
            tabby_root=str(source),
        )
    except Exception as exc:
        state.update(status="blocked", error=f"{type(exc).__name__}: {exc}")
    write_json(REPORT, state)
    print(json.dumps({"status": state["status"], "error": state.get("error")}))


if __name__ == "__main__":
    import sys

    sys.path.insert(0, str(ROOT))
    main()
