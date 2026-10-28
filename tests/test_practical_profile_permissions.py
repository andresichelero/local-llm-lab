"""The agent permission layer must retain the offline task restrictions."""

from benchmark.practical_runtime_v2 import make_opencode_profile


def test_build_agent_does_not_override_denied_network_and_question_tools():
    config = make_opencode_profile(
        "fixture", {"alias": "fixture"},
        {"id": "baseline", "context_tokens": 16384, "cache_prompt": False},
    )
    agent_permissions = config["agent"]["build"]["permission"]
    for name in ("webfetch", "websearch", "question"):
        assert config["permission"][name] == "deny"
        assert agent_permissions.get(name) == "deny"
