"""Tests for PrioritizationEngine skill."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from superagents_sdlc.skills.base import SkillContext, SkillValidationError
from superagents_sdlc.skills.llm import StubLLMClient
from superagents_sdlc.skills.pm.prioritization_engine import PrioritizationEngine

if TYPE_CHECKING:
    from pathlib import Path


def _make_stub() -> StubLLMClient:
    return StubLLMClient(responses={"items": "## Prioritized Rankings\n1. Feature A\n2. Feature B"})


def _make_context(tmp_path: Path) -> SkillContext:
    return SkillContext(
        artifact_dir=tmp_path,
        parameters={
            "items": "Feature A\nFeature B\nFeature C",
            "product_context": "We build project management tools",
            "goals_context": "Q1 goal: increase retention by 15%",
        },
        trace_id="trace-1",
    )


def test_priority_validate_passes(tmp_path):
    skill = PrioritizationEngine(llm=_make_stub())
    skill.validate(_make_context(tmp_path))


def test_priority_validate_fails_missing_items(tmp_path):
    skill = PrioritizationEngine(llm=_make_stub())
    context = _make_context(tmp_path)
    del context.parameters["items"]
    with pytest.raises(SkillValidationError, match="items"):
        skill.validate(context)


def test_priority_validate_fails_missing_goals(tmp_path):
    skill = PrioritizationEngine(llm=_make_stub())
    context = _make_context(tmp_path)
    del context.parameters["goals_context"]
    with pytest.raises(SkillValidationError, match="goals_context"):
        skill.validate(context)


async def test_priority_execute_writes_artifact(tmp_path):
    stub = _make_stub()
    skill = PrioritizationEngine(llm=stub)
    context = _make_context(tmp_path)

    artifact = await skill.execute(context)

    assert artifact.artifact_type == "backlog"
    assert artifact.metadata["framework"] == "RICE"
    assert (tmp_path / "prioritization.md").exists()


async def test_priority_execute_includes_context_in_prompt(tmp_path):
    stub = _make_stub()
    skill = PrioritizationEngine(llm=stub)
    context = _make_context(tmp_path)

    await skill.execute(context)

    prompt = stub.calls[0][0]
    assert "Feature A" in prompt
    assert "Feature B" in prompt
    assert "increase retention by 15%" in prompt
    assert "project management tools" in prompt


async def test_prioritization_includes_brief_in_prompt(tmp_path):
    stub = _make_stub()
    skill = PrioritizationEngine(llm=stub)
    context = _make_context(tmp_path)
    context.parameters["brief"] = "# Brief\nHigh-impact recurring task feature"

    await skill.execute(context)

    prompt = stub.calls[0][0]
    assert "## Design Brief" in prompt
    assert "High-impact" in prompt
