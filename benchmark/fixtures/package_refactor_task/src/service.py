from __future__ import annotations


def sanitize_record(record: dict) -> dict:
    """Sanitize input record by stripping string values; preserved helper."""
    return {k: v.strip() if isinstance(v, str) else v for k, v in record.items()}


def generate_service_summary(records: list[dict]) -> dict[str, float]:
    """Generate service summary by aggregating latency metrics."""
    raise NotImplementedError
