"""Superagents telemetry — OpenTelemetry instrumentation primitives."""

from superagents.telemetry.provider import get_tracer, init_telemetry, reset_telemetry
from superagents.telemetry.spans import (
    approval_gate_span,
    handoff_span,
    persona_span,
    skill_span,
)

__all__ = [
    "approval_gate_span",
    "get_tracer",
    "handoff_span",
    "init_telemetry",
    "persona_span",
    "reset_telemetry",
    "skill_span",
]
