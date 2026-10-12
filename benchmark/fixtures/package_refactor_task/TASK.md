# Package Refactoring Task

Refactor metrics computation into a separate module without breaking the public service interface.

## Requirements
1. Create `src/metrics.py` and implement `summarize_metrics(data: list[float]) -> dict[str, float]`:
   - If `data` is empty, return `{"count": 0.0, "mean": 0.0, "min": 0.0, "max": 0.0}`.
   - If `data` is non-empty, return `{"count": float(len(data)), "mean": float(sum(data) / len(data)), "min": float(min(data)), "max": float(max(data))}`.
2. In `src/service.py`:
   - Re-export `summarize_metrics` from `src.metrics` so callers importing `summarize_metrics` from `src.service` continue to work.
   - Implement `generate_service_summary(records: list[dict]) -> dict[str, float]`:
     Extract numeric `latency` values from records (ignoring any record missing `latency` or where `latency` is `None`), and pass the list of latencies to `summarize_metrics`.
   - Preserve the unchanged helper function: `sanitize_record(record: dict) -> dict`.
3. Unit tests in `tests/test_service.py` must include test methods:
   - `test_summarize_metrics_empty_and_normal`
   - `test_generate_service_summary_filters_missing`
   - `test_service_reexports_metrics`
4. Only changes to `src/metrics.py`, `src/service.py`, and `tests/test_service.py` are allowed.
