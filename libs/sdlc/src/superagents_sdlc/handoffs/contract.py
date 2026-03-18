"""Handoff contract — PersonaHandoff and HandoffResult Pydantic models.

These models must round-trip through ``model_dump_json()`` /
``model_validate_json()``. No Python object references in the payload.
"""

from __future__ import annotations

from pydantic import BaseModel


class PersonaHandoff(BaseModel):
    """Typed, serializable handoff between SDLC personas.

    Attributes:
        source_persona: Originating persona identifier.
        target_persona: Receiving persona identifier.
        artifact_type: Classification of the artifact being handed off.
        artifact_path: Filesystem path to the artifact (str, not Path).
        context_summary: Compressed context for the receiving persona.
        autonomy_level: Current policy level (1, 2, or 3).
        requires_approval: Whether a human gate is required.
        trace_id: OpenTelemetry trace identifier.
        parent_span_id: Span identifier for parent linking.
    """

    source_persona: str
    target_persona: str
    artifact_type: str
    artifact_path: str
    context_summary: str
    autonomy_level: int
    requires_approval: bool
    trace_id: str
    parent_span_id: str


class HandoffResult(BaseModel):
    """Result of a handoff attempt.

    Attributes:
        status: Outcome — "accepted", "rejected", or "pending".
        target_persona: The persona the handoff was sent to.
        trace_id: OpenTelemetry trace identifier for correlation.
    """

    status: str
    target_persona: str
    trace_id: str
