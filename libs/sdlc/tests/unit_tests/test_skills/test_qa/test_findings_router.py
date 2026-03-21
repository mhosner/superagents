"""Tests for FindingsRouter skill."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from superagents_sdlc.skills.base import SkillContext, SkillValidationError
from superagents_sdlc.skills.llm import StubLLMClient
from superagents_sdlc.skills.qa.findings_router import FindingsRouter

if TYPE_CHECKING:
    from pathlib import Path


_VALID_MANIFEST = json.dumps({
    "certification": "NEEDS WORK",
    "total_findings": 2,
    "routing": {
        "product_manager": [],
        "architect": [
            {
                "id": "RF-1",
                "summary": "Missing caching layer in spec",
                "detail": "The tech spec does not address caching.",
                "affected_artifact": "tech_spec",
                "related_requirements": [
                    {"id": "S1-AC3", "text": "Response time under 200ms"},
                ],
            },
        ],
        "developer": [
            {
                "id": "RF-2",
                "summary": "No test for error path",
                "detail": "Code plan lacks error handling test.",
                "affected_artifact": "code_plan",
                "related_requirements": [
                    {"id": "S2-AC1", "text": "Returns 422 on invalid input"},
                ],
            },
        ],
    },
})


def _make_stub(response: str = _VALID_MANIFEST) -> StubLLMClient:
    return StubLLMClient(responses={"## Validation report\n": response})


def _make_context(tmp_path: Path) -> SkillContext:
    return SkillContext(
        artifact_dir=tmp_path,
        parameters={
            "validation_report": (
                "## Required Fixes\n- RF-1: Missing caching\n- RF-2: No error test"
            ),
            "user_stories": "## S1-AC3\nResponse time under 200ms\n## S2-AC1\nReturns 422",
        },
        trace_id="trace-1",
    )


def test_findings_router_validate_passes(tmp_path):
    skill = FindingsRouter(llm=_make_stub())
    skill.validate(_make_context(tmp_path))


def test_findings_router_validate_missing_validation_report(tmp_path):
    skill = FindingsRouter(llm=_make_stub())
    context = _make_context(tmp_path)
    del context.parameters["validation_report"]
    with pytest.raises(SkillValidationError, match="validation_report"):
        skill.validate(context)


def test_findings_router_validate_missing_user_stories(tmp_path):
    skill = FindingsRouter(llm=_make_stub())
    context = _make_context(tmp_path)
    del context.parameters["user_stories"]
    with pytest.raises(SkillValidationError, match="user_stories"):
        skill.validate(context)


async def test_findings_router_execute_writes_json(tmp_path):
    skill = FindingsRouter(llm=_make_stub())
    context = _make_context(tmp_path)
    artifact = await skill.execute(context)

    assert artifact.artifact_type == "routing_manifest"
    assert artifact.path == str(tmp_path / "routing_manifest.json")

    written = json.loads((tmp_path / "routing_manifest.json").read_text())
    assert written["total_findings"] == 2
    assert len(written["routing"]["architect"]) == 1
    assert len(written["routing"]["developer"]) == 1
    assert written["routing"]["product_manager"] == []


async def test_findings_router_metadata_has_total(tmp_path):
    skill = FindingsRouter(llm=_make_stub())
    context = _make_context(tmp_path)
    artifact = await skill.execute(context)

    assert artifact.metadata["total_findings"] == "2"


async def test_findings_router_includes_context_in_prompt(tmp_path):
    stub = _make_stub()
    skill = FindingsRouter(llm=stub)
    context = _make_context(tmp_path)
    await skill.execute(context)

    prompt = stub.calls[0][0]
    assert "Missing caching" in prompt
    assert "Response time under 200ms" in prompt


async def test_findings_router_rejects_invalid_json(tmp_path):
    skill = FindingsRouter(llm=_make_stub(response="This is not JSON"))
    context = _make_context(tmp_path)

    with pytest.raises(ValueError, match="Failed to parse routing manifest"):
        await skill.execute(context)


async def test_findings_router_rejects_missing_routing_key(tmp_path):
    bad_manifest = json.dumps({"certification": "NEEDS WORK", "total_findings": 0})
    skill = FindingsRouter(llm=_make_stub(response=bad_manifest))
    context = _make_context(tmp_path)

    with pytest.raises(ValueError, match="missing required key"):
        await skill.execute(context)


async def test_findings_router_strips_markdown_fences(tmp_path):
    fenced = f"```json\n{_VALID_MANIFEST}\n```"
    skill = FindingsRouter(llm=_make_stub(response=fenced))
    context = _make_context(tmp_path)
    artifact = await skill.execute(context)

    assert artifact.artifact_type == "routing_manifest"
    written = json.loads((tmp_path / "routing_manifest.json").read_text())
    assert written["total_findings"] == 2


async def test_findings_router_rejects_finding_missing_fields(tmp_path):
    bad_manifest = json.dumps({
        "certification": "NEEDS WORK",
        "total_findings": 1,
        "routing": {
            "product_manager": [],
            "architect": [{"id": "RF-1"}],
            "developer": [],
        },
    })
    skill = FindingsRouter(llm=_make_stub(response=bad_manifest))
    context = _make_context(tmp_path)

    with pytest.raises(ValueError, match="missing required field"):
        await skill.execute(context)
