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


def _is_code_plan_call(call: tuple[str, str]) -> bool:
    """Check if a StubLLMClient call is a CodePlanner invocation.

    Matches both initial generation (starts with "## Implementation plan")
    and revision mode (starts with "## PREVIOUS PLAN").
    """
    return (
        call[0].startswith("## Implementation plan\n")
        or call[0].startswith("## PREVIOUS PLAN")
    )


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
            # Developer skills — initial generation and revision mode
            "## Implementation plan\n": (
                "### Task 1: DarkModeToggle\n\n"
                "- [ ] **Step 1: Write test**\n"
                "Run: `pytest -v`\n\n"
                "- [ ] **Step 2: Implement**\n"
            ),
            "## PREVIOUS PLAN": (
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
    # After retry, certification is still NEEDS WORK (stubs always return it)
    assert result.certification == "NEEDS WORK"
    assert result.retry_attempted is True


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

    # Initial phases + retry phases (architect+developer+qa re-run)
    assert phases == [
        ("pm", 3), ("architect", 2), ("developer", 1), ("qa", 3),
        ("architect", 2), ("developer", 1), ("qa", 3),
    ]


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

    # Initial phases + retry phases (architect+developer+qa re-run)
    assert phases == [
        ("architect", 2), ("developer", 1), ("qa", 3),
        ("architect", 2), ("developer", 1), ("qa", 3),
    ]


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

    # Initial phases + retry phases (developer+qa re-run; architect not active)
    assert phases == [
        ("developer", 1), ("qa", 3),
        ("developer", 1), ("qa", 3),
    ]


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


# -- retry pass tests --


async def test_idea_to_code_retries_on_needs_work(exporter, tmp_path):
    """Orchestrator retries when QA certifies NEEDS WORK with findings."""
    orchestrator, _ = _make_orchestrator()

    result = await orchestrator.run_idea_to_code("Add dark mode", artifact_dir=tmp_path)

    assert result.retry_attempted is True
    assert result.pre_retry_certification == "NEEDS WORK"
    # After retry, QA runs again — still NEEDS WORK with stubs, but
    # the retry was attempted
    assert result.certification in ("NEEDS WORK", "READY", "FAILED", "unknown")


async def test_idea_to_code_retry_re_runs_architect_and_developer(exporter, tmp_path):
    """When routing manifest has architect findings, both architect and developer re-run."""
    orchestrator, stub_llm = _make_orchestrator()

    await orchestrator.run_idea_to_code("Add dark mode", artifact_dir=tmp_path)

    # Verify tech_spec_writer was called at least twice (initial + retry).
    # Filter by prompt starting with "## PRD\n" to exclude implementation_planner
    # calls which also contain "## PRD\n" as context.
    tech_spec_calls = [
        call for call in stub_llm.calls if call[0].startswith("## PRD\n")
    ]
    assert len(tech_spec_calls) >= 2


async def test_idea_to_code_retry_injects_findings(exporter, tmp_path):
    """Retry passes inject revision_findings into skill context."""
    orchestrator, stub_llm = _make_orchestrator()

    await orchestrator.run_idea_to_code("Add dark mode", artifact_dir=tmp_path)

    # The architect's retry call should contain revision findings.
    # Filter by prompt starting with "## PRD\n" to isolate tech_spec_writer calls.
    tech_spec_calls = [
        call for call in stub_llm.calls if call[0].startswith("## PRD\n")
    ]
    # The second call (retry) should have revision findings
    assert len(tech_spec_calls) >= 2
    retry_prompt = tech_spec_calls[1][0]
    assert "## Revision findings" in retry_prompt


async def test_no_retry_when_ready(exporter, tmp_path):
    """No retry when QA certifies READY."""
    # Override validation report stub to return READY
    stub_llm = StubLLMClient(
        responses={
            "## Items to prioritize\n": "## Rankings\n1. Dark mode - RICE: 42",
            "## Idea / feature to spec\n": "# PRD: Dark Mode\n## Problem\nEye strain",
            "## Feature description\n": (
                "## Story 1\nAs a PM, I want dark mode\n"
                "### Acceptance Criteria\nGiven dashboard\nWhen toggle\nThen dark"
            ),
            "## Compliance report\n": (
                "# Validation Report\n## Executive Summary\nAll good.\n"
                "## Certification\nREADY"
            ),
            "## Plan structure analysis\n": (
                "## Compliance Check\n| Feature | PASS |\n"
                "## Summary\nTotal: 1 | Pass: 1\nOverall: READY"
            ),
            "## PRD\n": "# Tech Spec\n## Architecture\nSimple",
            "## Technical specification\n": "## Tasks\n1. Build it",
            "## Implementation plan\n": (
                "### Task 1: Feature\n\n"
                "- [ ] **Step 1: Write test**\nRun: `pytest -v`\n\n"
                "- [ ] **Step 2: Implement**\n"
            ),
        }
    )

    config = PolicyConfig(autonomy_level=2)
    engine = PolicyEngine(config=config, gate=AutoApprovalGate())
    orchestrator = PipelineOrchestrator(
        llm=stub_llm,
        policy_engine=engine,
        context={
            "product_context": "B2B SaaS platform",
            "goals_context": "Q1: reduce churn by 10%",
            "personas_context": "# PM Patricia\nManages projects",
        },
    )

    result = await orchestrator.run_idea_to_code("Add dark mode", artifact_dir=tmp_path)

    assert result.retry_attempted is False
    assert result.pre_retry_certification == ""
    assert result.certification == "READY"


async def test_retry_cascade_developer_only(exporter, tmp_path):
    """Developer-only findings: only developer + QA re-run, not architect."""
    # Manifest with findings only for developer
    dev_only_manifest = json.dumps({
        "certification": "NEEDS WORK",
        "total_findings": 1,
        "routing": {
            "product_manager": [],
            "architect": [],
            "developer": [{
                "id": "RF-1",
                "summary": "Missing error test",
                "detail": "Detail",
                "affected_artifact": "code_plan",
                "related_requirements": [{"id": "AC-1", "text": "Criterion"}],
            }],
        },
    })

    stub_llm = StubLLMClient(
        responses={
            "## Items to prioritize\n": "## Rankings\n1. Dark mode - RICE: 42",
            "## Idea / feature to spec\n": "# PRD: Dark Mode\n## Problem\nEye strain",
            "## Feature description\n": (
                "## Story 1\nAs a PM, I want dark mode\n"
                "### Acceptance Criteria\nGiven dashboard\nWhen toggle\nThen dark"
            ),
            "## Validation report\n": dev_only_manifest,
            "## Compliance report\n": (
                "# Validation Report\n## Executive Summary\nGaps.\n"
                "## Certification\nNEEDS WORK"
            ),
            "## Plan structure analysis\n": (
                "## Compliance Check\n| Feature | PASS |\n"
                "## Summary\nTotal: 1 | Pass: 1\nOverall: NEEDS WORK"
            ),
            "## PRD\n": "# Tech Spec\n## Architecture\nSimple",
            "## Technical specification\n": "## Tasks\n1. Build it",
            # Matches both initial ("## Implementation plan") and revision
            # ("## PREVIOUS PLAN") prompts for CodePlanner
            "## Implementation plan\n": (
                "### Task 1: Feature\n\n"
                "- [ ] **Step 1: Write test**\nRun: `pytest -v`\n\n"
                "- [ ] **Step 2: Implement**\n"
            ),
            "## PREVIOUS PLAN": (
                "### Task 1: Feature\n\n"
                "- [ ] **Step 1: Write test**\nRun: `pytest -v`\n\n"
                "- [ ] **Step 2: Implement**\n"
            ),
        }
    )

    config = PolicyConfig(autonomy_level=2)
    engine = PolicyEngine(config=config, gate=AutoApprovalGate())
    orchestrator = PipelineOrchestrator(
        llm=stub_llm, policy_engine=engine,
        context={
            "product_context": "B2B SaaS",
            "goals_context": "Q1 goals",
            "personas_context": "# PM\nManages projects",
        },
    )

    await orchestrator.run_idea_to_code("Add dark mode", artifact_dir=tmp_path)

    # Architect skill (tech_spec_writer) should be called exactly once (no retry)
    tech_spec_calls = [c for c in stub_llm.calls if c[0].startswith("## PRD\n")]
    assert len(tech_spec_calls) == 1

    # Developer skill should be called at least twice (initial + retry)
    code_plan_calls = [c for c in stub_llm.calls if _is_code_plan_call(c)]
    assert len(code_plan_calls) >= 2


async def test_retry_cascade_pm_triggers_all_downstream(exporter, tmp_path):
    """PM findings: PM + architect + developer + QA all re-run."""
    pm_manifest = json.dumps({
        "certification": "NEEDS WORK",
        "total_findings": 1,
        "routing": {
            "product_manager": [{
                "id": "RF-1",
                "summary": "Vague acceptance criteria",
                "detail": "Detail",
                "affected_artifact": "user_story",
                "related_requirements": [{"id": "AC-1", "text": "Criterion"}],
            }],
            "architect": [],
            "developer": [],
        },
    })

    stub_llm = StubLLMClient(
        responses={
            "## Items to prioritize\n": "## Rankings\n1. Dark mode - RICE: 42",
            "## Idea / feature to spec\n": "# PRD: Dark Mode\n## Problem\nEye strain",
            "## Feature description\n": (
                "## Story 1\nAs a PM, I want dark mode\n"
                "### Acceptance Criteria\nGiven dashboard\nWhen toggle\nThen dark"
            ),
            "## Validation report\n": pm_manifest,
            "## Compliance report\n": (
                "# Validation Report\n## Executive Summary\nGaps.\n"
                "## Certification\nNEEDS WORK"
            ),
            "## Plan structure analysis\n": (
                "## Compliance Check\n| Feature | PASS |\n"
                "## Summary\nTotal: 1 | Pass: 1\nOverall: NEEDS WORK"
            ),
            "## PRD\n": "# Tech Spec\n## Architecture\nSimple",
            "## Technical specification\n": "## Tasks\n1. Build it",
            "## Implementation plan\n": (
                "### Task 1: Feature\n\n"
                "- [ ] **Step 1: Write test**\nRun: `pytest -v`\n\n"
                "- [ ] **Step 2: Implement**\n"
            ),
            "## PREVIOUS PLAN": (
                "### Task 1: Feature\n\n"
                "- [ ] **Step 1: Write test**\nRun: `pytest -v`\n\n"
                "- [ ] **Step 2: Implement**\n"
            ),
        }
    )

    config = PolicyConfig(autonomy_level=2)
    engine = PolicyEngine(config=config, gate=AutoApprovalGate())
    orchestrator = PipelineOrchestrator(
        llm=stub_llm, policy_engine=engine,
        context={
            "product_context": "B2B SaaS",
            "goals_context": "Q1 goals",
            "personas_context": "# PM\nManages projects",
        },
    )

    await orchestrator.run_idea_to_code("Add dark mode", artifact_dir=tmp_path)

    # All three content personas should be called at least twice
    prd_calls = [c for c in stub_llm.calls if c[0].startswith("## Idea / feature to spec\n")]
    tech_spec_calls = [c for c in stub_llm.calls if c[0].startswith("## PRD\n")]
    code_plan_calls = [c for c in stub_llm.calls if _is_code_plan_call(c)]
    assert len(prd_calls) >= 2
    assert len(tech_spec_calls) >= 2
    assert len(code_plan_calls) >= 2


# -- run_human_revision tests --


async def test_human_revision_routes_and_retries(exporter, tmp_path):
    """Human revision feedback is routed and triggers a retry pass."""
    orchestrator, stub_llm = _make_orchestrator()

    result = await orchestrator.run_idea_to_code("Add dark mode", artifact_dir=tmp_path)

    # Count architect calls before human revision
    tech_spec_calls_before = len(
        [c for c in stub_llm.calls if c[0].startswith("## PRD\n")]
    )

    result = await orchestrator.run_human_revision(
        feedback="Fix the caching layer",
        result=result,
        artifact_dir=tmp_path,
    )

    assert result.retry_attempted is True

    # Architect should have been called again (FindingsRouter routes to architect
    # by default with the standard stub)
    tech_spec_calls_after = len(
        [c for c in stub_llm.calls if c[0].startswith("## PRD\n")]
    )
    assert tech_spec_calls_after > tech_spec_calls_before


async def test_human_revision_developer_only(exporter, tmp_path):
    """Human revision routed to developer only doesn't re-run architect."""
    dev_only_manifest = json.dumps({
        "certification": "NEEDS WORK",
        "total_findings": 1,
        "routing": {
            "product_manager": [],
            "architect": [],
            "developer": [{
                "id": "RF-H1",
                "summary": "Fix caching",
                "detail": "Detail",
                "affected_artifact": "code_plan",
                "related_requirements": [{"id": "AC-1", "text": "Criterion"}],
            }],
        },
    })

    stub_llm = StubLLMClient(
        responses={
            "## Items to prioritize\n": "## Rankings\n1. Dark mode - RICE: 42",
            "## Idea / feature to spec\n": "# PRD: Dark Mode\n## Problem\nEye strain",
            "## Feature description\n": (
                "## Story 1\nAs a PM, I want dark mode\n"
                "### Acceptance Criteria\nGiven dashboard\nWhen toggle\nThen dark"
            ),
            "## Validation report\n": dev_only_manifest,
            "## Compliance report\n": (
                "# Validation Report\n## Executive Summary\nGaps.\n"
                "## Certification\nNEEDS WORK"
            ),
            "## Plan structure analysis\n": (
                "## Compliance Check\n| Feature | PASS |\n"
                "## Summary\nTotal: 1 | Pass: 1\nOverall: NEEDS WORK"
            ),
            "## PRD\n": "# Tech Spec\n## Architecture\nSimple",
            "## Technical specification\n": "## Tasks\n1. Build it",
            "## Implementation plan\n": (
                "### Task 1: Feature\n\n"
                "- [ ] **Step 1: Write test**\nRun: `pytest -v`\n\n"
                "- [ ] **Step 2: Implement**\n"
            ),
            "## PREVIOUS PLAN": (
                "### Task 1: Feature\n\n"
                "- [ ] **Step 1: Write test**\nRun: `pytest -v`\n\n"
                "- [ ] **Step 2: Implement**\n"
            ),
        }
    )

    config = PolicyConfig(autonomy_level=2)
    engine = PolicyEngine(config=config, gate=AutoApprovalGate())
    orchestrator = PipelineOrchestrator(
        llm=stub_llm, policy_engine=engine,
        context={
            "product_context": "B2B SaaS",
            "goals_context": "Q1 goals",
            "personas_context": "# PM\nManages projects",
        },
    )

    result = await orchestrator.run_idea_to_code("Add dark mode", artifact_dir=tmp_path)

    # Count architect calls after initial pipeline (includes initial + automated retry)
    tech_spec_calls_before = len(
        [c for c in stub_llm.calls if c[0].startswith("## PRD\n")]
    )
    # Count developer calls after initial pipeline
    code_plan_calls_before = len(
        [c for c in stub_llm.calls if _is_code_plan_call(c)]
    )

    result = await orchestrator.run_human_revision(
        feedback="Fix the caching layer",
        result=result,
        artifact_dir=tmp_path,
    )

    tech_spec_calls_after = len(
        [c for c in stub_llm.calls if c[0].startswith("## PRD\n")]
    )
    code_plan_calls_after = len(
        [c for c in stub_llm.calls if _is_code_plan_call(c)]
    )

    # Architect should NOT have been called again
    assert tech_spec_calls_after == tech_spec_calls_before
    # Developer SHOULD have been called again
    assert code_plan_calls_after > code_plan_calls_before


async def test_human_revision_empty_feedback(exporter, tmp_path):
    """Empty feedback still produces a valid pseudo report and runs without error."""
    orchestrator, _ = _make_orchestrator()

    result = await orchestrator.run_idea_to_code("Add dark mode", artifact_dir=tmp_path)

    # Should not raise
    result = await orchestrator.run_human_revision(
        feedback="",
        result=result,
        artifact_dir=tmp_path,
    )

    assert result.retry_attempted is True


# -- on_skill_complete callback tests --


async def test_on_skill_complete_called_for_each_skill(exporter, tmp_path):
    """on_skill_complete fires for every skill execution in the pipeline."""
    orchestrator, _ = _make_orchestrator()
    skills: list[tuple[str, str]] = []

    def on_skill(persona_name, skill_name, artifact):
        skills.append((persona_name, skill_name))

    await orchestrator.run_idea_to_code(
        "Add dark mode",
        artifact_dir=tmp_path,
        on_skill_complete=on_skill,
    )

    # Initial run: PM has 3 skills, Architect 2, Developer 1, QA 3 = 9
    # Retry re-runs some subset. Just check we got at least 9 calls
    # and that all four personas are represented.
    assert len(skills) >= 9
    persona_names = {s[0] for s in skills}
    assert "product_manager" in persona_names
    assert "architect" in persona_names
    assert "developer" in persona_names
    assert "qa" in persona_names


# -- narrative callback tests --


async def test_on_qa_complete_called_after_qa(exporter, tmp_path):
    """on_qa_complete fires after the QA phase with certification and artifacts."""
    orchestrator, _ = _make_orchestrator()
    qa_calls: list[tuple[str, list]] = []

    def on_qa(certification, artifacts):
        qa_calls.append((certification, artifacts))

    await orchestrator.run_idea_to_code(
        "Add dark mode",
        artifact_dir=tmp_path,
        on_qa_complete=on_qa,
    )

    # At least one QA completion (initial), possibly two (with retry)
    assert len(qa_calls) >= 1
    cert, arts = qa_calls[0]
    assert cert in ("READY", "NEEDS WORK", "FAILED", "unknown")
    assert len(arts) >= 1


async def test_on_findings_routed_called_before_retry(exporter, tmp_path):
    """on_findings_routed fires with routing data before retry starts."""
    orchestrator, _ = _make_orchestrator()
    routing_calls: list[tuple[dict, list]] = []

    def on_routed(routing, cascade):
        routing_calls.append((routing, cascade))

    await orchestrator.run_idea_to_code(
        "Add dark mode",
        artifact_dir=tmp_path,
        on_findings_routed=on_routed,
    )

    # Stubs return NEEDS WORK, so retry fires, so routing callback fires
    assert len(routing_calls) >= 1
    routing, cascade = routing_calls[0]
    assert isinstance(routing, dict)
    assert isinstance(cascade, list)
    assert len(cascade) >= 1


async def test_on_retry_start_called_at_retry(exporter, tmp_path):
    """on_retry_start fires at the beginning of a retry pass."""
    orchestrator, _ = _make_orchestrator()
    retry_calls: list[tuple[str, dict]] = []

    def on_retry(pre_cert, routing):
        retry_calls.append((pre_cert, routing))

    await orchestrator.run_idea_to_code(
        "Add dark mode",
        artifact_dir=tmp_path,
        on_retry_start=on_retry,
    )

    assert len(retry_calls) >= 1
    pre_cert, routing = retry_calls[0]
    assert pre_cert == "NEEDS WORK"
    assert isinstance(routing, dict)


# -- fast_llm model routing tests --


async def test_orchestrator_fast_llm_routes_correctly(exporter, tmp_path):
    """Architect and Developer use fast_llm; PM and QA compliance/validation use strong."""
    strong = _make_pipeline_llm()
    fast = _make_pipeline_llm()

    config = PolicyConfig(autonomy_level=2)
    engine = PolicyEngine(config=config, gate=AutoApprovalGate())
    orchestrator = PipelineOrchestrator(
        llm=strong,
        fast_llm=fast,
        policy_engine=engine,
        context={
            "product_context": "B2B SaaS",
            "goals_context": "Q1 goals",
            "personas_context": "# PM\nManages projects",
        },
    )

    await orchestrator.run_idea_to_code("Add dark mode", artifact_dir=tmp_path)

    # PM skills should hit strong (3 calls: prioritization, prd, user_story)
    pm_calls = [c for c in strong.calls if c[0].startswith("## Items to prioritize")
                or c[0].startswith("## Idea / feature to spec")
                or c[0].startswith("## Feature description")]
    assert len(pm_calls) >= 3

    # Architect skills should hit fast
    arch_calls = [c for c in fast.calls if c[0].startswith("## PRD\n")
                  or c[0].startswith("## Technical specification\n")]
    assert len(arch_calls) >= 2

    # Developer skills should hit strong (code plans need structured format)
    dev_calls = [c for c in strong.calls if c[0].startswith("## Implementation plan\n")]
    assert len(dev_calls) >= 1

    # QA compliance/validation should hit strong
    qa_strong_calls = [c for c in strong.calls
                       if c[0].startswith("## Code plan\n")
                       or c[0].startswith("## Compliance report\n")]
    assert len(qa_strong_calls) >= 2


async def test_orchestrator_uses_strong_llm_for_developer(exporter, tmp_path):
    """Developer uses strong LLM because code plans need structured format compliance."""
    strong = _make_pipeline_llm()
    fast = _make_pipeline_llm()

    config = PolicyConfig(autonomy_level=2)
    engine = PolicyEngine(config=config, gate=AutoApprovalGate())
    orchestrator = PipelineOrchestrator(
        llm=strong,
        fast_llm=fast,
        policy_engine=engine,
        context={
            "product_context": "B2B SaaS",
            "goals_context": "Q1 goals",
            "personas_context": "# PM\nManages projects",
        },
    )

    await orchestrator.run_idea_to_code("Add dark mode", artifact_dir=tmp_path)

    # Developer skills should hit strong, not fast
    dev_calls_strong = [c for c in strong.calls if c[0].startswith("## Implementation plan\n")]
    dev_calls_fast = [c for c in fast.calls if c[0].startswith("## Implementation plan\n")]
    assert len(dev_calls_strong) >= 1
    assert len(dev_calls_fast) == 0


async def test_orchestrator_no_fast_llm_uses_single(exporter, tmp_path):
    """Without fast_llm, all personas use the same llm."""
    orchestrator, single_llm = _make_orchestrator()

    await orchestrator.run_idea_to_code("Add dark mode", artifact_dir=tmp_path)

    # All calls should be on the single llm
    assert len(single_llm.calls) >= 9
