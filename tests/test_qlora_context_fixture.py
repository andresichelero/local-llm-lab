from __future__ import annotations

import importlib.util
from collections import UserDict
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "27_generate_qlora_long_context_fixture.py"
SPEC = importlib.util.spec_from_file_location("qlora_long_context_fixture", MODULE_PATH)
qlora_fixture = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(qlora_fixture)


def test_token_ids_accepts_mapping_results():
    assert qlora_fixture.token_ids(UserDict({"input_ids": [1, 2, 3]})) == [1, 2, 3]


def test_build_example_reaches_prompt_and_sequence_targets():
    class CharacterTokenizer:
        def __call__(self, text, **kwargs):
            return UserDict({"input_ids": list(text)})

        def apply_chat_template(self, messages, *, tokenize, add_generation_prompt):
            text = "".join(message["content"] for message in messages)
            if add_generation_prompt:
                text += "<assistant>"
            else:
                text += "<end>"
            return UserDict({"input_ids": list(text)})

    _, prompt_tokens, full_tokens = qlora_fixture.build_example(CharacterTokenizer(), 350, 1024)

    assert prompt_tokens >= 350
    assert full_tokens >= 1024
