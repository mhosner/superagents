"""Tests for ArchitectPersona."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

import pytest

from superagents_sdlc.handoffs.contract import PersonaHandoff
from superagents_sdlc.handoffs.registry import PersonaRegistry
from superagents_sdlc.handoffs.transport import InProcessTransport
from superagents_sdlc.personas.architect import ArchitectPersona
from superagents_sdlc.personas.base import BasePersona
from superagents_sdlc.policy.config import PolicyConfig
from superagents_sdlc.policy.engine import PolicyEngine
from superagents_sdlc.policy.gates import AutoApprovalGate
from superagents_sdlc.skills.base import SkillContext, SkillValidationError
from superagents_sdlc.skills.llm import StubLLMClient


class StubDeveloperPersona(BasePersona):
    """Stub developer that stores received handoffs."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.received: list[PersonaHandoff] = []

    async def receive_handoff(self, handoff: PersonaHandoff) -> None:
        self.received.append(handoff)


def _make_stub_llm() -> StubLLMClient:
    return StubLLMClient(
        responses={
            "## PRD\n": "# Tech Spec\n## Architecture\nMicroservices with REST API",
            "## Technical specification\n": "## Tasks\n1. Create model\n2. Build API\n3. Add UI",
        }
    )


def _make_context(tmp_path: Path) -> SkillContext:
    return SkillContext(
        artifact_dir=tmp_path,
        parameters={
            "prd": "# PRD: Dark Mode\n## Problem\nEye strain",
            "user_stories": "As a PM, I want dark mode so I reduce eye strain",
            "product_context": "B2B SaaS project management platform",
        },
        trace_id="trace-1",
    )


def _make_architect(
    tmp_path: Path,
    *,
    stub_llm: StubLLMClient | None = None,
) -> tuple[ArchitectPersona, StubDeveloperPersona, StubLLMClient]:
    llm = stub_llm or _make_stub_llm()
    config = PolicyConfig(autonomy_level=2)
    engine = PolicyEngine(config=config, gate=AutoApprovalGate())
    registry = PersonaRegistry()
    transport = InProcessTransport(registry=registry)

    architect = ArchitectPersona(llm=llm, policy_engine=engine, transport=transport)
    developer = StubDeveloperPersona(
        name="developer",
        skills={},
        policy_engine=PolicyEngine(config=config, gate=AutoApprovalGate()),
        transport=InProcessTransport(registry=registry),
    )
    registry.register(architect)
    registry.register(developer)

    return architect, developer, llm


def test_architect_has_two_skills(tmp_path):
    architect, _, _ = _make_architect(tmp_path)
    assert "tech_spec_writer" in architect.skills
    assert "implementation_planner" in architect.skills
    assert len(architect.skills) == 2


async def test_architect_receive_handoff_stores(exporter, tmp_path):
    architect, _, _ = _make_architect(tmp_path)
    handoff = PersonaHandoff(
        source_persona="product_manager",
        target_persona="architect",
        artifact_type="user_story",
        artifact_path="/stories.md",
        context_summary="Stories ready",
        autonomy_level=2,
        requires_approval=False,
        trace_id="trace-1",
        parent_span_id="span-1",
    )
    await architect.receive_handoff(handoff)
    assert len(architect.received) == 1
    assert architect.received[0].source_persona == "product_manager"


async def test_architect_workflow_runs_two_skills_in_order(exporter, tmp_path):
    architect, _, stub_llm = _make_architect(tmp_path)
    context = _make_context(tmp_path)

    await architect.run_spec_from_prd(context)

    prompts = [call[0] for call in stub_llm.calls]
    assert len(prompts) == 2
    assert "## PRD\n" in prompts[0]
    assert "## Technical specification\n" in prompts[1]


async def test_architect_workflow_returns_two_artifacts(exporter, tmp_path):
    architect, _, _ = _make_architect(tmp_path)
    context = _make_context(tmp_path)

    artifacts = await architect.run_spec_from_prd(context)

    assert len(artifacts) == 2
    assert artifacts[0].artifact_type == "tech_spec"
    assert artifacts[1].artifact_type == "implementation_plan"


async def test_architect_workflow_emits_persona_span(exporter, tmp_path):
    architect, _, _ = _make_architect(tmp_path)
    context = _make_context(tmp_path)

    await architect.run_spec_from_prd(context)

    spans = exporter.get_finished_spans()
    persona_spans = [s for s in spans if s.name == "persona.architect"]
    assert len(persona_spans) == 1

    skill_spans = [s for s in spans if s.name.startswith("skill.")]
    for ss in skill_spans:
        assert ss.parent is not None
        assert ss.parent.span_id == persona_spans[0].context.span_id


async def test_architect_preflight_fails_missing_prd(exporter, tmp_path):
    architect, _, _ = _make_architect(tmp_path)
    context = _make_context(tmp_path)
    del context.parameters["prd"]

    with pytest.raises(SkillValidationError, match="prd"):
        await architect.run_spec_from_prd(context)


async def test_architect_preflight_fails_missing_user_stories(exporter, tmp_path):
    architect, _, _ = _make_architect(tmp_path)
    context = _make_context(tmp_path)
    del context.parameters["user_stories"]

    with pytest.raises(SkillValidationError, match="user_stories"):
        await architect.run_spec_from_prd(context)


async def test_architect_preflight_fails_missing_product_context(exporter, tmp_path):
    architect, _, _ = _make_architect(tmp_path)
    context = _make_context(tmp_path)
    del context.parameters["product_context"]

    with pytest.raises(SkillValidationError, match="product_context"):
        await architect.run_spec_from_prd(context)


async def test_architect_handle_handoff_loads_user_stories(exporter, tmp_path):
    architect, _dev, _ = _make_architect(tmp_path)

    stories_path = tmp_path / "user_stories.md"
    stories_path.write_text("As a PM, I want dark mode")

    handoff = PersonaHandoff(
        source_persona="product_manager",
        target_persona="architect",
        artifact_type="user_story",
        artifact_path=str(stories_path),
        context_summary="Stories ready",
        autonomy_level=2,
        requires_approval=False,
        trace_id="trace-1",
        parent_span_id="span-1",
    )

    output_dir = tmp_path / "architect_output"
    output_dir.mkdir()
    context = SkillContext(
        artifact_dir=output_dir,
        parameters={
            "prd": "# PRD: Dark Mode",
            "product_context": "B2B SaaS platform",
        },
        trace_id="trace-1",
    )

    artifacts = await architect.handle_handoff(handoff, context)

    assert len(artifacts) == 2
    assert context.parameters["user_stories"] == "As a PM, I want dark mode"
