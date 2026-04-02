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


async def test_compliance_prompt_includes_plan_summary(tmp_path):
    stub = _make_stub()
    skill = SpecComplianceChecker(llm=stub)
    context = SkillContext(
        artifact_dir=tmp_path,
        parameters={
            "code_plan": (
                "### Task 1: Create toggle\n\n"
                "- [ ] **Step 1: Write test**\n"
                "Run: `pytest -v`\n\n"
                "- [ ] **Step 2: Implement**\n"
            ),
            "user_stories": "As a PM, I want dark mode",
            "tech_spec": "# Tech Spec\nREST API",
        },
        trace_id="trace-1",
    )

    await skill.execute(context)

    prompt = stub.calls[0][0]
    assert "Tasks extracted: 1" in prompt
    assert "Tasks with test commands: 1" in prompt
    assert "Total steps: 2" in prompt
    assert "### Task 1: Create toggle" in prompt


async def test_compliance_handles_unparseable_plan(tmp_path):
    stub = _make_stub()
    skill = SpecComplianceChecker(llm=stub)
    context = SkillContext(
        artifact_dir=tmp_path,
        parameters={
            "code_plan": "This is not a valid plan at all.",
            "user_stories": "As a PM, I want dark mode",
            "tech_spec": "# Tech Spec\nREST API",
        },
        trace_id="trace-1",
    )

    artifact = await skill.execute(context)

    assert artifact.artifact_type == "compliance_report"
    prompt = stub.calls[0][0]
    assert "Tasks extracted: 0" in prompt


# --- B-12: compliance count parsing ---


def test_parse_compliance_counts_standard_format():
    """Standard summary line with all four counts."""
    from superagents_sdlc.skills.qa.spec_compliance_checker import _parse_compliance_counts

    result = _parse_compliance_counts("Total: 22 | Pass: 8 | Fail: 6 | Partial: 8")
    assert result == {"total": 22, "pass": 8, "fail": 6, "partial": 8}


def test_parse_compliance_counts_missing_partial():
    """Missing partial defaults to 0."""
    from superagents_sdlc.skills.qa.spec_compliance_checker import _parse_compliance_counts

    result = _parse_compliance_counts("Total: 2 | Pass: 1 | Fail: 1")
    assert result == {"total": 2, "pass": 1, "fail": 1, "partial": 0}


def test_parse_compliance_counts_no_match():
    """No structured summary returns all zeros."""
    from superagents_sdlc.skills.qa.spec_compliance_checker import _parse_compliance_counts

    result = _parse_compliance_counts("No structured summary here")
    assert result == {"total": 0, "pass": 0, "fail": 0, "partial": 0}


async def test_compliance_artifact_metadata_includes_counts(tmp_path):
    """execute() embeds parsed compliance counts in artifact metadata."""
    stub = StubLLMClient(
        responses={
            "## Code plan\n": (
                "## Compliance Check\n"
                "| Requirement | Status |\n"
                "| Toggle | PASS |\n"
                "| Persist | PASS |\n"
                "| Sync | PASS |\n"
                "| Error | FAIL |\n"
                "| Edge | PARTIAL |\n"
                "## Summary\n"
                "Total: 5 | Pass: 3 | Fail: 1 | Partial: 1\n"
                "Overall: NEEDS WORK"
            ),
        }
    )
    skill = SpecComplianceChecker(llm=stub)
    context = _make_context(tmp_path)

    artifact = await skill.execute(context)

    assert artifact.metadata["total_checks"] == "5"
    assert artifact.metadata["pass_count"] == "3"
    assert artifact.metadata["fail_count"] == "1"
    assert artifact.metadata["partial_count"] == "1"


# -- _parse_compliance_counts format tests (B-17) --


def test_parse_counts_pipe_separated():
    from superagents_sdlc.skills.qa.spec_compliance_checker import _parse_compliance_counts

    text = "## Summary\nTotal: 5 | Pass: 3 | Fail: 1 | Partial: 1\nOverall: NEEDS WORK"
    counts = _parse_compliance_counts(text)
    assert counts == {"total": 5, "pass": 3, "fail": 1, "partial": 1}


def test_parse_counts_prose_style():
    from superagents_sdlc.skills.qa.spec_compliance_checker import _parse_compliance_counts

    text = "22 checks — 8 PASS, 6 FAIL, 8 PARTIAL"
    counts = _parse_compliance_counts(text)
    assert counts == {"total": 22, "pass": 8, "fail": 6, "partial": 8}


def test_parse_counts_markdown_bold():
    from superagents_sdlc.skills.qa.spec_compliance_checker import _parse_compliance_counts

    text = "| **TOTAL** | **106** | **97** | **3** | **6** |"
    counts = _parse_compliance_counts(text)
    assert counts == {"total": 106, "pass": 97, "fail": 3, "partial": 6}


def test_parse_counts_markdown_table_with_headers():
    """Real format from a spec-from-prd run: TOTAL row in a table with
    columns Total, Pass, Fail, Partial."""
    from superagents_sdlc.skills.qa.spec_compliance_checker import _parse_compliance_counts

    text = (
        "| Requirement | Total | Pass | Fail | Partial |\n"
        "|---|---|---|---|---|\n"
        "| SL-01 | 8 | 7 | 1 | 0 |\n"
        "| **TOTAL** | **106** | **97** | **3** | **6** |\n"
    )
    counts = _parse_compliance_counts(text)
    assert counts == {"total": 106, "pass": 97, "fail": 3, "partial": 6}


def test_parse_counts_no_match():
    from superagents_sdlc.skills.qa.spec_compliance_checker import _parse_compliance_counts

    text = "No structured summary here at all."
    counts = _parse_compliance_counts(text)
    assert counts == {"total": 0, "pass": 0, "fail": 0, "partial": 0}
