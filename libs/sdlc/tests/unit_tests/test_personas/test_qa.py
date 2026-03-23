"""Tests for QAPersona."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from superagents_sdlc.handoffs.contract import PersonaHandoff
from superagents_sdlc.handoffs.registry import PersonaRegistry
from superagents_sdlc.handoffs.transport import InProcessTransport
from superagents_sdlc.personas.qa import QAPersona
from superagents_sdlc.policy.config import PolicyConfig
from superagents_sdlc.policy.engine import PolicyEngine
from superagents_sdlc.policy.gates import AutoApprovalGate
from superagents_sdlc.skills.base import SkillContext, SkillValidationError
from superagents_sdlc.skills.llm import StubLLMClient

if TYPE_CHECKING:
    from pathlib import Path


def _make_stub_llm() -> StubLLMClient:
    return StubLLMClient(
        responses={
            # FindingsRouter — must come before "## Code plan" because the
            # FindingsRouter prompt also contains "## Code plan"
            "## Validation report\n": json.dumps({
                "certification": "NEEDS WORK",
                "total_findings": 1,
                "routing": {
                    "product_manager": [],
                    "architect": [{
                        "id": "RF-1",
                        "summary": "Minor spec gap",
                        "detail": "Detail text",
                        "affected_artifact": "tech_spec",
                        "related_requirements": [{"id": "AC-1", "text": "Criterion"}],
                    }],
                    "developer": [],
                },
            }),
            "## Code plan\n": (
                "## Compliance Check\n"
                "| Dark mode toggle | PASS |\n"
                "| Theme persistence | FAIL |\n"
                "## Summary\nTotal: 2 | Pass: 1 | Fail: 1\n"
                "Overall: NEEDS WORK"
            ),
            "## Compliance report\n": (
                "# Validation Report\n"
                "## Executive Summary\nPartial coverage.\n"
                "## Certification\nNEEDS WORK"
            ),
        }
    )


def _make_qa(
    tmp_path: Path,
    *,
    stub_llm: StubLLMClient | None = None,
) -> tuple[QAPersona, StubLLMClient]:
    llm = stub_llm or _make_stub_llm()
    config = PolicyConfig(autonomy_level=2)
    engine = PolicyEngine(config=config, gate=AutoApprovalGate())
    registry = PersonaRegistry()
    transport = InProcessTransport(registry=registry)

    qa = QAPersona(llm=llm, policy_engine=engine, transport=transport)
    registry.register(qa)
    return qa, llm


def _make_context(tmp_path: Path) -> SkillContext:
    return SkillContext(
        artifact_dir=tmp_path,
        parameters={
            "code_plan": "## Task 1: DarkModeToggle\n### RED\ntest_toggle",
            "user_stories": "As a PM, I want dark mode so I reduce eye strain",
            "tech_spec": "# Tech Spec\n## Architecture\nREST API with PostgreSQL",
        },
        trace_id="trace-1",
    )


def test_qa_has_three_skills(tmp_path):
    qa, _ = _make_qa(tmp_path)
    assert "spec_compliance_checker" in qa.skills
    assert "validation_report_generator" in qa.skills
    assert "findings_router" in qa.skills
    assert len(qa.skills) == 3


async def test_qa_receive_handoff_stores(exporter, tmp_path):
    qa, _ = _make_qa(tmp_path)
    handoff = PersonaHandoff(
        source_persona="developer",
        target_persona="qa",
        artifact_type="code",
        artifact_path="/code_plan.md",
        context_summary="Code plan ready",
        autonomy_level=2,
        requires_approval=False,
        trace_id="trace-1",
        parent_span_id="span-1",
    )
    await qa.receive_handoff(handoff)
    assert len(qa.received) == 1
    assert qa.received[0].source_persona == "developer"


async def test_qa_workflow_runs_three_skills_in_order(exporter, tmp_path):
    qa, stub_llm = _make_qa(tmp_path)
    context = _make_context(tmp_path)

    await qa.run_validation(context)

    prompts = [call[0] for call in stub_llm.calls]
    assert len(prompts) == 3
    assert "## Code plan\n" in prompts[0]
    assert "## Compliance report\n" in prompts[1]
    assert "## Validation report\n" in prompts[2]


async def test_qa_workflow_returns_three_artifacts(exporter, tmp_path):
    qa, _ = _make_qa(tmp_path)
    context = _make_context(tmp_path)

    artifacts = await qa.run_validation(context)

    assert len(artifacts) == 3
    assert artifacts[0].artifact_type == "compliance_report"
    assert artifacts[1].artifact_type == "validation_report"
    assert artifacts[2].artifact_type == "routing_manifest"


async def test_qa_workflow_emits_persona_span(exporter, tmp_path):
    qa, _ = _make_qa(tmp_path)
    context = _make_context(tmp_path)

    await qa.run_validation(context)

    spans = exporter.get_finished_spans()
    persona_spans = [s for s in spans if s.name == "persona.qa"]
    assert len(persona_spans) == 1

    skill_spans = [s for s in spans if s.name.startswith("skill.")]
    for ss in skill_spans:
        assert ss.parent is not None
        assert ss.parent.span_id == persona_spans[0].context.span_id


async def test_qa_preflight_fails_missing_context(exporter, tmp_path):
    qa, _ = _make_qa(tmp_path)
    context = SkillContext(
        artifact_dir=tmp_path,
        parameters={
            "user_stories": "stories",
            "tech_spec": "spec",
        },
        trace_id="trace-1",
    )

    with pytest.raises(SkillValidationError, match="code_plan"):
        await qa.run_validation(context)


async def test_qa_handle_handoff_without_user_stories_path(exporter, tmp_path):
    qa, _ = _make_qa(tmp_path)

    code_plan_path = tmp_path / "code_plan.md"
    code_plan_path.write_text("## Task 1: Toggle\n- [ ] Step 1\nRun: pytest")

    spec_path = tmp_path / "tech_spec.md"
    spec_path.write_text("# Tech Spec\nREST API")

    handoff = PersonaHandoff(
        source_persona="developer",
        target_persona="qa",
        artifact_type="code",
        artifact_path=str(code_plan_path),
        context_summary="Code plan ready",
        autonomy_level=2,
        requires_approval=False,
        trace_id="trace-1",
        parent_span_id="span-1",
        metadata={
            "tech_spec_path": str(spec_path),
            "user_stories_path": "",
        },
    )

    output_dir = tmp_path / "qa_output"
    output_dir.mkdir()
    context = SkillContext(
        artifact_dir=output_dir,
        parameters={"user_stories": "Pre-loaded stories"},
        trace_id="trace-1",
    )

    artifacts = await qa.handle_handoff(handoff, context)
    assert len(artifacts) == 3


async def test_qa_uses_fast_llm_for_findings_router(exporter, tmp_path):
    """FindingsRouter uses fast_llm; compliance and validation use strong llm."""
    strong = _make_stub_llm()
    fast = _make_stub_llm()

    config = PolicyConfig(autonomy_level=2)
    engine = PolicyEngine(config=config, gate=AutoApprovalGate())
    registry = PersonaRegistry()
    transport = InProcessTransport(registry=registry)

    qa = QAPersona(llm=strong, fast_llm=fast, policy_engine=engine, transport=transport)
    registry.register(qa)
    context = _make_context(tmp_path)

    await qa.run_validation(context)

    # strong should have compliance + validation calls (2)
    assert len(strong.calls) == 2
    # fast should have the findings_router call (1)
    assert len(fast.calls) == 1
    assert "## Validation report\n" in fast.calls[0][0]


async def test_qa_no_fast_llm_uses_single_llm(exporter, tmp_path):
    """When fast_llm is not provided, all skills use the same llm."""
    llm = _make_stub_llm()
    qa, _ = _make_qa(tmp_path, stub_llm=llm)
    context = _make_context(tmp_path)

    await qa.run_validation(context)

    # All 3 calls on the single llm
    assert len(llm.calls) == 3
