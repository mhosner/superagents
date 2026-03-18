"""Tests for UserStoryWriter skill."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from superagents_sdlc.skills.base import SkillContext, SkillValidationError
from superagents_sdlc.skills.llm import StubLLMClient
from superagents_sdlc.skills.pm.user_story_writer import UserStoryWriter

if TYPE_CHECKING:
    from pathlib import Path


def _make_stub() -> StubLLMClient:
    return StubLLMClient(
        responses={
            "feature_description": (
                "## User Story 1\n"
                "As a PM, I want dark mode, So that I reduce eye strain\n"
                "### Acceptance Criteria\n"
                "Given the dashboard is open\nWhen I toggle dark mode\nThen colors invert"
            ),
        }
    )


def _make_context(tmp_path: Path) -> SkillContext:
    return SkillContext(
        artifact_dir=tmp_path,
        parameters={
            "personas_context": "# PM Patricia\nManages 5 projects, frustrated by eye strain",
            "feature_description": "Add dark mode to the dashboard for reduced eye strain",
        },
        trace_id="trace-1",
    )


def test_stories_validate_passes(tmp_path):
    skill = UserStoryWriter(llm=_make_stub())
    skill.validate(_make_context(tmp_path))


def test_stories_validate_fails_missing_personas(tmp_path):
    skill = UserStoryWriter(llm=_make_stub())
    context = _make_context(tmp_path)
    del context.parameters["personas_context"]
    with pytest.raises(SkillValidationError, match="personas_context"):
        skill.validate(context)


def test_stories_validate_fails_missing_feature(tmp_path):
    skill = UserStoryWriter(llm=_make_stub())
    context = _make_context(tmp_path)
    del context.parameters["feature_description"]
    with pytest.raises(SkillValidationError, match="feature_description"):
        skill.validate(context)


async def test_stories_execute_writes_artifact(tmp_path):
    stub = _make_stub()
    skill = UserStoryWriter(llm=stub)
    context = _make_context(tmp_path)

    artifact = await skill.execute(context)

    assert (tmp_path / "user_stories.md").exists()
    assert artifact.artifact_type == "user_story"


async def test_stories_execute_includes_persona_in_prompt(tmp_path):
    stub = _make_stub()
    skill = UserStoryWriter(llm=stub)
    context = _make_context(tmp_path)

    await skill.execute(context)

    prompt = stub.calls[0][0]
    assert "PM Patricia" in prompt
    assert "dark mode" in prompt
