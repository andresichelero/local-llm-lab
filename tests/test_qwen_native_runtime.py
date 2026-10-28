import json

from benchmark.qwen_native_runtime import stage_native_runtime


def test_stage_native_runtime_copies_only_allowlisted_sources_outside_repo(tmp_path):
    repo = tmp_path / "repo"
    source = repo / "benchmark"
    source.mkdir(parents=True)
    expected = (
        "qwen_native_driver.py",
        "qwen_native_gateway.py",
        "qwen_native_protocols.py",
        "qwen_native_mcp.py",
    )
    for name in expected:
        (source / name).write_text(f"# trusted source: {name}\n", encoding="utf-8")
    (source / "unrelated.py").write_text("not mounted\n", encoding="utf-8")
    adapter = {"status": "ready", "argv": ["/usr/bin/example"]}
    episode = tmp_path / "episode"
    episode.mkdir()

    runtime = stage_native_runtime(episode, repo, adapter)

    assert runtime.is_dir()
    assert repo not in runtime.parents
    assert {path.name for path in runtime.iterdir()} == {*expected, "adapter.json"}
    assert all((runtime / name).read_text() == f"# trusted source: {name}\n" for name in expected)
    assert json.loads((runtime / "adapter.json").read_text()) == adapter

