"""Fail-closed guard for retired model-execution entry points."""
from __future__ import annotations


def block_legacy_execution(entrypoint: str) -> None:
    """Prevent execution outside the source-bound canonical campaign."""
    raise RuntimeError(
        f"{entrypoint} is retired for model execution; use "
        "`python -m benchmark.safe_campaign --readiness` and, only after a fresh READY result, "
        "`python -m benchmark.safe_campaign --execute`. Historical records are unchanged."
    )
