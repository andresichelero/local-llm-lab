"""Deterministic semantic routing. Endpoint health and price belong elsewhere."""
from __future__ import annotations

from dataclasses import dataclass
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

