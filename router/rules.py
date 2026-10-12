"""Deterministic semantic routing. Endpoint health and price belong elsewhere."""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Literal

TaskType = Literal["coding", "research", "classification", "summary", "general"]
Complexity = Literal["low", "medium", "high"]


@dataclass(frozen=True)
class Task:
    task_type: TaskType
    complexity: Complexity
    needs_tools: bool = False
    needs_web: bool = False
    context_tokens: int = 0


@dataclass(frozen=True)
class Route:
    candidates: tuple[str, ...]
    reason: str
    routing_layer: str = "semantic"


@dataclass(frozen=True)
class LocalDestination:
    """Caller-supplied observed capabilities for one destination."""

    name: str
    healthy: bool
    supports_tools: bool
    supported_templates: frozenset[str]
    max_context_tokens: int
    estimated_seconds: float
    is_local: bool = True


@dataclass(frozen=True)
class LocalRoute:
    """Outcome of pure local eligibility filtering; no destination is invoked."""

    destination: str | None
    reason: str
    rejected: tuple[tuple[str, str], ...] = ()
    routing_layer: str = "operational_local"


def route(task: Task) -> Route:
    """Return an ordered model shortlist; this function never calls a provider."""
    if task.context_tokens < 0:
        raise ValueError("context_tokens must be non-negative")
    if task.needs_web or task.task_type == "research":
        return Route(("deepseek", "luna", "sol"), "Research/web work benefits from a frontier or web-enabled worker.")
    if task.complexity == "high":
        return Route(("sol", "claude", "local-heavy"), "High-complexity work starts with a stronger planner/reviewer.")
    if task.task_type == "coding" and task.needs_tools:
        return Route(("local-heavy", "deepseek", "luna"), "Tool-driven coding prefers a local tool-capable worker, then lower-cost fallbacks.")
    if task.context_tokens > 20000:
        return Route(("local-heavy", "sol", "claude"), "Long context needs a destination selected for its context budget.")
    if task.task_type in {"classification", "summary"} or task.complexity == "low":
        return Route(("local-small", "deepseek", "luna"), "Bounded low-complexity work prefers a compact worker.")
    return Route(("local-small", "local-heavy", "luna"), "Default route starts with the local small model.")


def operational_fallback(candidates: tuple[str, ...], healthy: set[str], excluded: set[str] | None = None) -> str | None:
    """Select the first healthy semantic candidate after operational filtering."""
    excluded = excluded or set()
    return next((name for name in candidates if name in healthy and name not in excluded), None)


def route_local(
    task: Task,
    destinations: tuple[LocalDestination, ...],
    *,
    remaining_deadline_seconds: float,
    required_template: str | None = None,
) -> LocalRoute:
    """Choose the first explicitly eligible local destination without calling it.

    ``destinations`` is ordered by the caller. Their names carry no quality or
    capability meaning; eligibility comes only from the supplied fields.
    ``remaining_deadline_seconds`` is the budget left for this operation.
    """
    if task.context_tokens < 0:
        raise ValueError("context_tokens must be non-negative")
    if not math.isfinite(remaining_deadline_seconds) or remaining_deadline_seconds < 0:
        raise ValueError("remaining_deadline_seconds must be finite and non-negative")

    rejected: list[tuple[str, str]] = []
    for destination in destinations:
        if destination.max_context_tokens < 0:
            raise ValueError("max_context_tokens must be non-negative")
        if not math.isfinite(destination.estimated_seconds) or destination.estimated_seconds < 0:
            raise ValueError("estimated_seconds must be finite and non-negative")

        if not destination.is_local:
            reason = "cloud_disabled"
        elif not destination.healthy:
            reason = "health_failure"
        elif task.needs_web:
            reason = "web_disabled"
        elif task.needs_tools and not destination.supports_tools:
            reason = "unsupported_tools"
        elif required_template is not None and required_template not in destination.supported_templates:
            reason = "unsupported_template"
        elif task.context_tokens > destination.max_context_tokens:
            reason = "excessive_context"
        elif remaining_deadline_seconds == 0 or destination.estimated_seconds > remaining_deadline_seconds:
            reason = "deadline_exhaustion"
        else:
            return LocalRoute(destination.name, "eligible", tuple(rejected))
        rejected.append((destination.name, reason))

    return LocalRoute(None, "no_eligible_destination", tuple(rejected))

