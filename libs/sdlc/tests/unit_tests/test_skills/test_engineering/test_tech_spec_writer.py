"""Tests for TechSpecWriter skill."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from superagents_sdlc.skills.base import SkillContext, SkillValidationError
from superagents_sdlc.skills.engineering.tech_spec_writer import TechSpecWriter
from superagents_sdlc.skills.llm import StubLLMClient

if TYPE_CHECKING:
    from pathlib import Path


def _make_stub() -> StubLLMClient:
    return StubLLMClient(
        responses={"PRD": "# Tech Spec\n## Architecture\nMicroservices with REST API"}
    )


def _make_context(tmp_path: Path) -> SkillContext:
    return SkillContext(
        artifact_dir=tmp_path,
        parameters={
            "prd": "# PRD: Dark Mode\n## Problem\nEye strain in low light",
            "user_stories": "As a PM, I want dark mode so I reduce eye strain",
            "product_context": "B2B SaaS project management platform",
        },
        trace_id="trace-1",
    )


def test_spec_validate_passes(tmp_path):
    skill = TechSpecWriter(llm=_make_stub())
    skill.validate(_make_context(tmp_path))


def test_spec_validate_fails_missing_prd(tmp_path):
    skill = TechSpecWriter(llm=_make_stub())
    context = _make_context(tmp_path)
    del context.parameters["prd"]
    with pytest.raises(SkillValidationError, match="prd"):
        skill.validate(context)


async def test_spec_execute_writes_artifact(tmp_path):
    stub = _make_stub()
    skill = TechSpecWriter(llm=stub)
    context = _make_context(tmp_path)

    artifact = await skill.execute(context)

    assert (tmp_path / "tech_spec.md").exists()
    assert artifact.artifact_type == "tech_spec"
    assert artifact.path == str(tmp_path / "tech_spec.md")


async def test_spec_execute_includes_context_in_prompt(tmp_path):
    stub = _make_stub()
    skill = TechSpecWriter(llm=stub)
    context = _make_context(tmp_path)

    await skill.execute(context)

    prompt = stub.calls[0][0]
    assert "Dark Mode" in prompt
    assert "eye strain" in prompt
    assert "B2B SaaS" in prompt


async def test_spec_execute_returns_correct_metadata(tmp_path):
    stub = _make_stub()
    skill = TechSpecWriter(llm=stub)
    context = _make_context(tmp_path)

    artifact = await skill.execute(context)

    assert "prd_idea" in artifact.metadata


async def test_tech_spec_includes_revision_findings_in_prompt(tmp_path):
    stub = _make_stub()
    skill = TechSpecWriter(llm=stub)
    context = _make_context(tmp_path)
    context.parameters["revision_findings"] = '[{"id":"RF-1","summary":"Add caching"}]'
    context.parameters["previous_tech_spec"] = "# Old Spec\nNo caching mentioned"

    await skill.execute(context)

    prompt = stub.calls[0][0]
    assert "## Previous tech_spec" in prompt
    assert "No caching mentioned" in prompt
    assert "## Revision findings" in prompt
    assert "Add caching" in prompt
    # Both come after the core context (PRD, user stories, product context)
    prev_idx = prompt.index("## Previous tech_spec")
    findings_idx = prompt.index("## Revision findings")
    prd_idx = prompt.index("## PRD")
    assert prd_idx < prev_idx
    assert prev_idx < findings_idx


async def test_tech_spec_includes_codebase_context_in_prompt(tmp_path):
    stub = _make_stub()
    skill = TechSpecWriter(llm=stub)
    context = _make_context(tmp_path)
    context.parameters["codebase_context"] = "# Codebase\nPython monorepo with REST API"

    await skill.execute(context)

    prompt = stub.calls[0][0]
    assert "## Codebase Context" in prompt
    assert "Python monorepo" in prompt
