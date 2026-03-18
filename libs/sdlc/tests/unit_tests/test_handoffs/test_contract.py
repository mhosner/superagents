"""Tests for PersonaHandoff and HandoffResult Pydantic models."""

import pytest
from pydantic import ValidationError

from superagents_sdlc.handoffs.contract import HandoffResult, PersonaHandoff


def _make_handoff() -> PersonaHandoff:
    return PersonaHandoff(
        source_persona="product_manager",
        target_persona="architect",
        artifact_type="prd",
        artifact_path="/artifacts/prd.md",
        context_summary="Initial PRD for feature X",
        autonomy_level=2,
        requires_approval=False,
        trace_id="trace-abc",
        parent_span_id="span-123",
    )


def test_handoff_json_round_trip():
    original = _make_handoff()
    json_str = original.model_dump_json()
    restored = PersonaHandoff.model_validate_json(json_str)
    assert restored == original


def test_handoff_result_json_round_trip():
    original = HandoffResult(
        status="accepted",
        target_persona="architect",
        trace_id="trace-abc",
    )
    json_str = original.model_dump_json()
    restored = HandoffResult.model_validate_json(json_str)
    assert restored == original


def test_handoff_validates_required_fields():
    with pytest.raises(ValidationError):
        PersonaHandoff(
            source_persona="pm",
            # missing all other required fields
        )
