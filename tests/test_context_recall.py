from __future__ import annotations

import unittest

from benchmark.context_recall import TARGET_CODE, TARGET_STATION, answer_matches, make_prompt


class ContextRecallTests(unittest.TestCase):
    def test_prompt_has_single_midpoint_needle_and_exact_query(self) -> None:
        prompt = make_prompt(9)

        self.assertEqual(prompt.count(TARGET_CODE), 1)
        self.assertEqual(prompt.count(TARGET_STATION), 2)
        self.assertIn("Entry 00004: station=Relay Nacre-17; maintenance_code=FROST-9K2M-VALE-317", prompt)
        self.assertTrue(prompt.endswith(f"Return only the maintenance code for {TARGET_STATION}. If absent, return NOT FOUND."))

    def test_grader_requires_only_the_exact_code(self) -> None:
        self.assertTrue(answer_matches(f"  {TARGET_CODE.lower()}\n"))
        self.assertFalse(answer_matches(f"The code is {TARGET_CODE}"))
        self.assertFalse(answer_matches("NOT FOUND"))

    def test_prompt_rejects_empty_record_sets(self) -> None:
        with self.assertRaisesRegex(ValueError, "positive"):
            make_prompt(0)


if __name__ == "__main__":
    unittest.main()
