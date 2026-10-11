import unittest

from src.text_utils import word_count


class TextUtilsTests(unittest.TestCase):
    def test_word_count(self) -> None:
        self.assertEqual(word_count("two\twords"), 2)


if __name__ == "__main__":
    unittest.main()
