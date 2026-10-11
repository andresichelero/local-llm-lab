from benchmark import unsloth_smoke


def test_unsloth_run_requires_finite_losses_and_exact_code_probe():
    valid = "def add(a, b):\n    return a + b"
    invalid = "The sum is 42."

    assert unsloth_smoke.successful_unsloth_run(8, 8, [0.4] * 8, valid)
    assert not unsloth_smoke.successful_unsloth_run(8, 8, [0.4] * 7 + [float("nan")], valid)
    assert not unsloth_smoke.successful_unsloth_run(8, 8, [0.4] * 8, invalid)


def test_load_rows_accepts_transformers_tokenizer_list_output(tmp_path):
    import json

    dataset = tmp_path / "one.jsonl"
    dataset.write_text(json.dumps({"messages": [
        {"role": "user", "content": "question"},
        {"role": "assistant", "content": "answer"},
    ]}) + "\n", encoding="utf-8")

    class ListTokenizer:
        def apply_chat_template(self, messages, **kwargs):
            return [1, 2] if kwargs["add_generation_prompt"] else [1, 2, 3]

    rows = unsloth_smoke.load_rows(dataset, ListTokenizer(), 8)

    assert rows == [{"input_ids": [1, 2, 3], "labels": [-100, -100, 3]}]


def test_token_ids_accepts_mapping_and_direct_tensor_like_results():
    direct = object()

    assert unsloth_smoke.token_ids({"input_ids": [1, 2]}) == [1, 2]
    assert unsloth_smoke.token_ids(direct) is direct


def test_git_provenance_ignores_generated_results_but_detects_source_changes(tmp_path, monkeypatch):
    import subprocess

    repository = tmp_path / "repo"
    repository.mkdir()
    def git(*args):
        subprocess.run(["git", "-C", str(repository), *args], check=True, capture_output=True)

    git("init", "-q")
    git("config", "user.name", "Test")
    git("config", "user.email", "test@example.invalid")
    source = repository / "benchmark.py"
    source.write_text("value = 1\n", encoding="utf-8")
    git("add", "benchmark.py")
    git("commit", "-qm", "initial")
    generated = repository / "results" / "system-audit" / "host-audit.txt"
    generated.parent.mkdir(parents=True)
    generated.write_text("generated audit\n", encoding="utf-8")
    monkeypatch.setattr(unsloth_smoke, "REPOSITORY_ROOT", repository)

    _, dirty_with_only_generated_results = unsloth_smoke.git_provenance()
    assert not dirty_with_only_generated_results

    source.write_text("value = 2\n", encoding="utf-8")
    _, dirty_with_source_change = unsloth_smoke.git_provenance()
    assert dirty_with_source_change
