"""Tests for PrdGenerator skill."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from superagents_sdlc.skills.base import SkillContext, SkillValidationError
from superagents_sdlc.skills.llm import StubLLMClient
from superagents_sdlc.skills.pm.prd_generator import PrdGenerator

if TYPE_CHECKING:
    from pathlib import Path


def _make_stub() -> StubLLMClient:
    return StubLLMClient(responses={"idea": "# PRD: Feature X\n## Problem Statement\n..."})


def _make_context(tmp_path: Path) -> SkillContext:
    return SkillContext(
        artifact_dir=tmp_path,
        parameters={
            "idea": "Add dark mode to the dashboard",
            "product_context": "B2B SaaS project management platform",
            "personas_context": "PM Patricia: manages 5 projects, frustrated by eye strain",
            "goals_context": "Q1: reduce churn by 10%",
        },
        trace_id="trace-1",
    )


def test_prd_validate_passes_with_required_context(tmp_path):
    skill = PrdGenerator(llm=_make_stub())
    skill.validate(_make_context(tmp_path))


def test_prd_validate_fails_missing_idea(tmp_path):
    skill = PrdGenerator(llm=_make_stub())
    context = _make_context(tmp_path)
    del context.parameters["idea"]
    with pytest.raises(SkillValidationError, match="idea"):
        skill.validate(context)


async def test_prd_execute_writes_artifact(tmp_path):
    stub = _make_stub()
    skill = PrdGenerator(llm=stub)
    context = _make_context(tmp_path)

    artifact = await skill.execute(context)

    assert (tmp_path / "prd.md").exists()
    assert artifact.path == str(tmp_path / "prd.md")


async def test_prd_execute_includes_context_in_prompt(tmp_path):
    stub = _make_stub()
    skill = PrdGenerator(llm=stub)
    context = _make_context(tmp_path)

    await skill.execute(context)

    prompt = stub.calls[0][0]
    assert "dark mode" in prompt
    assert "B2B SaaS" in prompt
    assert "PM Patricia" in prompt
    assert "reduce churn" in prompt


async def test_prd_execute_returns_correct_artifact_type(tmp_path):
    stub = _make_stub()
    skill = PrdGenerator(llm=stub)
    context = _make_context(tmp_path)

    artifact = await skill.execute(context)

    assert artifact.artifact_type == "prd"
    assert "idea" in artifact.metadata


async def test_prd_includes_revision_findings_in_prompt(tmp_path):
    stub = _make_stub()
    skill = PrdGenerator(llm=stub)
    context = _make_context(tmp_path)
    context.parameters["revision_findings"] = '[{"id":"RF-1","summary":"Vague AC"}]'
    context.parameters["previous_prd"] = "# Old PRD\nVague requirements"

    await skill.execute(context)

    prompt = stub.calls[0][0]
    assert "## Previous PRD" in prompt
    assert "Vague requirements" in prompt
    assert "## Revision findings" in prompt
    assert "Vague AC" in prompt
    # Both come after the core context (idea, product roadmap, etc.)
    prev_idx = prompt.index("## Previous PRD")
    findings_idx = prompt.index("## Revision findings")
    idea_idx = prompt.index("## Idea / feature to spec")
    assert idea_idx < prev_idx
    assert prev_idx < findings_idx
