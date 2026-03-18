"""Span context managers for personas, skills, handoffs, and approval gates."""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator

    from opentelemetry.trace import Span

from superagents.telemetry.provider import get_tracer


@contextmanager
def persona_span(
    name: str,
    *,
    autonomy_level: int | None = None,
) -> Iterator[Span]:
    """Trace a persona operation.

    Args:
        name: Persona identifier (e.g., ``"product_manager"``).
        autonomy_level: Current policy level (1, 2, or 3).

    Yields:
        The active span for dynamic attribute setting.
    """
    tracer = get_tracer()
    with tracer.start_as_current_span(f"persona.{name}") as span:
        span.set_attribute("persona.name", name)
        if autonomy_level is not None:
            span.set_attribute("autonomy.level", autonomy_level)
        yield span


@contextmanager
def skill_span(name: str) -> Iterator[Span]:
    """Trace a skill execution.

    Args:
        name: Skill identifier (e.g., ``"prd_generator"``).

    Yields:
        The active span for dynamic attribute setting.
    """
    tracer = get_tracer()
    with tracer.start_as_current_span(f"skill.{name}") as span:
        span.set_attribute("skill.name", name)
        yield span


@contextmanager
def handoff_span(
    source: str,
    target: str,
    *,
    artifact_type: str | None = None,
) -> Iterator[Span]:
    """Trace a persona-to-persona handoff.

    Args:
        source: Source persona identifier.
        target: Target persona identifier.
        artifact_type: Type of artifact being handed off.

    Yields:
        The active span for dynamic attribute setting.
    """
    tracer = get_tracer()
    with tracer.start_as_current_span(f"handoff.{source}_to_{target}") as span:
        span.set_attribute("handoff.source", source)
        span.set_attribute("handoff.target", target)
        if artifact_type is not None:
            span.set_attribute("artifact.type", artifact_type)
        yield span


@contextmanager
def approval_gate_span(
    gate_name: str,
    *,
    autonomy_level: int | None = None,
) -> Iterator[Span]:
    """Trace an approval gate decision.

    Sets sentinel defaults for ``approval.required`` and ``approval.outcome``
    so that forgotten attributes show ``"pending"`` in traces rather than
    being invisibly absent.

    Args:
        gate_name: Gate identifier (e.g., ``"prd_review"``).
        autonomy_level: Current policy level (1, 2, or 3).

    Yields:
        The active span. Caller sets ``approval.required``,
        ``approval.outcome``, and ``gate_duration_ms`` after resolution.
    """
    tracer = get_tracer()
    with tracer.start_as_current_span(f"approval_gate.{gate_name}") as span:
        if autonomy_level is not None:
            span.set_attribute("autonomy.level", autonomy_level)
        span.set_attribute("approval.required", "pending")
        span.set_attribute("approval.outcome", "pending")
        yield span
