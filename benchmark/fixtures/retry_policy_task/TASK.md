# Retry Policy Task

Implement `execute_with_retry(operation, retryable_exceptions: tuple[type[Exception], ...], max_attempts: int = 3, on_retry: Callable[[int, Exception], None] | None = None)` in `src/retry.py`.

## Requirements
1. Call `operation()`. If it returns successfully, return that result immediately.
2. If an exception is raised that is an instance of `retryable_exceptions`:
   - If attempts remain (total attempts `< max_attempts`), invoke `on_retry(attempt, exception)` if `on_retry` is provided. The `attempt` argument is 1-indexed (e.g. 1 for the first failure). Then retry the operation.
   - If all `max_attempts` have failed, re-raise the last exception encountered.
3. If an exception is raised that is NOT an instance of `retryable_exceptions`, do NOT retry; let it raise immediately.
4. If `max_attempts <= 0`, raise `ValueError("max_attempts must be >= 1")`.
5. Preserve unchanged helper: `calculate_backoff(attempt: int, base: float = 1.0, factor: float = 2.0) -> float` in `src/retry.py`.
6. Unit tests in `tests/test_retry.py` must include test methods:
   - `test_succeeds_on_first_attempt`
   - `test_retries_transient_and_calls_callback`
   - `test_raises_immediately_on_permanent_error`
   - `test_exhausts_retries_and_reraises`
