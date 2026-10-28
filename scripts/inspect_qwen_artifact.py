"""Read GGUF metadata/tensor layout without loading the model onto a GPU."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys


def main():
    source = Path(
        "/home/foxtrot/local-llm-benchmark/tools/llama.cpp-v0.7.0-620d2225c/gguf-py"
    )
    sys.path.insert(0, str(source))
    from gguf import GGUFReader

    reader = GGUFReader(sys.argv[1])

    def field(name):
        item = reader.fields.get(name)
        return item.contents() if item is not None else None

    architecture = field("general.architecture")
    hashed = {}
    for name in (
        "tokenizer.chat_template",
        "tokenizer.ggml.tokens",
        "tokenizer.ggml.merges",
        "tokenizer.ggml.token_type",
        "tokenizer.ggml.bos_token_id",
        "tokenizer.ggml.eos_token_id",
    ):
        value = field(name)
        if value is not None:
            hashed[name] = hashlib.sha256(
                json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()
            ).hexdigest()
    result = {
        "architecture": architecture,
        "embedding_length": field(str(architecture) + ".embedding_length"),
        "block_count": field(str(architecture) + ".block_count"),
        "native_context": field(str(architecture) + ".context_length"),
        "metadata_sha256": hashed,
        "mtp_present": any(
            "mtp" in t.name or "nextn" in t.name for t in reader.tensors
        ),
        "tensors": [
            {
                "name": t.name,
                "type": t.tensor_type.name,
                "shape": t.shape.tolist(),
                "bytes": t.n_bytes,
            }
            for t in reader.tensors
        ],
    }
    print(json.dumps(result))


if __name__ == "__main__":
    main()
