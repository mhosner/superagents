"""Tests for PipelineResult dataclass."""

from __future__ import annotations

from superagents_sdlc.skills.base import Artifact
from superagents_sdlc.workflows.result import PipelineResult


def test_pipeline_result_defaults():
    result = PipelineResult()
    assert result.artifacts == []
    assert result.pm == []
    assert result.architect == []
    assert result.developer == []
    assert result.qa == []
    assert result.certification == "skipped"


def test_pipeline_result_with_artifacts():
    prd = Artifact(path="/prd.md", artifact_type="prd", metadata={})
    spec = Artifact(path="/spec.md", artifact_type="tech_spec", metadata={})
    result = PipelineResult(
        artifacts=[prd, spec],
        pm=[prd],
        architect=[spec],
        developer=[],
        qa=[],
        certification="NEEDS WORK",
    )
    assert len(result.artifacts) == 2
    assert len(result.pm) == 1
    assert result.pm[0].artifact_type == "prd"
    assert result.certification == "NEEDS WORK"
