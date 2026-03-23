"""Tests for BaseSkill ABC, SkillContext, Artifact, and SkillValidationError."""

from pathlib import Path

import pytest

from superagents_sdlc.skills.base import (
    Artifact,
    BaseSkill,
    SkillContext,
    SkillValidationError,
)

# -- Test doubles --


class StubSkill(BaseSkill):
    """Minimal concrete skill for testing."""

    def __init__(self) -> None:
        super().__init__(name="stub", description="A stub skill", required_context=["project"])

    async def execute(self, context: SkillContext) -> Artifact:
        return Artifact(
            path=str(context.artifact_dir / "out.txt"),
            artifact_type="test",
            metadata={"key": "val"},
        )


class StrictSkill(BaseSkill):
    """Skill that always fails validation."""

    def __init__(self) -> None:
        super().__init__(name="strict", description="Always fails", required_context=[])

    def validate(self, context: SkillContext) -> None:
        msg = "missing required field"
        raise SkillValidationError(msg)

    async def execute(self, context: SkillContext) -> Artifact:
        msg = "should not reach execute"
        raise AssertionError(msg)


# -- Fixtures --


def _make_context(tmp_path: Path) -> SkillContext:
    return SkillContext(artifact_dir=tmp_path, parameters={"env": "test"}, trace_id="abc123")


# -- Tests --


def test_skill_validate_default_passes(tmp_path):
    skill = StubSkill()
    context = _make_context(tmp_path)
    skill.validate(context)


def test_skill_validate_override_raises(tmp_path):
    skill = StrictSkill()
    context = _make_context(tmp_path)
    with pytest.raises(SkillValidationError, match="missing required field"):
        skill.validate(context)


async def test_skill_execute_returns_artifact(tmp_path):
    skill = StubSkill()
    context = _make_context(tmp_path)
    artifact = await skill.execute(context)
    assert isinstance(artifact, Artifact)
    assert artifact.path == str(tmp_path / "out.txt")
    assert artifact.artifact_type == "test"
    assert artifact.metadata == {"key": "val"}


def test_skill_metadata_fields():
    skill = StubSkill()
    assert skill.name == "stub"
    assert skill.description == "A stub skill"
    assert skill.required_context == ["project"]


def test_skill_context_cached_prefix_defaults_to_none(tmp_path):
    context = SkillContext(artifact_dir=tmp_path, parameters={}, trace_id="t")
    assert context.cached_prefix is None


def test_skill_context_cached_prefix_can_be_set(tmp_path):
    context = SkillContext(
        artifact_dir=tmp_path, parameters={}, trace_id="t",
        cached_prefix="stable context",
    )
    assert context.cached_prefix == "stable context"


def test_artifact_json_round_trip():
    original = Artifact(path="/tmp/out.txt", artifact_type="prd", metadata={"author": "pm"})
    json_str = original.model_dump_json()
    restored = Artifact.model_validate_json(json_str)
    assert restored.path == original.path
    assert restored.artifact_type == original.artifact_type
    assert restored.metadata == original.metadata
