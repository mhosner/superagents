"""Tests for ValidationReportGenerator skill."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from superagents_sdlc.skills.base import SkillContext, SkillValidationError
from superagents_sdlc.skills.llm import StubLLMClient
from superagents_sdlc.skills.qa.validation_report_generator import (
    ValidationReportGenerator,
    _extract_certification,
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


def test_extract_certification_infers_needs_work_when_missing_but_fixes_present():
    """When certification section is absent but required fixes exist, infer NEEDS WORK."""
    response = (
        "# Validation Report\n"
        "## Executive Summary\nPartial coverage.\n"
        "## Required Fixes\n- Add persistence tests\n- Fix auth flow\n"
        "## Recommended Improvements\n- Add logging\n"
    )
    assert _extract_certification(response) == "NEEDS WORK"


def test_extract_certification_returns_unknown_when_no_section_no_fixes():
    """When certification section is absent and no required fixes, return unknown."""
    response = (
        "# Validation Report\n"
        "## Executive Summary\nAll good.\n"
        "## Recommended Improvements\n- Add logging\n"
    )
    assert _extract_certification(response) == "unknown"


def test_prompt_mandates_certification_as_final_line():
    """System prompt must mandate certification rating as the very last line."""
    from superagents_sdlc.skills.qa.validation_report_generator import _SYSTEM_PROMPT

    assert "last line" in _SYSTEM_PROMPT.lower() or "final line" in _SYSTEM_PROMPT.lower()


def test_certification_prompt_contains_retry_guidance():
    """System prompt must explain how certification drives the automated retry loop."""
    from superagents_sdlc.skills.qa.validation_report_generator import _SYSTEM_PROMPT

    assert "automated retry" in _SYSTEM_PROMPT.lower()
