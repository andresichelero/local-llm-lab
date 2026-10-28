"""Prepare isolated, local-endpoint CLI commands for the refreshed harnesses.

``config_files`` paths are relative to ``HOME=/scratch/home/agent``. Each
``runtime_ro`` pair is ``(host_path, mounted_path)``; this module deliberately
uses the same absolute path on both sides because the installed CLI shims and
Python virtualenv shebangs point at those paths. The caller should also set the
process working directory to ``workspace``; CLIs with a documented directory
argument receive it in ``argv`` as well.

Provider settings pin documented loopback-only providers for each CLI. TrueForge
needs its API-driven session wrapper and remains blocked until that wire path is
qualified.
"""

from __future__ import annotations

import json
import re
from pathlib import Path


HOME = "/scratch/home/agent"
DEFAULT_CONTEXT = 16_384
DEFAULT_OUTPUT = 8_192
HARNESS_IDS = (
    "pi",
    "opencode",
    "codex",
    "claude-code",
    "hermes",
    "mistral-vibe",
    "trueforge",
    "deepseek-harness",
    "qwen-code",
    "aider",
    "openhands",
)
READY_HARNESSES = frozenset(
    {
        "pi",
        "opencode",
        "codex",
        "claude-code",
        "hermes",
        "mistral-vibe",
        "deepseek-harness",
        "qwen-code",
        "aider",
        "openhands",
    }
)
COMMANDS = {
    "pi": "pi",
    "opencode": "opencode",
    "codex": "codex",
    "claude-code": "claude",
    "trueforge": "trueforge",
    "deepseek-harness": "dsh",
    "qwen-code": "qwen",
    "mistral-vibe": "vibe",
    "aider": "aider",
    "openhands": "openhands",
}
BLOCKED_REASONS = {
    "trueforge": (
        "TrueForge 0.180 is an API server/session client, not a bounded one-shot CLI; a dedicated REST session adapter and SSRF allowlist qualification are required."
    ),
}


def _blocked(reason: str) -> dict:
    return {
        "argv": [],
        "config_files": {},
        "env": {},
        "runtime_ro": [],
        "status": "blocked",
        "reason": reason,
    }


def _mounts(*paths: str | Path) -> list[tuple[str, str]]:
    mounts: list[tuple[str, str]] = []
    seen: set[str] = set()
    for raw in paths:
        path = Path(raw)
        if not path.is_absolute():
            continue
        value = str(path)
        if value not in seen:
            seen.add(value)
            mounts.append((value, value))
    return mounts


def _python_runtime_root(install_state: dict, minor: str) -> Path | None:
    raw = install_state.get("runtime", {}).get("python", {}).get(minor)
    if not raw:
        return None
    interpreter = Path(raw)
    if not interpreter.is_absolute():
        return None
    return interpreter.parent.parent


def _python_runtime_alias(python_root: Path, minor: str) -> Path | None:
    """Return the unversioned symlink path embedded in managed venv shebangs."""
    alias = Path(python_root).parent / f"cpython-{minor}-linux-x86_64-gnu"
    try:
        if alias.is_symlink() and alias.resolve(strict=True) == Path(python_root).resolve(strict=True):
            return alias
    except OSError:
        return None
    return None


def _base_env(workspace: str, node_root: Path) -> dict[str, str]:
    return {
        "HOME": HOME,
        "PWD": workspace,
        "XDG_CONFIG_HOME": f"{HOME}/.config",
        "XDG_DATA_HOME": f"{HOME}/.local/share",
        "XDG_CACHE_HOME": f"{HOME}/.cache",
        "PATH": f"{node_root}/bin:/usr/bin:/bin",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "DO_NOT_TRACK": "1",
        "NO_COLOR": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "NO_PROXY": "127.0.0.1,localhost",
        "no_proxy": "127.0.0.1,localhost",
    }


def _installed_item(install_state: dict, harness: str) -> dict | None:
    item = install_state.get("items", {}).get(harness)
    if not isinstance(item, dict) or item.get("status") not in {"installed", "staged"}:
        return None
    return item


def _node_adapter(
    harness: str,
    item: dict,
    node_root: Path,
    endpoint: str,
    model_alias: str,
    prompt: str,
    workspace: str,
) -> dict:
    prefix = Path(item["root"])
    executable = prefix / "node_modules/.bin" / COMMANDS[harness]
    if not executable.is_file():
        return _blocked(f"The installed {harness} executable is missing: {executable}")
    env = _base_env(workspace, node_root)
    mounts = _mounts(prefix, node_root)

    if harness == "pi":
        env.update(
            PI_CODING_AGENT_DIR=f"{HOME}/.pi/agent",
            PI_CODING_AGENT_SESSION_DIR=f"{HOME}/.pi/sessions",
            PI_OFFLINE="1",
            PI_TELEMETRY="0",
        )
        config = {
            "providers": {
                "local-llama": {
                    "baseUrl": endpoint,
                    "api": "openai-completions",
                    "apiKey": "local",
                    "models": [
                        {
                            "id": model_alias,
                            "name": model_alias,
                            "contextWindow": DEFAULT_CONTEXT,
                            "maxTokens": DEFAULT_OUTPUT,
                            "input": ["text"],
                            "reasoning": True,
                        }
                    ],
                }
            }
        }
        argv = [
            str(executable),
            "--provider",
            "local-llama",
            "--model",
            model_alias,
            "--no-session",
            "--print",
            prompt,
        ]
        config_files = {".pi/agent/models.json": json.dumps(config, indent=2) + "\n"}
    elif harness == "opencode":
        env["OPENCODE_DISABLE_AUTOUPDATE"] = "1"
        config = {
            "model": f"local/{model_alias}",
            "provider": {
                "local": {
                    "npm": "@ai-sdk/openai-compatible",
                    "name": "Local Qwen endpoint",
                    "options": {"baseURL": endpoint, "apiKey": "local"},
                    "models": {
                        model_alias: {
                            "name": model_alias,
                            "limit": {
                                "context": DEFAULT_CONTEXT,
                                "output": DEFAULT_OUTPUT,
                            },
                            "options": {"temperature": 0.6, "topP": 0.95},
                        }
                    },
                }
            },
        }
        argv = [
            str(executable),
            "run",
            "--model",
            f"local/{model_alias}",
            "--dir",
            workspace,
            prompt,
        ]
        config_files = {
            ".config/opencode/opencode.json": json.dumps(config, indent=2) + "\n"
        }
    elif harness == "deepseek-harness":
        env["DSH_HOME"] = f"{HOME}/.dsh"
        env["OPENAI_API_KEY"] = "local"
        env["DSH_PERMISSION_MODE"] = "workspace-write"
        patch = (
            "- id: agent-default-model\n"
            "  name: '@deepseek-ai/dsh-agent-default-model'\n"
            "  config:\n"
            "    provider: openai\n"
            f"    model: {json.dumps(model_alias)}\n"
            "- id: llm-pi-ai\n"
            "  name: '@deepseek-ai/dsh-llm-pi-ai'\n"
            "  config:\n"
            "    providers:\n"
            "      openai:\n"
            "        apiKeyEnv: OPENAI_API_KEY\n"
            "        api: openai-completions\n"
            f"        baseURL: {json.dumps(endpoint)}\n"
            "        models:\n"
            f"          - id: {json.dumps(model_alias)}\n"
            f"            name: {json.dumps(model_alias)}\n"
            f"            contextWindow: {DEFAULT_CONTEXT}\n"
            f"            maxTokens: {DEFAULT_OUTPUT}\n"
            "            input: [text]\n"
            "- id: web\n  name: '@deepseek-ai/dsh-web'\n  disabled: true\n"
            "- id: web-search-deepseek\n  name: '@deepseek-ai/dsh-web-search-deepseek'\n  disabled: true\n"
            "- id: web-deepseek-api\n  name: '@deepseek-ai/dsh-web-deepseek-api'\n  disabled: true\n"
            "- id: otel\n  name: '@deepseek-ai/dsh-otel'\n  disabled: true\n"
            "- id: session-telemetry-otel\n  name: '@deepseek-ai/dsh-session-telemetry-otel'\n  disabled: true\n"
        )
        patch_path = f"{HOME}/.dsh/qwen-local.patch.yml"
        argv = [str(executable), "--profile", "headless", "--patch", patch_path, prompt]
        config_files = {".dsh/qwen-local.patch.yml": patch}
    elif harness == "qwen-code":
        env["OPENAI_API_KEY"] = "local"
        env["OPENAI_BASE_URL"] = endpoint
        settings = {
            "modelProviders": {
                "openai": [
                    {
                        "id": model_alias,
                        "name": model_alias,
                        "baseUrl": endpoint,
                        "envKey": "OPENAI_API_KEY",
                    }
                ]
            },
            "model": {"name": model_alias},
            "security": {"auth": {"selectedType": "openai"}},
            "telemetry": {"enabled": False},
        }
        argv = [
            str(executable),
            "--auth-type",
            "openai",
            "--model",
            model_alias,
            "--prompt",
            prompt,
        ]
        config_files = {".qwen/settings.json": json.dumps(settings, indent=2) + "\n"}
    else:
        return _blocked(f"No ready Node adapter is defined for {harness}")

    return {
        "argv": argv,
        "config_files": config_files,
        "env": env,
        "runtime_ro": mounts,
        "status": "ready",
        "reason": "",
    }


def _python_adapter(
    harness: str,
    item: dict,
    install_state: dict,
    endpoint: str,
    model_alias: str,
    prompt: str,
    workspace: str,
    node_root: Path,
) -> dict:
    prefix = Path(item["root"])
    executable = prefix / "bin" / COMMANDS[harness]
    minor = str(item.get("python", ""))
    python_root = _python_runtime_root(install_state, minor)
    if not executable.is_file() or python_root is None:
        return _blocked(f"The installed {harness} runtime or CLI is missing")
    env = _base_env(workspace, node_root)
    mounts = _mounts(prefix, python_root, node_root)
    runtime_alias = _python_runtime_alias(python_root, minor)
    if runtime_alias is not None:
        mounts.append((str(python_root), str(runtime_alias)))

    if harness == "mistral-vibe":
        env["VIBE_HOME"] = HOME
        config = "\n".join(
            [
                f"active_model = {json.dumps(model_alias)}",
                "",
                "[[providers]]",
                'name = "llamacpp"',
                f"api_base = {json.dumps(endpoint)}",
                'api_key_env_var = ""',
                "",
                "[[models]]",
                'name = "qwen-local"',
                'provider = "llamacpp"',
                f"alias = {json.dumps(model_alias)}",
                "temperature = 0.0",
                'thinking = "off"',
                f"max_context_length = {DEFAULT_CONTEXT}",
                f"auto_compact_threshold = {int(DEFAULT_CONTEXT * 0.9)}",
                "",
            ]
        )
        argv = [str(executable), "--prompt", prompt, "--workdir", workspace]
        config_files = {"config.toml": config}
        reason = ""
    elif harness == "aider":
        argv = [
            str(executable),
            "--model",
            f"openai/{model_alias}",
            "--openai-api-base",
            endpoint,
            "--openai-api-key",
            "local",
            "--no-check-update",
            "--analytics-disable",
            "--message",
            prompt,
        ]
        config_files = {}
        reason = ""
    elif harness == "openhands":
        env.update(
            LLM_API_KEY="local",
            LLM_BASE_URL=endpoint,
            LLM_MODEL=f"openai/{model_alias}",
            LITELLM_LOCAL_MODEL_COST_MAP="True",
            OPENHANDS_SUPPRESS_BANNER="1",
        )
        argv = [
            str(executable),
            "--headless",
            "--json",
            "--override-with-envs",
            "--task",
            prompt,
        ]
        config_files = {}
        reason = "Headless mode auto-approves actions; the outer namespace must enforce workspace and tool limits."
    else:
        return _blocked(f"No ready Python adapter is defined for {harness}")

    return {
        "argv": argv,
        "config_files": config_files,
        "env": env,
        "runtime_ro": mounts,
        "status": "ready",
        "reason": reason,
    }


def _hermes_adapter(
    item: dict,
    model_alias: str,
    endpoint: str,
    prompt: str,
    workspace: str,
    node_root: Path,
) -> dict:
    data_home = Path(item.get("home", "")) / "hermes-data"
    installs = sorted(data_home.glob("installs/*/environments/*/venv"))
    if len(installs) != 1 or not (installs[0] / "bin/hermes").is_file():
        return _blocked(
            "The isolated Hermes PM virtualenv could not be resolved to one CLI path"
        )
    tools_root = data_home / "tools"
    if not tools_root.is_dir():
        return _blocked("The isolated Hermes runtime tool directory is missing")
    executable = installs[0] / "bin/hermes"
    python = installs[0] / "bin/python"
    tool_roots = sorted(path for path in tools_root.iterdir() if path.is_dir())
    if not tool_roots:
        return _blocked("The isolated Hermes runtime tool directory is missing")
    env = _base_env(workspace, node_root)
    env["HERMES_HOME"] = f"{HOME}/.hermes"
    env["OPENAI_API_KEY"] = "local"
    tool_bins = [str(path / "bin") for path in tool_roots if (path / "bin").is_dir()]
    env["PATH"] = ":".join([*tool_bins, env["PATH"]])
    config = (
        "fallback_providers: []\n"
        "custom_providers:\n"
        "  - name: local-qwen\n"
        f"    base_url: {json.dumps(endpoint)}\n"
        "    api_mode: chat_completions\n"
        "    key_env: OPENAI_API_KEY\n"
        f"    model: {json.dumps(model_alias)}\n"
    )
    argv = [
        str(executable),
        "--provider",
        "custom:local-qwen",
        "--model",
        model_alias,
        "--base-url",
        endpoint,
        "--api-key",
        "local",
        "--in",
        workspace,
        "chat",
        "-q",
        prompt,
        "--oneshot",
        "--quiet",
    ]
    mounts = _mounts(
        item["root"],
        installs[0],
        python.resolve().parent.parent,
        node_root,
        *tool_roots,
    )
    return {
        "argv": argv,
        "config_files": {".hermes/config.yaml": config},
        "env": env,
        "runtime_ro": mounts,
        "status": "ready",
        "reason": "",
    }


def _dsh_adapter(
    item: dict,
    endpoint: str,
    model_alias: str,
    prompt: str,
    workspace: str,
    node_root: Path,
) -> dict:
    prefix = Path(item["root"])
    executable = prefix / "node_modules/.bin/dsh"
    if not executable.is_file():
        return _blocked(
            f"The installed DeepSeek Harness executable is missing: {executable}"
        )
    env = _base_env(workspace, node_root)
    env.update(
        DSH_HOME=f"{HOME}/.dsh",
        DSH_PERMISSION_MODE="workspace-write",
        OPENAI_API_KEY="local",
    )
    patch = (
        "- id: agent-default-model\n"
        "  name: '@deepseek-ai/dsh-agent-default-model'\n"
        "  config:\n"
        "    provider: openai\n"
        f"    model: {json.dumps(model_alias)}\n"
        "- id: llm-pi-ai\n"
        "  name: '@deepseek-ai/dsh-llm-pi-ai'\n"
        "  config:\n"
        "    providers:\n"
        "      openai:\n"
        "        apiKeyEnv: OPENAI_API_KEY\n"
        "        api: openai-completions\n"
        f"        baseURL: {json.dumps(endpoint)}\n"
        "        models:\n"
        f"          - id: {json.dumps(model_alias)}\n"
        f"            name: {json.dumps(model_alias)}\n"
        f"            contextWindow: {DEFAULT_CONTEXT}\n"
        f"            maxTokens: {DEFAULT_OUTPUT}\n"
        "            input: [text]\n"
        "- id: web\n  name: '@deepseek-ai/dsh-web'\n  disabled: true\n"
        "- id: web-search-deepseek\n  name: '@deepseek-ai/dsh-web-search-deepseek'\n  disabled: true\n"
        "- id: web-deepseek-api\n  name: '@deepseek-ai/dsh-web-deepseek-api'\n  disabled: true\n"
        "- id: otel\n  name: '@deepseek-ai/dsh-otel'\n  disabled: true\n"
        "- id: session-telemetry-otel\n  name: '@deepseek-ai/dsh-session-telemetry-otel'\n  disabled: true\n"
    )
    patch_path = f"{HOME}/.dsh/qwen-local.patch.yml"
    return {
        "argv": [
            str(executable),
            "--profile",
            "headless",
            "--patch",
            patch_path,
            prompt,
        ],
        "config_files": {".dsh/qwen-local.patch.yml": patch},
        "env": env,
        "runtime_ro": _mounts(prefix, node_root),
        "status": "ready",
        "reason": "",
    }


def prepare_adapter(
    harness: str,
    install_state: dict,
    *,
    model_alias: str,
    endpoint_port: int,
    prompt: str,
    workspace: str = "/workspace",
    mcp_port: int | None = None,
) -> dict:
    """Return a CLI invocation and isolated provider settings without running a model.

    Blocked adapters return no command or configuration. Unknown or incomplete
    install state is also blocked rather than falling back to an ambient provider.
    """
    if (
        isinstance(endpoint_port, bool)
        or not isinstance(endpoint_port, int)
        or not 1 <= endpoint_port <= 65535
    ):
        raise ValueError("endpoint_port must be an integer in [1, 65535]")
    if not isinstance(model_alias, str) or not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9._/-]{0,127}", model_alias
    ):
        raise ValueError("model_alias must be a non-empty string without NUL")
    if not isinstance(prompt, str) or "\0" in prompt:
        raise ValueError("prompt must be a string without NUL")
    if not isinstance(workspace, str) or not Path(workspace).is_absolute():
        raise ValueError("workspace must be an absolute path inside the namespace")
    if harness not in HARNESS_IDS:
        return _blocked(f"Unknown harness: {harness}")
    item = _installed_item(install_state, harness)
    if item is None:
        return _blocked(
            f"{harness} is not installed in the supplied installation state"
        )
    node_root_raw = install_state.get("runtime", {}).get("node", {}).get("root")
    if not node_root_raw or not Path(node_root_raw).is_absolute():
        return _blocked("The isolated Node runtime path is missing")
    node_root = Path(node_root_raw)
    endpoint = f"http://127.0.0.1:{endpoint_port}/v1"

    if harness in BLOCKED_REASONS:
        return _blocked(BLOCKED_REASONS[harness])
    if harness == "codex":
        return dict(
            _codex_adapter(item, model_alias, endpoint, prompt, workspace, node_root),
            mcp_supported=False,
            mcp_reason="No documented installed-version MCP config was qualified offline",
        )
    if harness == "claude-code":
        return dict(
            _claude_adapter(item, model_alias, endpoint, prompt, workspace, node_root),
            mcp_supported=False,
            mcp_reason="No documented installed-version MCP config was qualified offline",
        )
    if harness == "hermes":
        return _add_episode_mcp(
            _hermes_adapter(item, model_alias, endpoint, prompt, workspace, node_root),
            harness,
            mcp_port,
        )
    if harness == "deepseek-harness":
        return _add_episode_mcp(
            _dsh_adapter(item, endpoint, model_alias, prompt, workspace, node_root),
            harness,
            mcp_port,
        )
    if harness in {"pi", "opencode", "qwen-code"}:
        return _add_episode_mcp(
            _node_adapter(
                harness, item, node_root, endpoint, model_alias, prompt, workspace
            ),
            harness,
            mcp_port,
        )
    return _add_episode_mcp(
        _python_adapter(
            harness,
            item,
            install_state,
            endpoint,
            model_alias,
            prompt,
            workspace,
            node_root,
        ),
        harness,
        mcp_port,
    )


def _codex_adapter(item, model_alias, endpoint, prompt, workspace, node_root):
    prefix = Path(item["root"])
    exe = prefix / "node_modules/.bin/codex"
    if not exe.is_file():
        return _blocked("isolated Codex executable is missing")
    env = _base_env(workspace, node_root)
    env.update(
        CODEX_HOME=f"{HOME}/.codex",
        OPENAI_API_KEY="local",
        CODEX_DISABLE_AUTOUPDATER="1",
    )

    def quote(value):
        return json.dumps(value, ensure_ascii=False)

    config = "\n".join(
        [
            f"model = {quote(model_alias)}",
            'model_provider = "qwen-local"',
            'approval_policy = "never"',
            'sandbox_mode = "workspace-write"',
            'web_search = "disabled"',
            "",
            "[model_providers.qwen-local]",
            'name = "Local Qwen"',
            f"base_url = {quote(endpoint)}",
            'env_key = "OPENAI_API_KEY"',
            'wire_api = "responses"',
            "requires_openai_auth = true",
            "supports_websockets = false",
            "",
        ]
    )
    argv = [
        str(exe),
        "exec",
        "--ephemeral",
        "--skip-git-repo-check",
        "--json",
        "--sandbox",
        "workspace-write",
        "--color",
        "never",
        "--cd",
        workspace,
        "--model",
        model_alias,
        prompt,
    ]
    return {
        "argv": argv,
        "config_files": {".codex/config.toml": config},
        "env": env,
        "runtime_ro": _mounts(prefix, node_root),
        "status": "ready",
        "reason": "Pinned local Codex custom provider uses the Responses API through the native local gateway.",
    }


def _claude_adapter(item, model_alias, endpoint, prompt, workspace, node_root):
    prefix = Path(item["root"])
    exe = prefix / "node_modules/.bin/claude"
    if not exe.is_file():
        return _blocked("isolated Claude Code executable is missing")
    env = _base_env(workspace, node_root)
    env.update(
        ANTHROPIC_BASE_URL=endpoint.rsplit("/v1", 1)[0],
        ANTHROPIC_AUTH_TOKEN="local",
        ANTHROPIC_MODEL=model_alias,
        ANTHROPIC_DEFAULT_OPUS_MODEL=model_alias,
        ANTHROPIC_DEFAULT_SONNET_MODEL=model_alias,
        ANTHROPIC_DEFAULT_HAIKU_MODEL=model_alias,
        CLAUDE_CONFIG_DIR=f"{HOME}/.claude",
    )
    cfg = {
        "permissions": {"defaultMode": "acceptEdits"},
        "apiKeyHelper": "printf local",
        "disableTelemetry": True,
        "skipWebFetchPreflight": True,
    }
    argv = [
        str(exe),
        "-p",
        "--output-format",
        "stream-json",
        "--verbose",
        "--model",
        model_alias,
        "--permission-mode",
        "acceptEdits",
        "--setting-sources",
        "user,project,local",
        prompt,
    ]
    return {
        "argv": argv,
        "config_files": {".claude/settings.json": json.dumps(cfg, indent=2) + "\n"},
        "env": env,
        "runtime_ro": _mounts(prefix, node_root),
        "status": "ready",
        "reason": "Local Anthropic Messages protocol through the loopback adapter; upstream Claude support policy does not warrant a Qwen quality claim.",
    }


def _add_episode_mcp(adapter: dict, harness: str, port: int | None) -> dict:
    """Add the source-bound JSON-RPC relay only for the qualified OpenCode V1 schema."""
    if adapter.get("status") != "ready":
        return adapter
    if port is None:
        return dict(
            adapter,
            mcp_supported=(harness == "opencode"),
            mcp_reason="OpenCode MCP route is documented; no MCP server enabled for this task."
            if harness == "opencode"
            else "No documented installed-version MCP config was qualified offline",
        )
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError("MCP relay port must be an integer in 1..65535")
    if harness != "opencode":
        return dict(
            adapter,
            mcp_supported=False,
            mcp_reason="The installed-version native MCP route has not been qualified",
        )
    config_path = ".config/opencode/opencode.json"
    config = json.loads(adapter["config_files"][config_path])
    config.setdefault("mcp", {})["lab"] = {
        "type": "local",
            "command": ["/usr/bin/python3", "/opt/qwen-native/qwen_native_mcp.py", str(port)],
        "enabled": True,
        "environment": {"PYTHONDONTWRITEBYTECODE": "1"},
    }
    adapter["config_files"][config_path] = json.dumps(config, indent=2) + "\n"
    adapter["mcp_supported"] = True
    adapter["mcp_reason"] = (
        "OpenCode V1 uses its native local command MCP provider backed by the bounded per-episode host bridge."
    )
    return adapter
