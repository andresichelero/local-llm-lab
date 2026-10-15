from __future__ import annotations

import pytest

from benchmark.safe_execution_guard import block_legacy_execution


def test_retired_execution_guard_points_to_canonical_readiness_command() -> None:
    with pytest.raises(RuntimeError) as error:
        block_legacy_execution("benchmark.example.legacy_runner")

    message = str(error.value)
    assert "benchmark.example.legacy_runner is retired" in message
    assert "python -m benchmark.safe_campaign --readiness" in message
    assert "--execute" in message
    assert "Historical records are unchanged" in message
