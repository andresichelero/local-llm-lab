from __future__ import annotations

import unittest

from src.retry import calculate_backoff, execute_with_retry


class RetryPolicyTests(unittest.TestCase):
    def test_calculate_backoff_helper(self):
        self.assertEqual(calculate_backoff(1), 1.0)
        self.assertEqual(calculate_backoff(2), 2.0)
        self.assertEqual(calculate_backoff(3), 4.0)
        self.assertEqual(calculate_backoff(0), 0.0)

    def test_succeeds_on_first_attempt(self):
        calls = []

        def op():
            calls.append(1)
            return "ok"

        res = execute_with_retry(op, (IOError,))
        self.assertEqual(res, "ok")
        self.assertEqual(len(calls), 1)

    def test_retries_transient_and_calls_callback(self):
        attempts = 0
        callbacks = []

        def op():
            nonlocal attempts
            attempts += 1
            if attempts < 3:
                raise ConnectionError(f"fail {attempts}")
            return "success"

        def cb(attempt, exc):
            callbacks.append((attempt, str(exc)))

        res = execute_with_retry(op, (ConnectionError,), max_attempts=3, on_retry=cb)
        self.assertEqual(res, "success")
        self.assertEqual(attempts, 3)
        self.assertEqual(len(callbacks), 2)
        self.assertEqual(callbacks[0], (1, "fail 1"))
        self.assertEqual(callbacks[1], (2, "fail 2"))

    def test_raises_immediately_on_permanent_error(self):
        attempts = 0

        def op():
            nonlocal attempts
            attempts += 1
            raise ValueError("bad argument")

        with self.assertRaises(ValueError):
            execute_with_retry(op, (ConnectionError,), max_attempts=5)
        self.assertEqual(attempts, 1)

    def test_exhausts_retries_and_reraises(self):
        attempts = 0

        def op():
            nonlocal attempts
            attempts += 1
            raise TimeoutError("timeout")

        with self.assertRaises(TimeoutError):
            execute_with_retry(op, (TimeoutError,), max_attempts=3)
        self.assertEqual(attempts, 3)


if __name__ == "__main__":
    unittest.main()
