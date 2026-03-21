"""Tests for PipelineOrchestrator."""

from __future__ import annotations

import json

import pytest

from superagents_sdlc.handoffs.contract import PersonaHandoff
from superagents_sdlc.policy.config import PolicyConfig
from superagents_sdlc.policy.engine import PolicyEngine
from superagents_sdlc.policy.gates import AutoApprovalGate
from superagents_sdlc.skills.base import SkillValidationError
from superagents_sdlc.skills.llm import StubLLMClient
from superagents_sdlc.workflows.orchestrator import PipelineOrchestrator, _get_handoff


def _make_pipeline_llm() -> StubLLMClient:
    """StubLLMClient with canned responses for all skills across all personas.

    Key ordering matters: StubLLMClient returns the first matching key.
    More specific keys must come before less specific ones to avoid
    cross-prompt collisions (e.g., "## PRD" appears in multiple prompts).
    """
    return StubLLMClient(
        responses={
            # PM skills — unique prompt section headers
            "## Items to prioritize\n": "## Rankings\n1. Dark mode - RICE: 42",
            "## Idea / feature to spec\n": "# PRD: Dark Mode\n## Problem\nEye strain",
            "## Feature description\n": (
                "## Story 1\nAs a PM, I want dark mode\n"
                "### Acceptance Criteria\nGiven dashboard\nWhen toggle\nThen dark"
            ),
            # QA skills — must come before Architect/Developer keys because
            # QA prompts contain "## Code plan" and "## Technical specification"
            # which would collide with Architect/Developer keys if checked first.
            "## Compliance report\n": (
                "# Validation Report\n"
                "## Executive Summary\nPartial coverage.\n"
                "## Certification\nNEEDS WORK"
            ),
            "## Plan structure analysis\n": (
                "## Compliance Check\n"
                "| Dark mode toggle | PASS |\n"
                "## Summary\nTotal: 1 | Pass: 1\n"
                "Overall: NEEDS WORK"
            ),
            # FindingsRouter — must come before other keys containing "## Validation report"
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
            # Architect skills
            "## PRD\n": "# Tech Spec\n## Architecture\nMicroservices with REST API",
            "## Technical specification\n": ("## Tasks\n1. Create model\n2. Build API\n3. Add UI"),
            # Developer skills
            "## Implementation plan\n": (
                "### Task 1: DarkModeToggle\n\n"
                "- [ ] **Step 1: Write test**\n"
                "Run: `pytest -v`\n\n"
                "- [ ] **Step 2: Implement**\n"
            ),
        }
    )


def _make_orchestrator(
    *,
    autonomy_level: int = 2,
) -> tuple[PipelineOrchestrator, StubLLMClient]:
    stub_llm = _make_pipeline_llm()
    config = PolicyConfig(autonomy_level=autonomy_level)
    engine = PolicyEngine(config=config, gate=AutoApprovalGate())

    orchestrator = PipelineOrchestrator(
        llm=stub_llm,
        policy_engine=engine,
        context={
            "product_context": "B2B SaaS platform",
            "goals_context": "Q1: reduce churn by 10%",
            "personas_context": "# PM Patricia\nManages projects, hates eye strain",
        },
    )
    return orchestrator, stub_llm


async def test_idea_to_code_returns_eight_artifacts(exporter, tmp_path):
    orchestrator, _ = _make_orchestrator()

    result = await orchestrator.run_idea_to_code("Add dark mode", artifact_dir=tmp_path)

    assert len(result.artifacts) == 9
    types = [a.artifact_type for a in result.artifacts]
    assert types == [
        "backlog",
        "prd",
        "user_story",
        "tech_spec",
        "implementation_plan",
        "code",
        "compliance_report",
        "validation_report",
        "routing_manifest",
    ]


async def test_idea_to_code_creates_persona_directories(exporter, tmp_path):
    orchestrator, _ = _make_orchestrator()

    await orchestrator.run_idea_to_code("Add dark mode", artifact_dir=tmp_path)

    assert (tmp_path / "pm").is_dir()
    assert (tmp_path / "architect").is_dir()
    assert (tmp_path / "developer").is_dir()
    assert (tmp_path / "qa").is_dir()


async def test_idea_to_code_returns_certification(exporter, tmp_path):
    orchestrator, _ = _make_orchestrator()

    result = await orchestrator.run_idea_to_code("Add dark mode", artifact_dir=tmp_path)

    assert result.certification != "skipped"
    assert result.certification == "NEEDS WORK"


async def test_idea_to_code_context_overrides(exporter, tmp_path):
    orchestrator, stub_llm = _make_orchestrator()

    await orchestrator.run_idea_to_code(
        "Add dark mode",
        artifact_dir=tmp_path,
        context_overrides={"personas_context": "# Override Persona\nDifferent persona"},
    )

    first_prompt = stub_llm.calls[0][0]
    assert "Override Persona" in first_prompt


async def test_idea_to_code_emits_telemetry(exporter, tmp_path):
    orchestrator, _ = _make_orchestrator()

    await orchestrator.run_idea_to_code("Add dark mode", artifact_dir=tmp_path)

    spans = exporter.get_finished_spans()
    persona_names = {s.name for s in spans if s.name.startswith("persona.")}
    assert len(persona_names) == 4
    assert "persona.product_manager" in persona_names
    assert "persona.qa" in persona_names

    handoff_spans = [s for s in spans if s.name.startswith("handoff.")]
    assert len(handoff_spans) == 3


async def test_idea_to_code_per_persona_grouping(exporter, tmp_path):
    orchestrator, _ = _make_orchestrator()

    result = await orchestrator.run_idea_to_code("Add dark mode", artifact_dir=tmp_path)

    assert len(result.pm) == 3
    assert len(result.architect) == 2
    assert len(result.developer) == 1
    assert len(result.qa) == 3


# -- run_spec_from_prd tests --


async def test_spec_from_prd_skips_pm(exporter, tmp_path):
    orchestrator, _ = _make_orchestrator()

    prd_path = tmp_path / "input_prd.md"
    prd_path.write_text("# PRD: Dark Mode\n## Problem\nEye strain")

    stories_path = tmp_path / "input_stories.md"
    stories_path.write_text("As a PM, I want dark mode so I reduce eye strain")

    result = await orchestrator.run_spec_from_prd(
        str(prd_path),
        user_stories_path=str(stories_path),
        artifact_dir=tmp_path / "output",
    )

    assert result.pm == []
    assert len(result.architect) == 2
    assert len(result.developer) == 1
    assert len(result.qa) == 3


async def test_spec_from_prd_returns_five_artifacts(exporter, tmp_path):
    orchestrator, _ = _make_orchestrator()

    prd_path = tmp_path / "input_prd.md"
    prd_path.write_text("# PRD: Dark Mode\n## Problem\nEye strain")

    stories_path = tmp_path / "input_stories.md"
    stories_path.write_text("As a PM, I want dark mode")

    result = await orchestrator.run_spec_from_prd(
        str(prd_path),
        user_stories_path=str(stories_path),
        artifact_dir=tmp_path / "output",
    )

    assert len(result.artifacts) == 6
    types = [a.artifact_type for a in result.artifacts]
    assert types == [
        "tech_spec",
        "implementation_plan",
        "code",
        "compliance_report",
        "validation_report",
        "routing_manifest",
    ]


async def test_spec_from_prd_emits_two_handoff_spans(exporter, tmp_path):
    orchestrator, _ = _make_orchestrator()

    prd_path = tmp_path / "input_prd.md"
    prd_path.write_text("# PRD: Dark Mode")

    stories_path = tmp_path / "input_stories.md"
    stories_path.write_text("As a PM, I want dark mode")

    await orchestrator.run_spec_from_prd(
        str(prd_path),
        user_stories_path=str(stories_path),
        artifact_dir=tmp_path / "output",
    )

    spans = exporter.get_finished_spans()
    handoff_spans = [s for s in spans if s.name.startswith("handoff.")]
    sources = [
        (s.attributes["handoff.source"], s.attributes["handoff.target"]) for s in handoff_spans
    ]
    assert ("architect", "developer") in sources
    assert ("developer", "qa") in sources
    assert len(handoff_spans) == 2


# -- run_plan_from_spec tests --


async def test_plan_from_spec_skips_pm_and_architect(exporter, tmp_path):
    orchestrator, _ = _make_orchestrator()

    plan_path = tmp_path / "input_plan.md"
    plan_path.write_text("## Tasks\n1. Create model\n2. Build API")

    spec_path = tmp_path / "input_spec.md"
    spec_path.write_text("# Tech Spec\nREST API with PostgreSQL")

    stories_path = tmp_path / "input_stories.md"
    stories_path.write_text("As a PM, I want dark mode")

    result = await orchestrator.run_plan_from_spec(
        implementation_plan_path=str(plan_path),
        tech_spec_path=str(spec_path),
        user_stories_path=str(stories_path),
        artifact_dir=tmp_path / "output",
    )

    assert result.pm == []
    assert result.architect == []
    assert len(result.developer) == 1
    assert len(result.qa) == 3


async def test_plan_from_spec_returns_three_artifacts(exporter, tmp_path):
    orchestrator, _ = _make_orchestrator()

    plan_path = tmp_path / "input_plan.md"
    plan_path.write_text("## Tasks\n1. Create model")

    spec_path = tmp_path / "input_spec.md"
    spec_path.write_text("# Tech Spec\nREST API")

    stories_path = tmp_path / "input_stories.md"
    stories_path.write_text("As a PM, I want dark mode")

    result = await orchestrator.run_plan_from_spec(
        implementation_plan_path=str(plan_path),
        tech_spec_path=str(spec_path),
        user_stories_path=str(stories_path),
        artifact_dir=tmp_path / "output",
    )

    assert len(result.artifacts) == 4
    types = [a.artifact_type for a in result.artifacts]
    assert types == ["code", "compliance_report", "validation_report", "routing_manifest"]


async def test_plan_from_spec_with_user_stories(exporter, tmp_path):
    orchestrator, _ = _make_orchestrator()

    plan_path = tmp_path / "input_plan.md"
    plan_path.write_text("## Tasks\n1. Create model")

    spec_path = tmp_path / "input_spec.md"
    spec_path.write_text("# Tech Spec\nREST API")

    stories_path = tmp_path / "input_stories.md"
    stories_path.write_text("As a PM, I want dark mode so I reduce eye strain")

    result = await orchestrator.run_plan_from_spec(
        implementation_plan_path=str(plan_path),
        tech_spec_path=str(spec_path),
        user_stories_path=str(stories_path),
        artifact_dir=tmp_path / "output",
    )

    assert len(result.qa) == 3
    assert result.certification != "skipped"


async def test_plan_from_spec_without_user_stories_fails_qa(exporter, tmp_path):
    orchestrator, _ = _make_orchestrator()

    plan_path = tmp_path / "input_plan.md"
    plan_path.write_text("## Tasks\n1. Create model")

    spec_path = tmp_path / "input_spec.md"
    spec_path.write_text("# Tech Spec\nREST API")

    with pytest.raises(SkillValidationError, match="user_stories"):
        await orchestrator.run_plan_from_spec(
            implementation_plan_path=str(plan_path),
            tech_spec_path=str(spec_path),
            artifact_dir=tmp_path / "output",
        )


# -- on_phase_complete callback tests --


async def test_idea_to_code_calls_phase_callback(exporter, tmp_path):
    orchestrator, _ = _make_orchestrator()
    phases: list[tuple[str, int]] = []

    def on_phase(name, artifacts):
        phases.append((name, len(artifacts)))

    await orchestrator.run_idea_to_code(
        "Add dark mode", artifact_dir=tmp_path, on_phase_complete=on_phase
    )

    assert phases == [("pm", 3), ("architect", 2), ("developer", 1), ("qa", 3)]


async def test_spec_from_prd_calls_phase_callback(exporter, tmp_path):
    orchestrator, _ = _make_orchestrator()
    phases: list[tuple[str, int]] = []

    prd_path = tmp_path / "input_prd.md"
    prd_path.write_text("# PRD: Dark Mode\n## Problem\nEye strain")

    stories_path = tmp_path / "input_stories.md"
    stories_path.write_text("As a PM, I want dark mode")

    def on_phase(name, artifacts):
        phases.append((name, len(artifacts)))

    await orchestrator.run_spec_from_prd(
        str(prd_path),
        user_stories_path=str(stories_path),
        artifact_dir=tmp_path / "output",
        on_phase_complete=on_phase,
    )

    assert phases == [("architect", 2), ("developer", 1), ("qa", 3)]


async def test_plan_from_spec_calls_phase_callback(exporter, tmp_path):
    orchestrator, _ = _make_orchestrator()
    phases: list[tuple[str, int]] = []

    plan_path = tmp_path / "input_plan.md"
    plan_path.write_text("## Tasks\n1. Create model")

    spec_path = tmp_path / "input_spec.md"
    spec_path.write_text("# Tech Spec\nREST API")

    stories_path = tmp_path / "input_stories.md"
    stories_path.write_text("As a PM, I want dark mode")

    def on_phase(name, artifacts):
        phases.append((name, len(artifacts)))

    await orchestrator.run_plan_from_spec(
        implementation_plan_path=str(plan_path),
        tech_spec_path=str(spec_path),
        user_stories_path=str(stories_path),
        artifact_dir=tmp_path / "output",
        on_phase_complete=on_phase,
    )

    assert phases == [("developer", 1), ("qa", 3)]


# -- handoff assertion test --


async def test_orchestrator_asserts_handoff_source(exporter, tmp_path):
    """Orchestrator catches wrong handoff source in received list."""
    orchestrator, _ = _make_orchestrator()

    fake_handoff = PersonaHandoff(
        source_persona="wrong_source",
        target_persona="architect",
        artifact_type="user_story",
        artifact_path="/fake.md",
        context_summary="fake",
        autonomy_level=2,
        requires_approval=False,
        trace_id="trace-1",
        parent_span_id="span-1",
    )
    orchestrator._architect.received.clear()
    orchestrator._architect.received.append(fake_handoff)

    with pytest.raises(RuntimeError, match="Expected handoff from 'product_manager'"):
        _get_handoff(orchestrator._architect, "product_manager")


# -- retry field tests --


async def test_idea_to_code_result_has_retry_fields(exporter, tmp_path):
    orchestrator, _ = _make_orchestrator()

    result = await orchestrator.run_idea_to_code("Add dark mode", artifact_dir=tmp_path)

    assert hasattr(result, "retry_attempted")
    assert hasattr(result, "pre_retry_certification")
    assert isinstance(result.retry_attempted, bool)
    assert isinstance(result.pre_retry_certification, str)
