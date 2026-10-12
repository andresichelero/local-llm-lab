from __future__ import annotations

from typing import Callable, TypeVar

T = TypeVar("T")


def calculate_backoff(attempt: int, base: float = 1.0, factor: float = 2.0) -> float:
    """Calculate exponential backoff delay in seconds; preserved helper."""
    if attempt < 1:
        return 0.0
    return base * (factor ** (attempt - 1))


def execute_with_retry(
    operation: Callable[[], T],
    retryable_exceptions: tuple[type[Exception], ...],
    max_attempts: int = 3,
    on_retry: Callable[[int, Exception], None] | None = None,
) -> T:
    """Execute operation with retry logic for specified exception types."""
    raise NotImplementedError
