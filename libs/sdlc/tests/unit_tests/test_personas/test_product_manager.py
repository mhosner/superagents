"""Tests for ProductManagerPersona."""

from __future__ import annotations

from typing import TYPE_CHECKING

from superagents_sdlc.handoffs.contract import PersonaHandoff
from superagents_sdlc.handoffs.registry import PersonaRegistry
from superagents_sdlc.handoffs.transport import InProcessTransport
from superagents_sdlc.personas.product_manager import ProductManagerPersona
from superagents_sdlc.policy.config import PolicyConfig
from superagents_sdlc.policy.engine import PolicyEngine
from superagents_sdlc.policy.gates import AutoApprovalGate
from superagents_sdlc.skills.base import SkillContext
from superagents_sdlc.skills.llm import StubLLMClient

if TYPE_CHECKING:
    from pathlib import Path


def _make_pm(tmp_path: Path) -> ProductManagerPersona:
    stub = StubLLMClient(responses={"idea": "PRD content", "items": "ranked"})
    config = PolicyConfig(autonomy_level=2)
    engine = PolicyEngine(config=config, gate=AutoApprovalGate())
    registry = PersonaRegistry()
    transport = InProcessTransport(registry=registry)
    return ProductManagerPersona(llm=stub, policy_engine=engine, transport=transport)


def test_pm_has_three_skills(tmp_path):
    pm = _make_pm(tmp_path)
    assert "prd_generator" in pm.skills
    assert "prioritization_engine" in pm.skills
    assert "user_story_writer" in pm.skills
    assert len(pm.skills) == 3


async def test_pm_execute_prd_skill(exporter, tmp_path):
    pm = _make_pm(tmp_path)
    context = SkillContext(
        artifact_dir=tmp_path,
        parameters={
            "idea": "Add dark mode",
            "product_context": "SaaS platform",
            "personas_context": "PM Patricia",
            "goals_context": "Reduce churn",
        },
        trace_id="trace-1",
    )
    artifact = await pm.execute_skill("prd_generator", context)
    assert artifact.artifact_type == "prd"


async def test_pm_receive_handoff_does_not_raise(exporter, tmp_path):
    pm = _make_pm(tmp_path)
    handoff = PersonaHandoff(
        source_persona="architect",
        target_persona="product_manager",
        artifact_type="tech_spec",
        artifact_path="/specs/arch.md",
        context_summary="Architecture review",
        autonomy_level=2,
        requires_approval=False,
        trace_id="trace-1",
        parent_span_id="span-1",
    )
    await pm.receive_handoff(handoff)
