from __future__ import annotations

import unittest

from benchmark.qlora_smoke import successful_training


class QLoRASuccessTests(unittest.TestCase):
    def test_requires_all_steps_finite_loss_and_passing_code_probe(self) -> None:
        losses = [0.5] * 7 + [0.2]
        self.assertTrue(successful_training(8, 8, losses, True))
        self.assertFalse(successful_training(8, 8, losses, False))
        self.assertFalse(successful_training(7, 8, losses[:-1], True))
        self.assertFalse(successful_training(8, 8, [0.5] * 7 + [float("nan")], True))


if __name__ == "__main__":
    unittest.main()
