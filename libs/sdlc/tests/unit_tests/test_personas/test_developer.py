"""Tests for DeveloperPersona."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from superagents_sdlc.handoffs.contract import PersonaHandoff
from superagents_sdlc.handoffs.registry import PersonaRegistry
from superagents_sdlc.handoffs.transport import InProcessTransport
from superagents_sdlc.personas.base import BasePersona
from superagents_sdlc.personas.developer import DeveloperPersona
from superagents_sdlc.policy.config import PolicyConfig
from superagents_sdlc.policy.engine import PolicyEngine
from superagents_sdlc.policy.gates import AutoApprovalGate
from superagents_sdlc.skills.base import SkillContext, SkillValidationError
from superagents_sdlc.skills.llm import StubLLMClient


def _make_stub_llm() -> StubLLMClient:
    return StubLLMClient(
        responses={
            "implementation_plan": (
                "## Task 1\n### RED\ntest_toggle\n### GREEN\ndef toggle(): pass"
            ),
        }
    )


def _make_developer(
    tmp_path: Path,
    *,
    stub_llm: StubLLMClient | None = None,
) -> tuple[DeveloperPersona, StubLLMClient]:
    llm = stub_llm or _make_stub_llm()
    config = PolicyConfig(autonomy_level=2)
    engine = PolicyEngine(config=config, gate=AutoApprovalGate())
    registry = PersonaRegistry()
    transport = InProcessTransport(registry=registry)

    dev = DeveloperPersona(llm=llm, policy_engine=engine, transport=transport)
    registry.register(dev)
    return dev, llm


def _make_context(tmp_path: Path) -> SkillContext:
    return SkillContext(
        artifact_dir=tmp_path,
        parameters={
            "implementation_plan": "## Tasks\n1. Create model\n2. Build API",
            "tech_spec": "# Tech Spec\n## Architecture\nREST API with PostgreSQL",
        },
        trace_id="trace-1",
    )


def test_developer_has_one_skill(tmp_path):
    dev, _ = _make_developer(tmp_path)
    assert "code_planner" in dev.skills
    assert len(dev.skills) == 1


async def test_developer_receive_handoff_stores(exporter, tmp_path):
    dev, _ = _make_developer(tmp_path)
    handoff = PersonaHandoff(
        source_persona="architect",
        target_persona="developer",
        artifact_type="architecture",
        artifact_path="/plan.md",
        context_summary="Plan ready",
        autonomy_level=2,
        requires_approval=False,
        trace_id="trace-1",
        parent_span_id="span-1",
    )
    await dev.receive_handoff(handoff)
    assert len(dev.received) == 1


async def test_developer_workflow_returns_code_plan(exporter, tmp_path):
    dev, _ = _make_developer(tmp_path)
    context = _make_context(tmp_path)

    artifacts = await dev.run_plan_from_spec(context)

    assert len(artifacts) == 1
    assert artifacts[0].artifact_type == "code"
    assert (tmp_path / "code_plan.md").exists()


async def test_developer_workflow_emits_persona_span(exporter, tmp_path):
    dev, _ = _make_developer(tmp_path)
    context = _make_context(tmp_path)

    await dev.run_plan_from_spec(context)

    spans = exporter.get_finished_spans()
    persona_spans = [s for s in spans if s.name == "persona.developer"]
    assert len(persona_spans) == 1


async def test_developer_preflight_fails_missing_context(exporter, tmp_path):
    dev, _ = _make_developer(tmp_path)
    context = SkillContext(
        artifact_dir=tmp_path,
        parameters={"tech_spec": "some spec"},
        trace_id="trace-1",
    )

    with pytest.raises(SkillValidationError, match="implementation_plan"):
        await dev.run_plan_from_spec(context)


async def test_developer_handle_handoff_loads_tech_spec_from_metadata(exporter, tmp_path):
    dev, _stub_llm = _make_developer(tmp_path)

    plan_path = tmp_path / "implementation_plan.md"
    plan_path.write_text("## Tasks\n1. Create model\n2. Build API")

    spec_path = tmp_path / "tech_spec.md"
    spec_path.write_text("# Tech Spec\n## Architecture\nREST API with PostgreSQL")

    handoff = PersonaHandoff(
        source_persona="architect",
        target_persona="developer",
        artifact_type="architecture",
        artifact_path=str(plan_path),
        context_summary="Plan ready",
        autonomy_level=2,
        requires_approval=False,
        trace_id="trace-1",
        parent_span_id="span-1",
        metadata={"tech_spec_path": str(spec_path)},
    )

    output_dir = tmp_path / "dev_output"
    output_dir.mkdir()
    context = SkillContext(artifact_dir=output_dir, parameters={}, trace_id="trace-1")

    artifacts = await dev.handle_handoff(handoff, context)

    assert context.parameters["implementation_plan"] == "## Tasks\n1. Create model\n2. Build API"
    assert "REST API" in context.parameters["tech_spec"]
    assert len(artifacts) == 1
    assert artifacts[0].artifact_type == "code"


class StubQAPersona(BasePersona):
    """Stub QA that stores received handoffs."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.received: list[PersonaHandoff] = []

    async def receive_handoff(self, handoff: PersonaHandoff) -> None:
        self.received.append(handoff)


async def test_developer_conditional_handoff_to_qa(exporter, tmp_path):
    """When QA is registered, Developer hands off with full metadata."""
    llm = _make_stub_llm()
    config = PolicyConfig(autonomy_level=2)
    engine = PolicyEngine(config=config, gate=AutoApprovalGate())
    registry = PersonaRegistry()
    transport = InProcessTransport(registry=registry)

    dev = DeveloperPersona(llm=llm, policy_engine=engine, transport=transport)
    qa = StubQAPersona(
        name="qa",
        skills={},
        policy_engine=PolicyEngine(config=config, gate=AutoApprovalGate()),
        transport=InProcessTransport(registry=registry),
    )
    registry.register(dev)
    registry.register(qa)

    context = SkillContext(
        artifact_dir=tmp_path,
        parameters={
            "implementation_plan": "## Tasks\n1. Create model",
            "tech_spec": "# Tech Spec\nREST API",
            "tech_spec_path": "/artifacts/spec.md",
            "user_stories_path": "/artifacts/stories.md",
            "implementation_plan_path": "/artifacts/plan.md",
            "prd_path": "/artifacts/prd.md",
        },
        trace_id="trace-1",
    )

    await dev.run_plan_from_spec(context)

    assert len(qa.received) == 1
    handoff = qa.received[0]
    assert handoff.source_persona == "developer"
    assert handoff.target_persona == "qa"
    assert handoff.artifact_type == "code"
    assert handoff.metadata["tech_spec_path"] == "/artifacts/spec.md"
    assert handoff.metadata["user_stories_path"] == "/artifacts/stories.md"
    assert handoff.metadata["implementation_plan_path"] == "/artifacts/plan.md"
    assert handoff.metadata["prd_path"] == "/artifacts/prd.md"


async def test_developer_no_handoff_without_qa(exporter, tmp_path):
    """When QA is not registered, Developer skips handoff silently."""
    dev, _ = _make_developer(tmp_path)
    context = _make_context(tmp_path)

    artifacts = await dev.run_plan_from_spec(context)

    assert len(artifacts) == 1
    # No handoff span should exist for developer→qa
    spans = exporter.get_finished_spans()
    handoff_spans = [s for s in spans if s.name.startswith("handoff.")]
    dev_to_qa = [s for s in handoff_spans if "qa" in str(s.attributes.get("handoff.target", ""))]
    assert len(dev_to_qa) == 0
