"""Held-out behavioral probe suite for dotenv_line_parser task."""
from __future__ import annotations

import unittest

from src.config_parser import normalize_key, parse_assignment


class DotenvLineParserBehavioralProbe(unittest.TestCase):
    def test_normal_assignments_and_whitespace_trimming(self) -> None:
        self.assertEqual(
            parse_assignment("  api_key = secret  "),
            ("api_key", "secret"),
        )

    def test_comments_and_empty_lines_return_none(self) -> None:
        self.assertIsNone(parse_assignment("  # ignored=x"))
        self.assertIsNone(parse_assignment("   "))
        self.assertIsNone(parse_assignment(""))
        self.assertIsNone(parse_assignment(" = empty key"))
        self.assertIsNone(parse_assignment("no_delimiter"))

    def test_first_equals_splitting(self) -> None:
        self.assertEqual(
            parse_assignment("  api_key = a=b  "),
            ("api_key", "a=b"),
        )

    def test_quote_stripping(self) -> None:
        self.assertEqual(
            parse_assignment('name="two words"'),
            ("name", "two words"),
        )
        self.assertEqual(
            parse_assignment("name='two words'"),
            ("name", "two words"),
        )

    def test_normalize_key_preserved_helper(self) -> None:
        self.assertEqual(normalize_key(" api_key "), "API_KEY")


if __name__ == "__main__":
    unittest.main()
