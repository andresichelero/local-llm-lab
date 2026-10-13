"""Held-out behavioral probe suite for whitespace_normalization task."""
from __future__ import annotations

import unittest

from src.text_utils import normalize_whitespace, word_count


class WhitespaceNormalizationBehavioralProbe(unittest.TestCase):
    def test_mixed_whitespace_and_tabs_newlines(self) -> None:
        self.assertEqual(
            normalize_whitespace("  alpha\tbeta\n gamma  "),
            "alpha beta gamma",
        )

    def test_unicode_whitespace_preservation(self) -> None:
        self.assertEqual(
            normalize_whitespace("\u00a0café\u2003x"),
            "café x",
        )

    def test_empty_and_whitespace_only_strings(self) -> None:
        self.assertEqual(normalize_whitespace(" \t\n"), "")
        self.assertEqual(normalize_whitespace(""), "")

    def test_word_count_preserved_helper(self) -> None:
        self.assertEqual(word_count("two\twords"), 2)


if __name__ == "__main__":
    unittest.main()
