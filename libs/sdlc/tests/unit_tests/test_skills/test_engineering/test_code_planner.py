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
