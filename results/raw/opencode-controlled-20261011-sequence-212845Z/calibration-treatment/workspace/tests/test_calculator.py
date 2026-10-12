import unittest

from src.calculator import add, multiply, divide


class CalculatorTests(unittest.TestCase):
    def test_add(self) -> None:
        self.assertEqual(add(2, 3), 5)

    def test_multiply(self) -> None:
        self.assertEqual(multiply(2, 3), 6)

    def test_divide_positive(self) -> None:
        self.assertEqual(divide(6, 3), 2.0)

    def test_divide_negative(self) -> None:
        self.assertEqual(divide(-6, 3), -2.0)
        self.assertEqual(divide(6, -3), -2.0)

    def test_divide_by_zero(self) -> None:
        with self.assertRaises(ValueError):
            divide(5, 0)


if __name__ == "__main__":
    unittest.main()
