"""Held-out behavioral probe suite for calculator_division task."""
from __future__ import annotations

import unittest

from src.calculator import add, divide, multiply


class CalculatorBehavioralProbe(unittest.TestCase):
    def test_divide_positive_operands(self) -> None:
        self.assertEqual(divide(10, 2), 5)
        self.assertEqual(divide(7, 2), 3.5)

    def test_divide_negative_operands(self) -> None:
        self.assertEqual(divide(-10, 2), -5)
        self.assertEqual(divide(10, -2), -5)
        self.assertEqual(divide(-10, -2), 5)

    def test_divide_by_zero_raises_value_error(self) -> None:
        with self.assertRaisesRegex(ValueError, "division by zero"):
            divide(10, 0)

    def test_preserved_helpers(self) -> None:
        self.assertEqual(add(2, 3), 5)
        self.assertEqual(multiply(2, 3), 6)


if __name__ == "__main__":
    unittest.main()
