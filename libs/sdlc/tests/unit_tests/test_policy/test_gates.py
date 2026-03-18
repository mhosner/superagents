"""Tests for ApprovalGate protocol and implementations."""

from superagents_sdlc.handoffs.contract import PersonaHandoff
from superagents_sdlc.policy.gates import (
    ApprovalResult,
    AutoApprovalGate,
    MockApprovalGate,
)


def _make_handoff() -> PersonaHandoff:
    return PersonaHandoff(
        source_persona="pm",
        target_persona="architect",
        artifact_type="prd",
        artifact_path="/artifacts/prd.md",
        context_summary="test",
        autonomy_level=2,
        requires_approval=True,
        trace_id="trace-1",
        parent_span_id="span-1",
    )


def test_auto_gate_always_approves():
    gate = AutoApprovalGate()
    result = gate.evaluate(_make_handoff(), level=2)
    assert result.approved is True
    assert result.outcome == "auto_proceeded"


def test_mock_gate_approves_when_configured():
    gate = MockApprovalGate(should_approve=True)
    result = gate.evaluate(_make_handoff(), level=1)
    assert result.approved is True
    assert result.outcome == "approved"


def test_mock_gate_rejects_when_configured():
    gate = MockApprovalGate(should_approve=False)
    result = gate.evaluate(_make_handoff(), level=1)
    assert result.approved is False
    assert result.outcome == "rejected"


def test_gate_result_has_duration():
    result = ApprovalResult(approved=True, outcome="approved", duration_ms=42)
    assert result.duration_ms == 42
