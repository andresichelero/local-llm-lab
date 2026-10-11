import unittest

from src.config_parser import parse_assignment


class ConfigParserTests(unittest.TestCase):
    def test_ignores_blank_and_comment_lines(self):
        self.assertIsNone(parse_assignment(" \t\n"))
        self.assertIsNone(parse_assignment("  # note=x"))
        self.assertIsNone(parse_assignment("no separator"))
        self.assertIsNone(parse_assignment(" = value"))

    def test_splits_on_first_equals_and_trims(self):
        self.assertEqual(parse_assignment("  api_key = a=b  "), ("api_key", "a=b"))

    def test_strips_matching_quotes(self):
        self.assertEqual(parse_assignment('name="two words"'), ("name", "two words"))
        self.assertEqual(parse_assignment("name='two words'"), ("name", "two words"))
