"""Runs one refreshed native harness inside an already locked Linux namespace."""

from __future__ import annotations

import json
import hashlib
from pathlib import Path
import os
import selectors
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
from qwen_native_gateway import NativeGateway


def main():
    if len(sys.argv) != 2:
        return 2
    adapter_path = Path(sys.argv[1])
    adapter = json.loads(adapter_path.read_text())
    if adapter.get("status") != "ready" or not adapter.get("argv"):
        print(
            json.dumps({"status": "adapter_blocked", "reason": adapter.get("reason")}),
            flush=True,
        )
        return 77
    env = dict(adapter["env"])
    # The adapter settings are fresh, local-only constants; never inherit host
    # credentials, provider settings, proxies, or update tokens.
    allowed = {
        "HOME",
        "PWD",
        "XDG_CONFIG_HOME",
        "XDG_DATA_HOME",
        "XDG_CACHE_HOME",
        "PATH",
        "LANG",
        "LC_ALL",
        "DO_NOT_TRACK",
        "NO_COLOR",
        "PYTHONDONTWRITEBYTECODE",
        "NO_PROXY",
        "no_proxy",
        "HERMES_HOME",
        "CODEX_HOME",
        "CODEX_DISABLE_AUTOUPDATER",
        "PI_CODING_AGENT_DIR",
        "PI_CODING_AGENT_SESSION_DIR",
        "PI_OFFLINE",
        "PI_TELEMETRY",
        "VIBE_HOME",
        "DSH_HOME",
        "DSH_PERMISSION_MODE",
        "LITELLM_LOCAL_MODEL_COST_MAP",
        "OPENHANDS_SUPPRESS_BANNER",
        "OPENCODE_DISABLE_AUTOUPDATE",
        "ANTHROPIC_BASE_URL",
        "ANTHROPIC_AUTH_TOKEN",
        "ANTHROPIC_MODEL",
        "ANTHROPIC_DEFAULT_OPUS_MODEL",
        "ANTHROPIC_DEFAULT_SONNET_MODEL",
        "ANTHROPIC_DEFAULT_HAIKU_MODEL",
        "CLAUDE_CONFIG_DIR",
        "OPENAI_API_BASE",
        "OPENAI_BASE_URL",
        "OPENAI_API_KEY",
        "LLM_API_KEY",
        "LLM_BASE_URL",
        "LLM_MODEL",
    }
    synthetic = {"ANTHROPIC_AUTH_TOKEN", "OPENAI_API_KEY", "LLM_API_KEY"}
    if set(env) - allowed or any(
        any(x in k.upper() for x in ("SECRET", "PASSWORD"))
        or ("TOKEN" in k.upper() and k not in synthetic)
        for k in env
    ):
        print(
            json.dumps(
                {
                    "status": "adapter_blocked",
                    "reason": "environment contains an unapproved variable",
                }
            ),
            flush=True,
        )
        return 78
    for relative, content in adapter.get("config_files", {}).items():
        path = Path(relative)
        if (
            path.is_absolute()
            or ".." in path.parts
            or len(path.parts) > 8
            or len(content.encode()) > 128 * 1024
        ):
            print(
                json.dumps(
                    {
                        "status": "adapter_blocked",
                        "reason": "provider config path or size is invalid",
                    }
                ),
                flush=True,
            )
            return 78
        target = Path(env["HOME"]).joinpath(*path.parts)
        if not target.resolve().is_relative_to(Path(env["HOME"]).resolve()):
            return 78
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
    with NativeGateway(
        18888,
        str(adapter.get("model_alias", "local-qwen")),
        int(adapter.get("output_cap", 8192)),
        port=int(adapter.get("gateway_port", 18887)),
        generation=adapter.get("generation"),
        aliases=adapter.get("native_model_aliases", ()),
    ) as gateway:
        started = time.monotonic()
        process = subprocess.Popen(
            adapter["argv"],
            cwd=adapter["workspace"],
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            close_fds=True,
            bufsize=0,
        )
        cap = 8 * 1024**2
        output = bytearray()
        assert process.stdout is not None
        wall_budget_exhausted = False
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            while process.poll() is None:
                if time.monotonic() - started >= 1770:
                    wall_budget_exhausted = True
                    os.killpg(process.pid, 15)
                    break
                if not selector.select(timeout=1):
                    continue
                part = process.stdout.read(64 * 1024)
                if not part:
                    break
                if len(output) < cap:
                    output.extend(part[: cap - len(output)])
        try:
            code = process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            code = process.wait(timeout=10)
        (Path(adapter["evidence_dir"]) / "native-cli.stdout.txt").write_bytes(
            bytes(output)
        )
        report = {
            "status": "cli_exit",
            "returncode": code,
            "seconds": time.monotonic() - started,
            "wall_budget_exhausted": wall_budget_exhausted,
            "stdout_bytes_retained": len(output),
            "stdout_truncated": len(output) >= cap,
            "native_protocol_requests": gateway.calls,
            "model_generations": gateway.generations,
            "tool_calls_observed": gateway.tool_calls,
            "tool_budget_exhausted": gateway.tool_budget_exhausted,
            "model_budget_exhausted": gateway.model_budget_exhausted,
            "effective_generation": gateway.profile,
            "adapter_config_sha256": hashlib.sha256(adapter_path.read_bytes()).hexdigest(),
        }
        print(
            "QWEN_NATIVE_EPISODE:" + json.dumps(report, separators=(",", ":")),
            flush=True,
        )
        return code


if __name__ == "__main__":
    raise SystemExit(main())
