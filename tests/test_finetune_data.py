import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "benchmark"))

from finetune_lora import (  # noqa: E402
    IGNORE_INDEX,
    ByteTokenizer,
    batch_schedule,
    build_dataset,
    collate,
    dataset_sha256,
    encode_example,
)


class FinetuneDataTests(unittest.TestCase):
    def test_dataset_is_deterministic_for_a_seed(self):
        self.assertEqual(build_dataset(32, 1234), build_dataset(32, 1234))
        self.assertEqual(dataset_sha256(build_dataset(32, 1234)), dataset_sha256(build_dataset(32, 1234)))

    def test_seed_changes_order_but_not_content(self):
        a, b = build_dataset(32, 1), build_dataset(32, 2)
        self.assertNotEqual(a, b)
        self.assertEqual(sorted(a, key=repr), sorted(b, key=repr))

    def test_dataset_size_and_unique_function_names(self):
        examples = build_dataset(32, 1234)
        self.assertEqual(len(examples), 32)
        names = {ex["prompt"].split("`")[1] for ex in examples}
        self.assertEqual(len(names), 32)

    def test_reference_completions_define_the_named_function(self):
        for ex in build_dataset(10, 7):
            name = ex["prompt"].split("`")[1]
            self.assertIn(f"def {name}(", ex["completion"])

    def test_prompt_is_masked_and_completion_ends_with_eos(self):
        tok = ByteTokenizer()
        example = {"prompt": "Write f.", "completion": "def f(x):\n    return x\n"}
        ids, labels = encode_example(tok, example, max_len=512, eos_id=tok.eos_id)
        self.assertEqual(len(ids), len(labels))
        prompt_len = len(tok.encode("Write f.\n"))
        self.assertTrue(all(label == IGNORE_INDEX for label in labels[:prompt_len]))
        self.assertEqual(labels[prompt_len:], ids[prompt_len:])
        self.assertEqual(labels[-1], tok.eos_id)

    def test_truncation_that_removes_completion_is_an_error(self):
        tok = ByteTokenizer()
        example = {"prompt": "x" * 50, "completion": "y"}
        with self.assertRaises(ValueError):
            encode_example(tok, example, max_len=20, eos_id=tok.eos_id)

    def test_collate_pads_inputs_mask_and_labels(self):
        batch = [([1, 2, 3], [IGNORE_INDEX, 2, 3]), ([4], [4])]
        out = collate(batch, pad_id=99)
        self.assertEqual(out["input_ids"], [[1, 2, 3], [4, 99, 99]])
        self.assertEqual(out["attention_mask"], [[1, 1, 1], [1, 0, 0]])
        self.assertEqual(out["labels"], [[IGNORE_INDEX, 2, 3], [4, IGNORE_INDEX, IGNORE_INDEX]])

    def test_batch_schedule_is_deterministic_and_covers_dataset_each_pass(self):
        schedule = batch_schedule(encoded_count=8, batch_size=2, micro_batches=4, seed=5)
        self.assertEqual(schedule, batch_schedule(8, 2, 4, 5))
        self.assertEqual(len(schedule), 4)
        first_pass = sorted(i for batch in schedule[:4] for i in batch)
        self.assertEqual(first_pass, list(range(8)))


if __name__ == "__main__":
    unittest.main()
