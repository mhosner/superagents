"""Workflow integration tests for ProductManagerPersona.run_idea_to_sprint().

These tests wire up the full Phase 1+2+3 stack with StubLLMClient as the
only fake. Everything else is real: PolicyEngine, InProcessTransport,
PersonaRegistry, telemetry.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from superagents_sdlc.handoffs.registry import PersonaRegistry
from superagents_sdlc.handoffs.transport import InProcessTransport
from superagents_sdlc.personas.base import BasePersona
from superagents_sdlc.personas.product_manager import ProductManagerPersona
from superagents_sdlc.policy.config import PolicyConfig
from superagents_sdlc.policy.engine import PolicyEngine
from superagents_sdlc.policy.gates import AutoApprovalGate, MockApprovalGate
from superagents_sdlc.skills.base import SkillContext
from superagents_sdlc.skills.llm import StubLLMClient

if TYPE_CHECKING:
    from pathlib import Path

    from superagents_sdlc.handoffs.contract import PersonaHandoff


# -- Stub architect persona (handoff target) --


class StubArchitectPersona(BasePersona):
    """Stub architect that stores received handoffs for assertion."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.received: list[PersonaHandoff] = []

    async def receive_handoff(self, handoff: PersonaHandoff) -> None:
        self.received.append(handoff)


# -- Fixtures --


def _make_stub_llm() -> StubLLMClient:
    """Create StubLLMClient with canned responses keyed to each skill's prompt."""
    return StubLLMClient(
        responses={
            "Items to prioritize": "## Rankings\n1. Dark mode - RICE: 42",
            "Idea / feature to spec": "# PRD: Dark Mode\n## Problem\nEye strain",
            "Feature description": (
                "## Story 1\nAs a PM, I want dark mode\n"
                "### Acceptance Criteria\nGiven dashboard\nWhen toggle\nThen dark"
            ),
        }
    )


def _make_context(tmp_path: Path) -> SkillContext:
    return SkillContext(
        artifact_dir=tmp_path,
        parameters={
            "product_context": "B2B SaaS platform",
            "goals_context": "Q1: reduce churn by 10%",
            "personas_context": "# PM Patricia\nManages projects, hates eye strain",
        },
        trace_id="trace-wf",
    )


def _make_stack(
    tmp_path: Path,
    *,
    autonomy_level: int = 2,
    gate=None,
) -> tuple[ProductManagerPersona, StubArchitectPersona, StubLLMClient]:
    """Wire up the full stack and return (pm, architect, stub_llm)."""
    stub_llm = _make_stub_llm()
    if gate is None:
        gate = AutoApprovalGate()
    config = PolicyConfig(autonomy_level=autonomy_level)
    engine = PolicyEngine(config=config, gate=gate)
    registry = PersonaRegistry()
    transport = InProcessTransport(registry=registry)

    pm = ProductManagerPersona(llm=stub_llm, policy_engine=engine, transport=transport)
    architect = StubArchitectPersona(
        name="architect",
        skills={},
        policy_engine=PolicyEngine(config=config, gate=AutoApprovalGate()),
        transport=InProcessTransport(registry=registry),
    )
    registry.register(pm)
    registry.register(architect)

    return pm, architect, stub_llm


# -- Tests --


async def test_workflow_runs_three_skills_in_order(exporter, tmp_path):
    pm, _arch, stub_llm = _make_stack(tmp_path)
    context = _make_context(tmp_path)

    await pm.run_idea_to_sprint("Add dark mode", context)

    # Verify calls were made in order: prioritize, prd, stories
    prompts = [call[0] for call in stub_llm.calls]
    assert len(prompts) == 3
    assert "Items to prioritize" in prompts[0]
    assert "Idea / feature to spec" in prompts[1]
    assert "Feature description" in prompts[2]


async def test_workflow_returns_three_artifacts(exporter, tmp_path):
    pm, _arch, _llm = _make_stack(tmp_path)
    context = _make_context(tmp_path)

    artifacts = await pm.run_idea_to_sprint("Add dark mode", context)

    assert len(artifacts) == 3
    assert artifacts[0].artifact_type == "backlog"
    assert artifacts[1].artifact_type == "prd"
    assert artifacts[2].artifact_type == "user_story"


async def test_workflow_writes_all_artifact_files(exporter, tmp_path):
    pm, _arch, _llm = _make_stack(tmp_path)
    context = _make_context(tmp_path)

    await pm.run_idea_to_sprint("Add dark mode", context)

    assert (tmp_path / "prioritization.md").exists()
    assert (tmp_path / "prd.md").exists()
    assert (tmp_path / "user_stories.md").exists()


async def test_workflow_passes_prd_to_story_writer(exporter, tmp_path):
    pm, _arch, stub_llm = _make_stack(tmp_path)
    context = _make_context(tmp_path)

    await pm.run_idea_to_sprint("Add dark mode", context)

    # The story writer prompt (3rd call) should contain the PRD output
    story_prompt = stub_llm.calls[2][0]
    assert "PRD: Dark Mode" in story_prompt


async def test_workflow_emits_persona_span(exporter, tmp_path):
    pm, _arch, _llm = _make_stack(tmp_path)
    context = _make_context(tmp_path)

    await pm.run_idea_to_sprint("Add dark mode", context)

    spans = exporter.get_finished_spans()
    persona_spans = [s for s in spans if s.name == "persona.product_manager"]
    assert len(persona_spans) == 1

    # Skill spans should be children of the persona span
    persona_span = persona_spans[0]
    skill_spans = [s for s in spans if s.name.startswith("skill.")]
    for skill_span in skill_spans:
        assert skill_span.parent is not None
        assert skill_span.parent.span_id == persona_span.context.span_id


async def test_workflow_emits_handoff_span(exporter, tmp_path):
    pm, _arch, _llm = _make_stack(tmp_path)
    context = _make_context(tmp_path)

    await pm.run_idea_to_sprint("Add dark mode", context)

    spans = exporter.get_finished_spans()
    handoff_spans = [s for s in spans if s.name.startswith("handoff.")]
    assert len(handoff_spans) == 1
    hs = handoff_spans[0]
    assert hs.attributes["handoff.source"] == "product_manager"
    assert hs.attributes["handoff.target"] == "architect"
    assert hs.attributes["artifact.type"] == "user_story"


async def test_workflow_handoff_at_level_2_auto_proceeds(exporter, tmp_path):
    pm, arch, _llm = _make_stack(tmp_path, autonomy_level=2)
    context = _make_context(tmp_path)

    await pm.run_idea_to_sprint("Add dark mode", context)

    # user_story is a planning artifact → auto-proceeds at Level 2
    spans = exporter.get_finished_spans()
    gate_spans = [s for s in spans if s.name.startswith("approval_gate.")]
    assert len(gate_spans) == 1
    assert gate_spans[0].attributes["approval.outcome"] == "auto_proceeded"
    # Architect should have received the handoff
    assert len(arch.received) == 1


async def test_workflow_handoff_at_level_1_requires_approval(exporter, tmp_path):
    pm, arch, _llm = _make_stack(
        tmp_path, autonomy_level=1, gate=MockApprovalGate(should_approve=True)
    )
    context = _make_context(tmp_path)

    await pm.run_idea_to_sprint("Add dark mode", context)

    spans = exporter.get_finished_spans()
    gate_spans = [s for s in spans if s.name.startswith("approval_gate.")]
    assert len(gate_spans) == 1
    assert gate_spans[0].attributes["approval.required"] is True
    assert gate_spans[0].attributes["approval.outcome"] == "approved"
    assert len(arch.received) == 1
