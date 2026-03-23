"""Tests for CodePlanner skill."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from superagents_sdlc.skills.base import SkillContext, SkillValidationError
from superagents_sdlc.skills.engineering.code_planner import CodePlanner
from superagents_sdlc.skills.engineering.plan_parser import extract_tasks
from superagents_sdlc.skills.llm import StubLLMClient

if TYPE_CHECKING:
    from pathlib import Path


def _make_stub() -> StubLLMClient:
    return StubLLMClient(
        responses={
            "## Implementation plan\n": (
                "# Dark Mode Implementation Plan\n\n"
                "> **For agentic workers:** Use superpowers:executing-plans\n"
                "> **Note:** File paths are proposed.\n\n"
                "**Goal:** Add dark mode toggle\n"
                "**Architecture:** React component with CSS variables\n"
                "**Tech Stack:** Python, pytest\n\n"
                "---\n\n"
                "### Task 1: Create DarkModeToggle\n\n"
                "**Files:**\n"
                "- Create: `src/components/toggle.py`\n"
                "- Test: `tests/test_toggle.py`\n\n"
                "- [ ] **Step 1: Write the failing test**\n"
                "```python\n"
                "def test_toggle_switches_theme():\n"
                "    assert toggle() == 'dark'\n"
                "```\n\n"
                "- [ ] **Step 2: Run test**\n"
                "Run: `pytest tests/test_toggle.py -v`\n\n"
                "- [ ] **Step 3: Write implementation**\n"
                "```python\n"
                "def toggle(): return 'dark'\n"
                "```\n\n"
                "- [ ] **Step 4: Verify passes**\n"
                "Run: `pytest tests/test_toggle.py -v`\n"
            ),
        }
    )


def _make_context(tmp_path: Path) -> SkillContext:
    return SkillContext(
        artifact_dir=tmp_path,
        parameters={
            "implementation_plan": "## Tasks\n1. Create data model\n2. Build API",
            "tech_spec": "# Tech Spec\n## Architecture\nREST API with PostgreSQL",
        },
        trace_id="trace-1",
    )


def test_code_planner_validate_passes(tmp_path):
    skill = CodePlanner(llm=_make_stub())
    skill.validate(_make_context(tmp_path))


def test_code_planner_validate_fails_missing_plan(tmp_path):
    skill = CodePlanner(llm=_make_stub())
    context = _make_context(tmp_path)
    del context.parameters["implementation_plan"]
    with pytest.raises(SkillValidationError, match="implementation_plan"):
        skill.validate(context)


async def test_code_planner_execute_writes_artifact(tmp_path):
    stub = _make_stub()
    skill = CodePlanner(llm=stub)
    context = _make_context(tmp_path)

    artifact = await skill.execute(context)

    assert (tmp_path / "code_plan.md").exists()
    assert artifact.artifact_type == "code"


async def test_code_planner_execute_includes_context_in_prompt(tmp_path):
    stub = _make_stub()
    skill = CodePlanner(llm=stub)
    context = _make_context(tmp_path)

    await skill.execute(context)

    prompt = stub.calls[0][0]
    assert "Create data model" in prompt
    assert "REST API" in prompt


async def test_code_planner_output_parseable_as_plan(tmp_path):
    stub = _make_stub()
    skill = CodePlanner(llm=stub)
    context = _make_context(tmp_path)

    await skill.execute(context)

    plan_text = (tmp_path / "code_plan.md").read_text()
    tasks = extract_tasks(plan_text)
    assert len(tasks) >= 1
    assert tasks[0].name == "Create DarkModeToggle"
    assert tasks[0].has_run_command is True
    assert tasks[0].checkboxes == 4


async def test_code_planner_uses_revision_prompt_when_findings_present(tmp_path):
    """When revision_findings is present, the LLM gets the revision system prompt."""
    stub = _make_stub()
    skill = CodePlanner(llm=stub)
    context = _make_context(tmp_path)
    context.parameters["revision_findings"] = '[{"id":"RF-2","summary":"Missing error test"}]'
    context.parameters["previous_code"] = "### Task 1: Old code plan"

    await skill.execute(context)

    system = stub.calls[0][1]
    assert "EDITING an existing plan" in system
    assert "producing an executable TDD" not in system


async def test_code_planner_uses_normal_prompt_without_findings(tmp_path):
    """Without revision_findings, the LLM gets the standard system prompt."""
    stub = _make_stub()
    skill = CodePlanner(llm=stub)
    context = _make_context(tmp_path)

    await skill.execute(context)

    system = stub.calls[0][1]
    assert "producing an executable TDD" in system
    assert "EDITING an existing plan" not in system


async def test_code_planner_revision_prompt_previous_plan_is_primary(tmp_path):
    """In revision mode, previous plan appears before findings with preserve framing."""
    stub = _make_stub()
    skill = CodePlanner(llm=stub)
    context = _make_context(tmp_path)
    context.parameters["revision_findings"] = '[{"id":"RF-2","summary":"Missing error test"}]'
    context.parameters["previous_code"] = "### Task 1: Old code plan"

    await skill.execute(context)

    prompt = stub.calls[0][0]
    assert "Old code plan" in prompt
    assert "Missing error test" in prompt
    # Previous plan comes before findings
    prev_idx = prompt.index("Old code plan")
    findings_idx = prompt.index("Missing error test")
    assert prev_idx < findings_idx
    # Previous plan section header signals preservation
    prev_header = prompt[:prev_idx]
    assert "preserve" in prev_header.lower()


async def test_code_planner_includes_codebase_context(tmp_path):
    stub = _make_stub()
    skill = CodePlanner(llm=stub)
    context = _make_context(tmp_path)
    context.parameters["codebase_context"] = "# Codebase\nFastAPI with SQLAlchemy"

    await skill.execute(context)

    prompt = stub.calls[0][0]
    assert "## Codebase Context" in prompt
    assert "FastAPI" in prompt


def test_code_planner_prompt_requires_component_level_granularity():
    """System prompt must mandate one task per component from the spec."""
    from superagents_sdlc.skills.engineering.code_planner import _SYSTEM_PROMPT

    lower = _SYSTEM_PROMPT.lower()
    assert "one task per" in lower or "separate task" in lower


# -- Phase extraction tests --


def test_extract_phases_from_implementation_plan():
    """Extracts phases split by ## Phase N headers."""
    from superagents_sdlc.skills.engineering.code_planner import _extract_phases

    plan = (
        "## Phase 0: Setup\nCreate project structure\n\n"
        "## Phase 1: Core\nBuild data model\n\n"
        "## Phase 2: Integration\nAdd API endpoints\n\n"
        "## Phase 3: Polish\nAdd logging"
    )
    phases = _extract_phases(plan)
    assert len(phases) == 4
    assert "Setup" in phases[0]
    assert "Core" in phases[1]
    assert "Integration" in phases[2]
    assert "Polish" in phases[3]


def test_extract_phases_single_phase_returns_whole():
    """No phase headers → returns the full plan as one phase."""
    from superagents_sdlc.skills.engineering.code_planner import _extract_phases

    plan = "## Tasks\n1. Create model\n2. Build API\n3. Add UI"
    phases = _extract_phases(plan)
    assert len(phases) == 1
    assert phases[0] == plan


def test_extract_phases_handles_different_header_levels():
    """Both ## Phase and ### Phase headers work."""
    from superagents_sdlc.skills.engineering.code_planner import _extract_phases

    plan = (
        "### Phase 1: Core\nBuild model\n\n"
        "### Phase 2: API\nAdd endpoints"
    )
    phases = _extract_phases(plan)
    assert len(phases) == 2


# -- Phased generation tests --


def _make_phased_stub() -> StubLLMClient:
    """Stub that returns different task blocks per phase prompt."""
    return StubLLMClient(
        responses={
            "## Current phase\n## Phase 0": (
                "### Task 1: Setup\n\n"
                "- [ ] **Step 1: Write test**\n"
                "Run: `pytest -v`\n"
            ),
            "## Current phase\n## Phase 1": (
                "### Task 2: Core\n\n"
                "- [ ] **Step 1: Write test**\n"
                "Run: `pytest -v`\n"
            ),
        }
    )


def _make_phased_context(tmp_path: Path) -> SkillContext:
    return SkillContext(
        artifact_dir=tmp_path,
        parameters={
            "implementation_plan": (
                "## Phase 0: Setup\nCreate project structure\n\n"
                "## Phase 1: Core\nBuild data model"
            ),
            "tech_spec": "# Tech Spec\nREST API",
        },
        trace_id="trace-1",
    )


async def test_phased_generation_calls_llm_per_phase(tmp_path):
    """Multi-phase plan makes one LLM call per phase."""
    stub = _make_phased_stub()
    skill = CodePlanner(llm=stub)
    context = _make_phased_context(tmp_path)

    await skill.execute(context)

    assert len(stub.calls) == 2


async def test_phased_generation_passes_prior_output(tmp_path):
    """Phase 2 call includes Phase 1 output as prior context."""
    stub = _make_phased_stub()
    skill = CodePlanner(llm=stub)
    context = _make_phased_context(tmp_path)

    await skill.execute(context)

    # Second call should contain the first phase's output
    second_prompt = stub.calls[1][0]
    assert "Task 1: Setup" in second_prompt


async def test_phased_generation_concatenates_output(tmp_path):
    """Final artifact contains all phase outputs joined."""
    stub = _make_phased_stub()
    skill = CodePlanner(llm=stub)
    context = _make_phased_context(tmp_path)

    artifact = await skill.execute(context)

    content = (tmp_path / "code_plan.md").read_text()
    assert "Task 1: Setup" in content
    assert "Task 2: Core" in content


async def test_single_phase_uses_existing_behavior(tmp_path):
    """No phase headers in implementation plan → single LLM call."""
    stub = _make_stub()
    skill = CodePlanner(llm=stub)
    context = _make_context(tmp_path)

    await skill.execute(context)

    assert len(stub.calls) == 1


# -- Phased revision tests --


def _make_phased_revision_stub() -> StubLLMClient:
    """Stub for phased revision — handles both preserved and revised phases."""
    return StubLLMClient(
        responses={
            # Phase 0 unchanged — will be preserved verbatim
            "## Current phase\n## Phase 0": (
                "### Task 1: Setup\n\n"
                "- [ ] **Step 1: Write test**\n"
                "Run: `pytest -v`\n"
            ),
            # Phase 1 revised — QA flagged Task 2
            "## PREVIOUS PHASE": (
                "### Task 2: Core (revised)\n\n"
                "- [ ] **Step 1: Write test**\n"
                "Run: `pytest -v`\n\n"
                "### Task 3: Error handling\n\n"
                "- [ ] **Step 1: Write test**\n"
                "Run: `pytest -v`\n"
            ),
        }
    )


async def test_phased_revision_only_regenerates_flagged_phase(tmp_path):
    """Findings targeting Task 2 (in Phase 1) only regenerate Phase 1."""
    stub = StubLLMClient(
        responses={
            # Only matches revision calls — the "## PREVIOUS PHASE" header
            "## PREVIOUS PHASE": (
                "### Task 2: Core (revised)\n\n"
                "- [ ] **Step 1: Write test**\n"
                "Run: `pytest -v`\n\n"
                "### Task 3: Error handling\n\n"
                "- [ ] **Step 1: Write test**\n"
                "Run: `pytest -v`\n"
            ),
        }
    )
    skill = CodePlanner(llm=stub)

    phase0_tasks = (
        "### Task 1: Setup\n\n"
        "- [ ] **Step 1: Write test**\n"
        "Run: `pytest -v`\n"
    )
    phase1_tasks = (
        "### Task 2: Core\n\n"
        "- [ ] **Step 1: Write test**\n"
        "Run: `pytest -v`\n"
    )
    context = SkillContext(
        artifact_dir=tmp_path,
        parameters={
            "implementation_plan": (
                "## Phase 0: Setup\nCreate project\n\n"
                "## Phase 1: Core\nBuild model"
            ),
            "tech_spec": "# Tech Spec\nREST API",
            "revision_findings": '[{"id":"RF-1","summary":"Missing error test","task":"Task 2"}]',
            "previous_code": f"{phase0_tasks}\n\n{phase1_tasks}",
        },
        trace_id="trace-1",
    )

    await skill.execute(context)

    content = (tmp_path / "code_plan.md").read_text()
    # Phase 0 should be preserved verbatim (not regenerated)
    assert "### Task 1: Setup" in content
    # Phase 1 should be revised with new tasks
    assert "### Task 2: Core (revised)" in content
    assert "### Task 3: Error handling" in content
    # Only 1 LLM call — Phase 0 was preserved, only Phase 1 revised
    assert len(stub.calls) == 1
    assert "Missing error test" in stub.calls[0][0]
