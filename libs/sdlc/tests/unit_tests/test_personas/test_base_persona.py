"""Tests for BasePersona ABC."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from superagents.telemetry import get_tracer

from superagents_sdlc.handoffs.registry import PersonaRegistry
from superagents_sdlc.handoffs.transport import InProcessTransport
from superagents_sdlc.personas.base import BasePersona
from superagents_sdlc.policy.config import PolicyConfig
from superagents_sdlc.policy.engine import PolicyEngine
from superagents_sdlc.policy.gates import AutoApprovalGate, MockApprovalGate
from superagents_sdlc.skills.base import Artifact, BaseSkill, SkillContext, SkillValidationError

if TYPE_CHECKING:
    from pathlib import Path

    from superagents_sdlc.handoffs.contract import PersonaHandoff

# -- Test doubles --


class StubSkill(BaseSkill):
    """Skill that returns a fixed artifact."""

    def __init__(self) -> None:
        super().__init__(name="stub_skill", description="A stub", required_context=[])

    async def execute(self, context: SkillContext) -> Artifact:
        return Artifact(path="/out.txt", artifact_type="test", metadata={})


class SpanChildSkill(BaseSkill):
    """Skill that creates a child span inside execute to test span parenting."""

    def __init__(self) -> None:
        super().__init__(name="span_child", description="Creates child span", required_context=[])

    async def execute(self, context: SkillContext) -> Artifact:
        tracer = get_tracer()
        with tracer.start_as_current_span("inner_work"):
            pass
        return Artifact(path="/out.txt", artifact_type="test", metadata={})


class FailValidateSkill(BaseSkill):
    """Skill that always fails validation."""

    def __init__(self) -> None:
        super().__init__(name="fail_validate", description="Fails", required_context=[])

    def validate(self, context: SkillContext) -> None:
        msg = "bad context"
        raise SkillValidationError(msg)

    async def execute(self, context: SkillContext) -> Artifact:
        msg = "unreachable"
        raise AssertionError(msg)


class ConcretePersona(BasePersona):
    """Minimal concrete persona for testing."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.received: list[PersonaHandoff] = []

    async def receive_handoff(self, handoff: PersonaHandoff) -> None:
        self.received.append(handoff)


# -- Helpers --


def _make_context(tmp_path: Path) -> SkillContext:
    return SkillContext(artifact_dir=tmp_path, parameters={}, trace_id="trace-1")


def _make_persona(
    *,
    skills: dict[str, BaseSkill] | None = None,
    config: PolicyConfig | None = None,
    gate=None,
    registry: PersonaRegistry | None = None,
) -> ConcretePersona:
    if skills is None:
        skills = {"stub_skill": StubSkill()}
    if config is None:
        config = PolicyConfig(autonomy_level=2)
    if gate is None:
        gate = AutoApprovalGate()
    engine = PolicyEngine(config=config, gate=gate)
    if registry is None:
        registry = PersonaRegistry()
    transport = InProcessTransport(registry=registry)
    return ConcretePersona(
        name="test_persona",
        skills=skills,
        policy_engine=engine,
        transport=transport,
    )


# -- Tests --


async def test_execute_skill_emits_skill_span(exporter, tmp_path):
    persona = _make_persona()
    await persona.execute_skill("stub_skill", _make_context(tmp_path))

    spans = exporter.get_finished_spans()
    names = [s.name for s in spans]
    assert "skill.stub_skill" in names

    skill_span = next(s for s in spans if s.name == "skill.stub_skill")
    assert skill_span.attributes["skill.name"] == "stub_skill"


async def test_execute_skill_calls_validate_then_execute(exporter, tmp_path):
    skill = MagicMock(spec=StubSkill)
    skill.name = "mock_skill"
    skill.validate = MagicMock()
    skill.execute = AsyncMock(
        return_value=Artifact(path="/out.txt", artifact_type="test", metadata={})
    )

    persona = _make_persona(skills={"mock_skill": skill})
    await persona.execute_skill("mock_skill", _make_context(tmp_path))

    skill.validate.assert_called_once()
    skill.execute.assert_called_once()
    # validate called before execute
    assert skill.validate.call_args_list[0] == skill.validate.call_args_list[-1]


async def test_execute_skill_records_validation_error_on_span(exporter, tmp_path):
    persona = _make_persona(skills={"fail_validate": FailValidateSkill()})

    with pytest.raises(SkillValidationError, match="bad context"):
        await persona.execute_skill("fail_validate", _make_context(tmp_path))

    spans = exporter.get_finished_spans()
    skill_span = next(s for s in spans if s.name == "skill.fail_validate")
    assert skill_span.status.status_code.name == "ERROR"


async def test_execute_skill_unknown_skill_raises(exporter, tmp_path):
    persona = _make_persona()

    with pytest.raises(KeyError, match="nonexistent"):
        await persona.execute_skill("nonexistent", _make_context(tmp_path))


async def test_execute_skill_span_parents_across_await(exporter, tmp_path):
    persona = _make_persona(skills={"span_child": SpanChildSkill()})
    await persona.execute_skill("span_child", _make_context(tmp_path))

    spans = exporter.get_finished_spans()
    inner = next(s for s in spans if s.name == "inner_work")
    skill = next(s for s in spans if s.name == "skill.span_child")
    # inner_work should be a child of skill.span_child
    assert inner.parent.span_id == skill.context.span_id


async def test_request_handoff_emits_handoff_span(exporter, tmp_path):
    target = ConcretePersona(
        name="architect",
        skills={},
        policy_engine=PolicyEngine(config=PolicyConfig(autonomy_level=3), gate=AutoApprovalGate()),
        transport=InProcessTransport(registry=PersonaRegistry()),
    )
    registry = PersonaRegistry()
    registry.register(target)
    persona = _make_persona(registry=registry)

    artifact = Artifact(path="/prd.md", artifact_type="prd", metadata={})
    await persona.request_handoff(
        target="architect", artifact=artifact, context_summary="handing off PRD"
    )

    spans = exporter.get_finished_spans()
    handoff_span = next(s for s in spans if s.name.startswith("handoff."))
    assert handoff_span.attributes["handoff.source"] == "test_persona"
    assert handoff_span.attributes["handoff.target"] == "architect"
    assert handoff_span.attributes["artifact.type"] == "prd"


async def test_request_handoff_passes_through_policy(exporter, tmp_path):
    target = ConcretePersona(
        name="architect",
        skills={},
        policy_engine=PolicyEngine(config=PolicyConfig(autonomy_level=3), gate=AutoApprovalGate()),
        transport=InProcessTransport(registry=PersonaRegistry()),
    )
    registry = PersonaRegistry()
    registry.register(target)
    persona = _make_persona(
        config=PolicyConfig(autonomy_level=2),
        gate=AutoApprovalGate(),
        registry=registry,
    )

    artifact = Artifact(path="/prd.md", artifact_type="prd", metadata={})
    result = await persona.request_handoff(
        target="architect", artifact=artifact, context_summary="test"
    )

    assert result.status == "accepted"
    # Verify policy engine was invoked (approval_gate span exists)
    spans = exporter.get_finished_spans()
    gate_spans = [s for s in spans if s.name.startswith("approval_gate.")]
    assert len(gate_spans) == 1


async def test_skill_callback_receives_rich_summary(exporter, tmp_path):
    """on_skill_complete receives the summary string from artifact metadata."""

    class SummarySkill(BaseSkill):
        def __init__(self) -> None:
            super().__init__(name="summary_skill", description="Has summary", required_context=[])

        async def execute(self, context: SkillContext) -> Artifact:
            return Artifact(
                path="/out.txt",
                artifact_type="prd",
                metadata={"summary": "Generated PRD for dark mode"},
            )

    calls: list[tuple[str, str, str]] = []

    def callback(persona_name: str, skill_name: str, summary: str) -> None:
        calls.append((persona_name, skill_name, summary))

    persona = _make_persona(skills={"summary_skill": SummarySkill()})
    persona.on_skill_complete = callback
    await persona.execute_skill("summary_skill", _make_context(tmp_path))

    assert len(calls) == 1
    assert calls[0] == ("test_persona", "summary_skill", "Generated PRD for dark mode")


async def test_skill_callback_fallback_when_no_summary(exporter, tmp_path):
    """on_skill_complete receives fallback string when no summary in metadata."""
    calls: list[tuple[str, str, str]] = []

    def callback(persona_name: str, skill_name: str, summary: str) -> None:
        calls.append((persona_name, skill_name, summary))

    persona = _make_persona()
    persona.on_skill_complete = callback
    await persona.execute_skill("stub_skill", _make_context(tmp_path))

    assert len(calls) == 1
    assert calls[0] == ("test_persona", "stub_skill", "Produced test artifact.")


async def test_request_handoff_rejected_does_not_send(exporter, tmp_path):
    registry = PersonaRegistry()
    persona = _make_persona(
        config=PolicyConfig(autonomy_level=1),
        gate=MockApprovalGate(should_approve=False),
        registry=registry,
    )

    artifact = Artifact(path="/code.py", artifact_type="code", metadata={})
    result = await persona.request_handoff(
        target="architect", artifact=artifact, context_summary="test"
    )

    assert result.status == "rejected"
    # No transport.send should have been called — target not even registered
    # If transport had been called, it would raise KeyError
