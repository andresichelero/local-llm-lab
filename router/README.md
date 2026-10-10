# Rule-based model router

rules.py handles semantic selection only: it returns an ordered shortlist from task type, complexity, tools, web need, and context size. It does not know API prices, endpoint health, credentials, retries, or rate limits. operational_fallback is a small next step that filters an existing shortlist against health and exclusion sets; it makes no network calls.

Run the deterministic unit tests with:

    python3 -m unittest discover -s tests -v

The initial policy is a baseline for later measurements, not an evidence-backed learned router.
