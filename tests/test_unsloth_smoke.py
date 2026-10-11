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
