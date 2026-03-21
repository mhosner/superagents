"""Tests for NarrativeWriter utility."""

from __future__ import annotations

from typing import TYPE_CHECKING

from superagents_sdlc.skills.base import Artifact

if TYPE_CHECKING:
    from pathlib import Path
from superagents_sdlc.workflows.narrative import NarrativeWriter


def test_init_creates_file_with_header(tmp_path: Path):
    NarrativeWriter(tmp_path, 'idea-to-code "Add dark mode"')
    path = tmp_path / "pipeline_narrative.md"
    assert path.exists()
    content = path.read_text()
    assert content == '# Pipeline: idea-to-code "Add dark mode"\n'


def test_start_pass_appends_header(tmp_path: Path):
    writer = NarrativeWriter(tmp_path, "test pipeline")
    writer.start_pass(1, "Initial Run")
    content = (tmp_path / "pipeline_narrative.md").read_text()
    assert "## Pass 1 (Initial Run)" in content
    assert content.startswith("# Pipeline: test pipeline\n")


def test_record_phase_includes_summaries(tmp_path: Path):
    writer = NarrativeWriter(tmp_path, "test")
    writer.start_pass(1, "Initial Run")
    artifacts = [
        Artifact(
            path="pm/prioritization.md",
            artifact_type="prioritization",
            metadata={"summary": "3 items scored; top: Dark mode"},
        ),
        Artifact(
            path="pm/prd.md",
            artifact_type="prd",
            metadata={"summary": "PRD for Add dark mode"},
        ),
    ]
    writer.record_phase("PM", artifacts)
    content = (tmp_path / "pipeline_narrative.md").read_text()
    assert "### PM Phase" in content
    assert "**prioritization**" in content
    assert "3 items scored; top: Dark mode" in content
    assert "`pm/prioritization.md`" in content
    assert "**prd**" in content
    assert "PRD for Add dark mode" in content
    assert "`pm/prd.md`" in content


def test_record_phase_with_certification(tmp_path: Path):
    writer = NarrativeWriter(tmp_path, "test")
    writer.start_pass(1, "Initial Run")
    artifacts = [
        Artifact(
            path="qa/compliance_report.md",
            artifact_type="compliance_report",
            metadata={"summary": "Compliance checked"},
        ),
    ]
    writer.record_phase(
        "QA",
        artifacts,
        certification="NEEDS WORK",
        findings_summary=[
            "RF-1: Missing caching layer [architect → tech_spec]",
        ],
    )
    content = (tmp_path / "pipeline_narrative.md").read_text()
    assert "**Certification: NEEDS WORK**" in content
    assert "Key findings:" in content
    assert "- RF-1: Missing caching layer [architect → tech_spec]" in content


def test_record_human_feedback(tmp_path: Path):
    writer = NarrativeWriter(tmp_path, "test")
    writer.start_pass(3, "Human Revision")
    writer.record_human_feedback("The tech spec needs a caching layer for /api/tasks")
    content = (tmp_path / "pipeline_narrative.md").read_text()
    assert "### Human Feedback" in content
    assert "> The tech spec needs a caching layer for /api/tasks" in content


def test_record_routing(tmp_path: Path):
    writer = NarrativeWriter(tmp_path, "test")
    writer.start_pass(3, "Human Revision")
    writer.record_routing(
        "Routed to: architect",
        ["architect", "developer"],
    )
    content = (tmp_path / "pipeline_narrative.md").read_text()
    assert "### Routing" in content
    assert "Routed to: architect" in content
    assert "Cascade: architect, developer" in content


def test_record_final_result(tmp_path: Path):
    writer = NarrativeWriter(tmp_path, "test")
    writer.record_final_result("READY", 3)
    content = (tmp_path / "pipeline_narrative.md").read_text()
    assert "## Final Result" in content
    assert "Certification: READY" in content
    assert "Total passes: 3" in content


def test_full_narrative_flow(tmp_path: Path):
    writer = NarrativeWriter(tmp_path, 'idea-to-code "Add dark mode"')

    # Pass 1
    writer.start_pass(1, "Initial Run")
    writer.record_phase(
        "PM",
        [
            Artifact(
                path="pm/prioritization.md",
                artifact_type="prioritization",
                metadata={"summary": "3 items scored; top: Dark mode"},
            ),
            Artifact(
                path="pm/prd.md",
                artifact_type="prd",
                metadata={"summary": "PRD for Add dark mode"},
            ),
        ],
    )
    writer.record_phase(
        "QA",
        [
            Artifact(
                path="qa/compliance_report.md",
                artifact_type="compliance_report",
                metadata={},
            ),
        ],
        certification="NEEDS WORK",
        findings_summary=["RF-1: Missing caching layer [architect → tech_spec]"],
    )

    # Pass 3 - Human revision
    writer.start_pass(3, "Human Revision")
    writer.record_human_feedback("The tech spec needs a caching layer for /api/tasks")
    writer.record_routing("Routed to: architect", ["architect", "developer"])

    # Final
    writer.record_final_result("READY", 3)

    content = (tmp_path / "pipeline_narrative.md").read_text()

    # Verify append-only ordering
    header_pos = content.index("# Pipeline:")
    pass1_pos = content.index("## Pass 1")
    pm_pos = content.index("### PM Phase")
    qa_pos = content.index("### QA Phase")
    pass3_pos = content.index("## Pass 3")
    feedback_pos = content.index("### Human Feedback")
    routing_pos = content.index("### Routing")
    final_pos = content.index("## Final Result")

    assert header_pos < pass1_pos < pm_pos < qa_pos < pass3_pos
    assert pass3_pos < feedback_pos < routing_pos < final_pos
