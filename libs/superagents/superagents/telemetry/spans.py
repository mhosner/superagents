"""Span context managers for personas, skills, handoffs, and approval gates."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

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
