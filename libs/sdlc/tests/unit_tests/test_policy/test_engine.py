"""Tests for PolicyEngine."""

from superagents_sdlc.handoffs.contract import PersonaHandoff
from superagents_sdlc.policy.config import PolicyConfig
from superagents_sdlc.policy.engine import PolicyEngine
from superagents_sdlc.policy.gates import MockApprovalGate


def _make_handoff(*, artifact_type: str = "prd", source: str = "pm") -> PersonaHandoff:
    return PersonaHandoff(
        source_persona=source,
        target_persona="architect",
        artifact_type=artifact_type,
        artifact_path="/artifacts/out.md",
        context_summary="test",
        autonomy_level=1,
        requires_approval=False,
        trace_id="trace-1",
        parent_span_id="span-1",
    )


async def test_level_1_always_requires_approval(exporter):
    config = PolicyConfig(autonomy_level=1)
    gate = MockApprovalGate(should_approve=True)
    engine = PolicyEngine(config=config, gate=gate)

    result = await engine.evaluate_handoff(_make_handoff(artifact_type="prd"))
    assert result.approved is True
    assert result.outcome == "approved"  # delegated to gate, not auto_proceeded

    result2 = await engine.evaluate_handoff(_make_handoff(artifact_type="code"))
    assert result2.outcome == "approved"


async def test_level_2_auto_proceeds_planning_artifacts(exporter):
    config = PolicyConfig(autonomy_level=2)
    gate = MockApprovalGate(should_approve=True)
    engine = PolicyEngine(config=config, gate=gate)

    result = await engine.evaluate_handoff(_make_handoff(artifact_type="prd"))
    assert result.approved is True
    assert result.outcome == "auto_proceeded"


async def test_level_2_requires_approval_for_code(exporter):
    config = PolicyConfig(autonomy_level=2)
    gate = MockApprovalGate(should_approve=False)
    engine = PolicyEngine(config=config, gate=gate)

    result = await engine.evaluate_handoff(_make_handoff(artifact_type="code"))
    assert result.approved is False
    assert result.outcome == "rejected"


async def test_level_3_auto_proceeds_everything(exporter):
    config = PolicyConfig(autonomy_level=3)
    gate = MockApprovalGate(should_approve=False)  # should never be called
    engine = PolicyEngine(config=config, gate=gate)

    result = await engine.evaluate_handoff(_make_handoff(artifact_type="code"))
    assert result.approved is True
    assert result.outcome == "auto_proceeded"


async def test_engine_emits_approval_gate_span(exporter):
    config = PolicyConfig(autonomy_level=2)
    gate = MockApprovalGate(should_approve=True)
    engine = PolicyEngine(config=config, gate=gate)

    await engine.evaluate_handoff(_make_handoff(artifact_type="prd"))

    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    span = spans[0]
    assert span.name == "approval_gate.pm_to_architect"
    attrs = dict(span.attributes)
    assert attrs["autonomy.level"] == 2
    assert attrs["approval.required"] is False  # planning at L2 = auto
    assert attrs["approval.outcome"] == "auto_proceeded"


async def test_engine_uses_persona_override_level(exporter):
    config = PolicyConfig(autonomy_level=1, overrides={"pm": 3})
    gate = MockApprovalGate(should_approve=False)
    engine = PolicyEngine(config=config, gate=gate)

    result = await engine.evaluate_handoff(_make_handoff(artifact_type="code", source="pm"))
    assert result.approved is True
    assert result.outcome == "auto_proceeded"
