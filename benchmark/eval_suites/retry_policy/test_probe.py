"""Held-out behavioral probe suite for retry_policy task."""
from __future__ import annotations

import unittest

import src.retry
from src.retry import calculate_backoff, execute_with_retry


class RetryPolicyBehavioralProbe(unittest.TestCase):
    def test_calculate_backoff_helper(self) -> None:
        self.assertEqual(calculate_backoff(1), 1.0)
        self.assertEqual(calculate_backoff(2), 2.0)
        self.assertEqual(calculate_backoff(3), 4.0)
        if hasattr(src.retry, "jitter_backoff"):
            jitter_fn = getattr(src.retry, "jitter_backoff")
            self.assertIsNotNone(jitter_fn(1))

    def test_retry_on_retryable_exception_and_stops_on_success(self) -> None:
        attempts = 0

        def op() -> int:
            nonlocal attempts
            attempts += 1
            if attempts < 2:
                raise ConnectionResetError("drop")
            return 42

        log: list[tuple[int, str]] = []

        def on_retry(att: int, exc: Exception) -> None:
            log.append((att, type(exc).__name__))

        res = execute_with_retry(
            op,
            (ConnectionResetError,),
            max_attempts=3,
            on_retry=on_retry,
        )
        self.assertEqual(res, 42)
        self.assertEqual(attempts, 2)
        self.assertEqual(log, [(1, "ConnectionResetError")])

    def test_raises_immediately_on_non_retryable_exception(self) -> None:
        unhandled_attempts = 0

        def unhandled_op() -> None:
            nonlocal unhandled_attempts
            unhandled_attempts += 1
            raise ZeroDivisionError("boom")

        with self.assertRaises(ZeroDivisionError):
            execute_with_retry(
                unhandled_op,
                (ConnectionResetError,),
                max_attempts=3,
            )
        self.assertEqual(unhandled_attempts, 1)

    def test_raises_when_retries_exhausted(self) -> None:
        attempts = 0

        def failing_op() -> None:
            nonlocal attempts
            attempts += 1
            raise ConnectionResetError("fail always")

        with self.assertRaises(ConnectionResetError):
            execute_with_retry(
                failing_op,
                (ConnectionResetError,),
                max_attempts=3,
            )
        self.assertEqual(attempts, 3)

    def test_invalid_max_attempts_raises_value_error(self) -> None:
        with self.assertRaisesRegex(ValueError, "max_attempts must be >= 1"):
            execute_with_retry(lambda: 1, (Exception,), max_attempts=0)


if __name__ == "__main__":
    unittest.main()
