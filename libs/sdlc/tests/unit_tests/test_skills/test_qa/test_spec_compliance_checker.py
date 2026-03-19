"""Tests for SpecComplianceChecker skill."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from superagents_sdlc.skills.base import SkillContext, SkillValidationError
from superagents_sdlc.skills.llm import StubLLMClient
from superagents_sdlc.skills.qa.spec_compliance_checker import SpecComplianceChecker

if TYPE_CHECKING:
    from pathlib import Path


def _make_stub() -> StubLLMClient:
    return StubLLMClient(
        responses={
            "## Code plan\n": (
                "## Compliance Check\n"
                "| Requirement | Status |\n"
                "| Dark mode toggle | PASS |\n"
                "| Theme persistence | FAIL |\n"
                "## Summary\nOverall: NEEDS WORK\n"
                "Total: 2 | Pass: 1 | Fail: 1"
            ),
        }
    )


def _make_context(tmp_path: Path) -> SkillContext:
    return SkillContext(
        artifact_dir=tmp_path,
        parameters={
            "code_plan": "## Task 1: DarkModeToggle\n### RED\ntest_toggle",
            "user_stories": "As a PM, I want dark mode so I reduce eye strain",
            "tech_spec": "# Tech Spec\n## Architecture\nREST API with PostgreSQL",
        },
        trace_id="trace-1",
    )


def test_compliance_validate_passes(tmp_path):
    skill = SpecComplianceChecker(llm=_make_stub())
    skill.validate(_make_context(tmp_path))


def test_compliance_validate_fails_missing_code_plan(tmp_path):
    skill = SpecComplianceChecker(llm=_make_stub())
    context = _make_context(tmp_path)
    del context.parameters["code_plan"]
    with pytest.raises(SkillValidationError, match="code_plan"):
        skill.validate(context)


def test_compliance_validate_fails_missing_user_stories(tmp_path):
    skill = SpecComplianceChecker(llm=_make_stub())
    context = _make_context(tmp_path)
    del context.parameters["user_stories"]
    with pytest.raises(SkillValidationError, match="user_stories"):
        skill.validate(context)


async def test_compliance_execute_writes_artifact(tmp_path):
    stub = _make_stub()
    skill = SpecComplianceChecker(llm=stub)
    context = _make_context(tmp_path)

    artifact = await skill.execute(context)

    assert (tmp_path / "compliance_report.md").exists()
    assert artifact.artifact_type == "compliance_report"
    assert artifact.path == str(tmp_path / "compliance_report.md")
    assert artifact.metadata["framework"] == "spec_compliance"


async def test_compliance_execute_includes_context_in_prompt(tmp_path):
    stub = _make_stub()
    skill = SpecComplianceChecker(llm=stub)
    context = _make_context(tmp_path)

    await skill.execute(context)

    prompt = stub.calls[0][0]
    assert "DarkModeToggle" in prompt
    assert "dark mode" in prompt
    assert "REST API" in prompt
