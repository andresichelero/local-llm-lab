import importlib.util
import json
from pathlib import Path

import pytest


spec = importlib.util.spec_from_file_location(
    "qwen_harness_adapters",
    Path(__file__).parents[1] / "benchmark/qwen_harness_adapters.py",
)
adapters = importlib.util.module_from_spec(spec)
spec.loader.exec_module(adapters)


def install_state(tmp_path):
    root = tmp_path / "refresh"
    node = root / "runtimes/node-v24.22.1-linux-x64"
    node.mkdir(parents=True)
    python = {}
    for minor in ("3.14", "3.12"):
        runtime = root / f"runtimes/python/cpython-{minor}.0-linux-x86_64-gnu"
        (runtime / "bin").mkdir(parents=True)
        interpreter = runtime / "bin" / f"python{minor}"
        interpreter.write_text("python runtime")
        python[minor] = str(interpreter)

    items = {}
    npm = {
        "pi": "pi",
        "opencode": "opencode",
        "codex": "codex",
        "claude-code": "claude",
        "trueforge": "trueforge",
        "deepseek-harness": "dsh",
        "qwen-code": "qwen",
    }
    for name, command in npm.items():
        prefix = root / "packages" / name
        binary = prefix / "node_modules/.bin" / command
        binary.parent.mkdir(parents=True)
        binary.write_text("cli")
        items[name] = {"status": "installed", "kind": "npm", "root": str(prefix)}

    python_items = {
        "mistral-vibe": ("vibe", "3.14"),
        "aider": ("aider", "3.12"),
        "openhands": ("openhands", "3.12"),
    }
    for name, (command, minor) in python_items.items():
        prefix = root / "packages" / name / f"python-{minor}"
        (prefix / "bin").mkdir(parents=True)
        (prefix / "bin" / command).write_text("cli")
        (prefix / "bin/python").write_text("python")
        items[name] = {
            "status": "installed",
            "kind": "pypi",
            "root": str(prefix),
            "python": minor,
        }

    source = root / "sources/hermes"
    source.mkdir(parents=True)
    hermes_home = root / "homes/hermes/hermes-data"
    venv = hermes_home / "installs/install/environments/runtime/venv"
    (venv / "bin").mkdir(parents=True)
    (venv / "bin/hermes").write_text("cli")
    (venv / "bin/python").write_text("python")
    for tool in ("node-26", "python-3.14", "uv-0.13"):
        (hermes_home / "tools" / tool / "bin").mkdir(parents=True)
    items["hermes"] = {
        "status": "installed",
        "kind": "source",
        "root": str(source),
        "home": str(hermes_home.parent),
    }

    return {
        "status": "installed",
        "base": str(root),
        "items": items,
        "runtime": {"node": {"root": str(node)}, "python": python},
    }


def assert_same_path_mounts(result):
    assert all(source == target for source, target in result["runtime_ro"])
    assert all(Path(source).is_absolute() for source, _ in result["runtime_ro"])


def test_python_runtime_mount_alias_matches_virtualenv_shebang_target(tmp_path):
    root = tmp_path / "runtimes/python"
    runtime = root / "cpython-3.12.15-linux-x86_64-gnu"
    runtime.mkdir(parents=True)
    alias = root / "cpython-3.12-linux-x86_64-gnu"
    alias.symlink_to(runtime)

    assert adapters._python_runtime_alias(runtime, "3.12") == alias


def test_python_cli_mounts_alias_only_when_it_resolves_to_selected_runtime(tmp_path):
    state = install_state(tmp_path)
    interpreter = Path(state["runtime"]["python"]["3.12"])
    runtime = interpreter.parent.parent
    alias = runtime.parent / "cpython-3.12-linux-x86_64-gnu"
    alias.symlink_to(runtime)

    adapter = adapters.prepare_adapter(
        "aider",
        state,
        model_alias="local-qwen",
        endpoint_port=18887,
        prompt="offline smoke",
        workspace="/workspace",
    )

    assert (str(runtime), str(alias)) in adapter["runtime_ro"]


def test_all_eleven_adapters_return_the_declared_contract(tmp_path):
    state = install_state(tmp_path)
    expected_ready = {
        "pi",
        "opencode",
        "codex",
        "claude-code",
        "codex",
        "claude-code",
        "hermes",
        "mistral-vibe",
        "deepseek-harness",
        "qwen-code",
        "aider",
        "openhands",
    }

    for harness in adapters.HARNESS_IDS:
        result = adapters.prepare_adapter(
            harness,
            state,
            model_alias="Qwen3.5-9B-Q4_K_M",
            endpoint_port=8123,
            prompt="Do the task safely.",
        )
        assert set(result) >= {
            "argv",
            "config_files",
            "env",
            "runtime_ro",
            "status",
            "reason",
        }
        assert set(result) - {
            "argv",
            "config_files",
            "env",
            "runtime_ro",
            "status",
            "reason",
        } <= {"mcp_supported", "mcp_reason"}
        assert result["status"] == ("ready" if harness in expected_ready else "blocked")
        if result["status"] == "ready":
            assert result["argv"]
            assert result["reason"] == "" or harness in {
                "openhands",
                "codex",
                "claude-code",
            }
            assert result["env"]["HOME"] == "/scratch/home/agent"
            assert result["env"]["PWD"] == "/workspace"
            assert_same_path_mounts(result)
        else:
            assert not result["argv"]
            assert result["config_files"] == {}
            assert result["reason"]


def test_ready_adapters_force_loopback_and_do_not_add_remote_fallbacks(tmp_path):
    state = install_state(tmp_path)
    for harness in adapters.READY_HARNESSES:
        result = adapters.prepare_adapter(
            harness,
            state,
            model_alias="qwen-local",
            endpoint_port=8124,
            prompt="Explain this file.",
            workspace="/workspace/project",
        )
        serialized = json.dumps(result)
        assert "http://127.0.0.1:8124" in serialized
        assert "https://" not in serialized
        assert "openrouter" not in serialized.lower()
        assert result["env"]["NO_PROXY"] == "127.0.0.1,localhost"
        assert "local" in serialized


def test_pi_and_opencode_configs_use_only_the_declared_local_model(tmp_path):
    state = install_state(tmp_path)
    pi = adapters.prepare_adapter(
        "pi", state, model_alias="qwen-local", endpoint_port=8125, prompt="x"
    )
    pi_config = json.loads(pi["config_files"][".pi/agent/models.json"])
    assert set(pi_config["providers"]) == {"local-llama"}
    assert (
        pi_config["providers"]["local-llama"]["baseUrl"] == "http://127.0.0.1:8125/v1"
    )
    assert pi_config["providers"]["local-llama"]["models"][0]["id"] == "qwen-local"
    assert pi["argv"][-2:] == ["--print", "x"]

    opencode = adapters.prepare_adapter(
        "opencode", state, model_alias="qwen-local", endpoint_port=8125, prompt="x"
    )
    config = json.loads(opencode["config_files"][".config/opencode/opencode.json"])
    assert config["model"] == "local/qwen-local"
    assert set(config["provider"]) == {"local"}
    assert (
        config["provider"]["local"]["options"]["baseURL"] == "http://127.0.0.1:8125/v1"
    )
    assert opencode["argv"][-1] == "x"


def test_hermes_vibe_and_deepseek_configure_their_documented_local_routes(tmp_path):
    state = install_state(tmp_path)
    endpoint = "http://127.0.0.1:8126/v1"

    hermes = adapters.prepare_adapter(
        "hermes", state, model_alias="qwen-local", endpoint_port=8126, prompt="x"
    )
    hermes_config = hermes["config_files"][".hermes/config.yaml"]
    assert "name: local-qwen" in hermes_config
    assert f'base_url: "{endpoint}"' in hermes_config
    assert "api_mode: chat_completions" in hermes_config
    assert "fallback_providers: []" in hermes_config
    assert hermes["env"]["OPENAI_API_KEY"] == "local"
    assert "-q" in hermes["argv"] and "--provider" in hermes["argv"]

    vibe = adapters.prepare_adapter(
        "mistral-vibe", state, model_alias="qwen-local", endpoint_port=8126, prompt="x"
    )
    assert f'api_base = "{endpoint}"' in vibe["config_files"]["config.toml"]
    assert 'alias = "qwen-local"' in vibe["config_files"]["config.toml"]
    assert "--workdir" in vibe["argv"] and "/workspace" in vibe["argv"]

    dsh = adapters.prepare_adapter(
        "deepseek-harness",
        state,
        model_alias="qwen-local",
        endpoint_port=8126,
        prompt="x",
    )
    patch = dsh["config_files"][".dsh/qwen-local.patch.yml"]
    assert "provider: openai" in patch
    assert f'baseURL: "{endpoint}"' in patch
    assert "disabled: true" in patch
    assert dsh["env"]["OPENAI_API_KEY"] == "local"
    assert "--patch" in dsh["argv"]


def test_qwen_aider_and_openhands_use_local_openai_compatible_settings(tmp_path):
    state = install_state(tmp_path)
    endpoint = "http://127.0.0.1:8127/v1"

    qwen = adapters.prepare_adapter(
        "qwen-code", state, model_alias="qwen-local", endpoint_port=8127, prompt="x"
    )
    settings = json.loads(qwen["config_files"][".qwen/settings.json"])
    assert settings["modelProviders"]["openai"][0]["baseUrl"] == endpoint
    assert settings["security"]["auth"]["selectedType"] == "openai"
    assert qwen["env"]["OPENAI_API_KEY"] == "local"

    aider = adapters.prepare_adapter(
        "aider", state, model_alias="qwen-local", endpoint_port=8127, prompt="x"
    )
    assert "openai/qwen-local" in aider["argv"]
    assert "--openai-api-base" in aider["argv"] and endpoint in aider["argv"]
    assert "--openai-api-key" in aider["argv"] and "local" in aider["argv"]

    openhands = adapters.prepare_adapter(
        "openhands", state, model_alias="qwen-local", endpoint_port=8127, prompt="x"
    )
    assert openhands["env"]["LLM_MODEL"] == "openai/qwen-local"
    assert openhands["env"]["LLM_BASE_URL"] == endpoint
    assert openhands["argv"][-1] == "x"
    assert "--override-with-envs" in openhands["argv"]


def test_blocked_adapters_explain_missing_local_provider_evidence(tmp_path):
    state = install_state(tmp_path)
    for harness in ("trueforge",):
        result = adapters.prepare_adapter(
            harness, state, model_alias="qwen-local", endpoint_port=8128, prompt="x"
        )
        assert result["status"] == "blocked"
        assert not result["argv"]
        assert result["reason"]


def test_codex_responses_and_anthropic_messages_pin_the_loopback_provider(tmp_path):
    state = install_state(tmp_path)
    codex = adapters.prepare_adapter(
        "codex", state, model_alias="qwen-local", endpoint_port=8129, prompt="x"
    )
    config = codex["config_files"][".codex/config.toml"]
    assert 'wire_api = "responses"' in config
    assert 'base_url = "http://127.0.0.1:8129/v1"' in config
    assert 'web_search = "disabled"' in config
    assert "network_access =" not in config
    assert "--skip-git-repo-check" in codex["argv"]
    claude = adapters.prepare_adapter(
        "claude-code", state, model_alias="qwen-local", endpoint_port=8129, prompt="x"
    )
    assert claude["env"]["ANTHROPIC_BASE_URL"] == "http://127.0.0.1:8129"
    assert claude["env"]["ANTHROPIC_AUTH_TOKEN"] == "local"
    assert claude["argv"][claude["argv"].index("--permission-mode") + 1] == "acceptEdits"
    assert json.loads(claude["config_files"][".claude/settings.json"])["permissions"]["defaultMode"] == "acceptEdits"


def test_only_the_provider_with_a_verified_stdio_mcp_schema_gets_the_episode_relay(
    tmp_path,
):
    state = install_state(tmp_path)
    opencode = adapters.prepare_adapter(
        "opencode",
        state,
        model_alias="qwen-local",
        endpoint_port=8123,
        prompt="x",
        mcp_port=8124,
    )
    config = json.loads(opencode["config_files"][".config/opencode/opencode.json"])
    assert opencode["mcp_supported"] is True
    assert config["mcp"]["lab"]["command"] == [
        "/usr/bin/python3",
        "/opt/qwen-native/qwen_native_mcp.py",
        "8124",
    ]
    for harness in adapters.READY_HARNESSES - {"opencode"}:
        item = adapters.prepare_adapter(
            harness,
            state,
            model_alias="qwen-local",
            endpoint_port=8123,
            prompt="x",
            mcp_port=8124,
        )
        assert item["mcp_supported"] is False
        assert "MCP" in item["mcp_reason"] and "qualified" in item["mcp_reason"]


@pytest.mark.parametrize("port", [0, -1, 65536, True])
def test_invalid_endpoint_port_is_rejected(tmp_path, port):
    with pytest.raises(ValueError, match="endpoint_port"):
        adapters.prepare_adapter(
            "pi",
            install_state(tmp_path),
            model_alias="qwen",
            endpoint_port=port,
            prompt="x",
        )


def test_unknown_or_uninstalled_harness_is_blocked(tmp_path):
    state = install_state(tmp_path)
    assert (
        adapters.prepare_adapter(
            "not-a-harness", state, model_alias="qwen", endpoint_port=8129, prompt="x"
        )["status"]
        == "blocked"
    )
    state["items"]["pi"]["status"] = "blocked"
    result = adapters.prepare_adapter(
        "pi", state, model_alias="qwen", endpoint_port=8129, prompt="x"
    )
    assert result["status"] == "blocked"
    assert "not installed" in result["reason"]
