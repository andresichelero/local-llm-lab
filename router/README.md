# Rule-based model router

`route(task)` remains the historical semantic shortlist. It includes names such
as cloud destinations and expresses the original policy only; it has no
health, compatibility, deadline, or quality measurements. Keep it and
`operational_fallback(...)` for compatibility with existing callers. They are
not evidence that any listed destination is currently installed, healthy, or
measured.

`route_local(...)` is the offline operational path. The caller supplies an
ordered tuple of `LocalDestination` records and the remaining deadline budget.
Each record states whether the endpoint is local and healthy, whether it
supports tools and the required template, its context limit, and its estimated
duration. The function checks those explicit fields in order and returns the
first eligible name. Names are identifiers only; they do not imply model
quality or capabilities. Supply estimates only when the caller has evidence
for them; this repository currently publishes no measured destination
capability table.

When no destination passes, the result has `destination=None`,
`reason="no_eligible_destination"`, and per-destination rejection reasons
such as `health_failure`, `unsupported_tools`, `unsupported_template`,
`excessive_context`, `deadline_exhaustion`, or `cloud_disabled`. For a web
request, each destination is rejected with `web_disabled`; an empty candidate
list has no per-destination rejection and returns only
`no_eligible_destination`. Deadline budgets and duration estimates must be
finite and non-negative, and a zero remaining budget is exhausted. This
function is pure: it does not call a provider, retry, or route to cloud. A
caller must decide how to surface the explicit failure.

Run the deterministic unit tests with:

    python3 -m unittest discover -s tests -v
