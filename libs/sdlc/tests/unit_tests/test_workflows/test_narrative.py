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


def test_narrative_record_brainstorm_summary(tmp_path: Path):
    narrative = NarrativeWriter(output_dir=tmp_path, title='idea-to-code "Test"')
    narrative.record_brainstorm_summary(
        question_count=3,
        approach_selected="Simple approach",
        section_count=6,
        brief_path="output/design_brief.md",
    )

    content = (tmp_path / "pipeline_narrative.md").read_text()
    assert "Brainstorm" in content
    assert "3 questions" in content
    assert "Simple approach" in content
    assert "design_brief.md" in content


def test_narrative_record_skill_execution(tmp_path: Path):
    writer = NarrativeWriter(tmp_path, "test")
    writer.start_pass(1, "Initial Run")
    writer.record_skill_execution(
        persona_name="PM",
        skill_name="prd_generator",
        artifact_summary="Generated PRD for dark mode toggle with 5 requirements.",
        context_note="Brief provided as primary input.",
    )
    content = (tmp_path / "pipeline_narrative.md").read_text()
    assert "**PM → prd_generator**" in content
    assert "Generated PRD for dark mode toggle" in content
    assert "Brief provided as primary input." in content


def test_narrative_record_skill_execution_no_context(tmp_path: Path):
    writer = NarrativeWriter(tmp_path, "test")
    writer.start_pass(1, "Initial Run")
    writer.record_skill_execution(
        persona_name="Developer",
        skill_name="code_planner",
        artifact_summary="Produced TDD code plan with 6 tasks.",
    )
    content = (tmp_path / "pipeline_narrative.md").read_text()
    assert "**Developer → code_planner**" in content
    assert "Produced TDD code plan" in content


def test_narrative_record_qa_findings(tmp_path: Path):
    writer = NarrativeWriter(tmp_path, "test")
    writer.start_pass(1, "Initial Run")
    writer.record_qa_findings(
        total_checks=22,
        pass_count=8,
        fail_count=6,
        partial_count=8,
        key_findings=[
            {"id": "RF-1", "summary": "GraphBuilder has no implementation task", "severity": "CRITICAL"},
            {"id": "RF-5", "summary": "Atomic write recovery has no task", "severity": "HIGH"},
        ],
        certification="NEEDS WORK",
    )
    content = (tmp_path / "pipeline_narrative.md").read_text()
    assert "22 checks" in content
    assert "8 PASS" in content
    assert "6 FAIL" in content
    assert "8 PARTIAL" in content
    assert "RF-1" in content
    assert "CRITICAL" in content
    assert "GraphBuilder" in content
    assert "RF-5" in content
    assert "HIGH" in content
    assert "Certification: NEEDS WORK" in content


def test_narrative_record_findings_routing(tmp_path: Path):
    writer = NarrativeWriter(tmp_path, "test")
    writer.start_pass(1, "Initial Run")
    writer.record_findings_routing(
        routing={
            "product_manager": [],
            "architect": [{"id": "RF-2", "summary": "Spec gap"}],
            "developer": [
                {"id": "RF-1", "summary": "Missing task"},
                {"id": "RF-3", "summary": "No error handling"},
            ],
        },
        cascade_personas=["architect", "developer"],
    )
    content = (tmp_path / "pipeline_narrative.md").read_text()
    assert "Findings Routing" in content
    assert "Product Manager: 0" in content
    assert "Architect: 1" in content
    assert "Developer: 2" in content
    assert "Cascade:" in content
    assert "Architect" in content and "Developer" in content


def test_narrative_record_findings_routing_developer_only(tmp_path: Path):
    writer = NarrativeWriter(tmp_path, "test")
    writer.start_pass(1, "Initial Run")
    writer.record_findings_routing(
        routing={
            "product_manager": [],
            "architect": [],
            "developer": [{"id": "RF-1", "summary": "Missing task"}],
        },
        cascade_personas=["developer"],
    )
    content = (tmp_path / "pipeline_narrative.md").read_text()
    assert "Developer: 1" in content
    assert "Cascade:" in content


def test_narrative_record_retry_start(tmp_path: Path):
    writer = NarrativeWriter(tmp_path, "test")
    writer.record_retry_start(
        pre_retry_certification="NEEDS WORK",
        finding_count=13,
        persona_breakdown={"product_manager": 0, "architect": 0, "developer": 13},
    )
    content = (tmp_path / "pipeline_narrative.md").read_text()
    assert "NEEDS WORK" in content
    assert "13" in content
    assert "Developer: 13" in content


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
