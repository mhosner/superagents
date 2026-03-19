"""Tests for ValidationReportGenerator skill."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from superagents_sdlc.skills.base import SkillContext, SkillValidationError
from superagents_sdlc.skills.llm import StubLLMClient
from superagents_sdlc.skills.qa.validation_report_generator import (
    ValidationReportGenerator,
)

if TYPE_CHECKING:
    from pathlib import Path


def _make_stub() -> StubLLMClient:
    return StubLLMClient(
        responses={
            "## Compliance report\n": (
                "# Validation Report\n"
                "## Executive Summary\nPartial coverage with gaps.\n"
                "## Certification\nNEEDS WORK\n"
                "## Required Fixes\n- Add persistence tests"
            ),
        }
    )


def _make_context(tmp_path: Path) -> SkillContext:
    return SkillContext(
        artifact_dir=tmp_path,
        parameters={
            "compliance_report": "## Summary\nTotal: 2 | Pass: 1 | Fail: 1",
            "code_plan": "## Task 1: DarkModeToggle\n### RED\ntest_toggle",
            "user_stories": "As a PM, I want dark mode so I reduce eye strain",
        },
        trace_id="trace-1",
    )


def test_validation_validate_passes(tmp_path):
    skill = ValidationReportGenerator(llm=_make_stub())
    skill.validate(_make_context(tmp_path))


def test_validation_validate_fails_missing_compliance(tmp_path):
    skill = ValidationReportGenerator(llm=_make_stub())
    context = _make_context(tmp_path)
    del context.parameters["compliance_report"]
    with pytest.raises(SkillValidationError, match="compliance_report"):
        skill.validate(context)


def test_validation_validate_fails_missing_code_plan(tmp_path):
    skill = ValidationReportGenerator(llm=_make_stub())
    context = _make_context(tmp_path)
    del context.parameters["code_plan"]
    with pytest.raises(SkillValidationError, match="code_plan"):
        skill.validate(context)


async def test_validation_execute_writes_artifact(tmp_path):
    stub = _make_stub()
    skill = ValidationReportGenerator(llm=stub)
    context = _make_context(tmp_path)

    artifact = await skill.execute(context)

    assert (tmp_path / "validation_report.md").exists()
    assert artifact.artifact_type == "validation_report"
    assert artifact.path == str(tmp_path / "validation_report.md")
    assert artifact.metadata["certification"] == "NEEDS WORK"


async def test_validation_execute_includes_context_in_prompt(tmp_path):
    stub = _make_stub()
    skill = ValidationReportGenerator(llm=stub)
    context = _make_context(tmp_path)

    await skill.execute(context)

    prompt = stub.calls[0][0]
    assert "Pass: 1" in prompt
    assert "DarkModeToggle" in prompt
