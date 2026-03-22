"""Tests for ImplementationPlanner skill."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from superagents_sdlc.skills.base import SkillContext, SkillValidationError
from superagents_sdlc.skills.engineering.implementation_planner import ImplementationPlanner
from superagents_sdlc.skills.llm import StubLLMClient

if TYPE_CHECKING:
    from pathlib import Path


def _make_stub() -> StubLLMClient:
    return StubLLMClient(
        responses={"tech_spec": "## Tasks\n1. Create data model\n2. Build API\n3. Add UI"}
    )


def _make_context(tmp_path: Path) -> SkillContext:
    return SkillContext(
        artifact_dir=tmp_path,
        parameters={
            "tech_spec": "# Tech Spec\n## Architecture\nREST API with PostgreSQL",
            "user_stories": "As a PM, I want dark mode so I reduce eye strain",
        },
        trace_id="trace-1",
    )


def test_planner_validate_passes(tmp_path):
    skill = ImplementationPlanner(llm=_make_stub())
    skill.validate(_make_context(tmp_path))


def test_planner_validate_fails_missing_spec(tmp_path):
    skill = ImplementationPlanner(llm=_make_stub())
    context = _make_context(tmp_path)
    del context.parameters["tech_spec"]
    with pytest.raises(SkillValidationError, match="tech_spec"):
        skill.validate(context)


async def test_planner_execute_writes_artifact(tmp_path):
    stub = _make_stub()
    skill = ImplementationPlanner(llm=stub)
    context = _make_context(tmp_path)

    artifact = await skill.execute(context)

    assert (tmp_path / "implementation_plan.md").exists()
    assert artifact.artifact_type == "implementation_plan"


async def test_planner_execute_includes_context_in_prompt(tmp_path):
    stub = _make_stub()
    skill = ImplementationPlanner(llm=stub)
    context = _make_context(tmp_path)

    await skill.execute(context)

    prompt = stub.calls[0][0]
    assert "REST API" in prompt
    assert "PostgreSQL" in prompt
    assert "dark mode" in prompt


async def test_implementation_planner_includes_codebase_context(tmp_path):
    stub = _make_stub()
    skill = ImplementationPlanner(llm=stub)
    context = _make_context(tmp_path)
    context.parameters["codebase_context"] = "# Codebase\nDjango app with PostgreSQL"

    await skill.execute(context)

    prompt = stub.calls[0][0]
    assert "## Codebase Context" in prompt
    assert "Django app" in prompt
