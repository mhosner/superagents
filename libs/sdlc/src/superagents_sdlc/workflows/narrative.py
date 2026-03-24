"""Pipeline narrative — append-only session log for pipeline runs."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from superagents_sdlc.skills.base import Artifact


class NarrativeWriter:
    """Appends structured narrative entries to pipeline_narrative.md."""

    def __init__(self, output_dir: Path, title: str) -> None:
        """Initialize and write the file header.

        Args:
            output_dir: Directory for the narrative file.
            title: Pipeline title (e.g., 'idea-to-code "Add dark mode"').
        """
        self._path = output_dir / "pipeline_narrative.md"
        self._path.write_text(f"# Pipeline: {title}\n")

    def start_pass(self, pass_number: int, pass_type: str) -> None:
        """Write a pass header.

        Args:
            pass_number: Pass number (1, 2, 3, ...).
            pass_type: One of "Initial Run", "Automated Retry", "Human Revision".
        """
        with self._path.open("a") as f:
            f.write(f"\n## Pass {pass_number} ({pass_type})\n")

    def record_phase(
        self,
        phase_name: str,
        artifacts: list[Artifact],
        *,
        certification: str = "",
        findings_summary: list[str] | None = None,
    ) -> None:
        """Append a phase entry with artifact summaries.

        Reads "summary" from each artifact's metadata.
        Includes artifact file paths.
        If certification provided, shows it.
        If findings_summary provided, lists key findings.

        Args:
            phase_name: Display name for the phase (e.g., "PM", "QA").
            artifacts: Artifacts produced during this phase.
            certification: Optional certification status.
            findings_summary: Optional list of key finding descriptions.
        """
        lines: list[str] = [f"\n### {phase_name} Phase\n"]
        if certification:
            lines.append(f"**Certification: {certification}**\n")
        if findings_summary:
            lines.append("Key findings:\n")
            lines.extend(f"- {finding}\n" for finding in findings_summary)
        for artifact in artifacts:
            summary = artifact.metadata.get("summary", "")
            entry = f"- **{artifact.artifact_type}**"
            if summary:
                entry += f": {summary}"
            entry += f" \u2192 `{artifact.path}`\n"
            lines.append(entry)
        with self._path.open("a") as f:
            f.writelines(lines)

    def record_human_feedback(self, feedback: str) -> None:
        """Record the user's revision feedback as a blockquote.

        Args:
            feedback: The human feedback text.
        """
        with self._path.open("a") as f:
            f.write(f"\n### Human Feedback\n\n> {feedback}\n")

    def record_routing(self, routing_summary: str, cascade_personas: list[str]) -> None:
        """Record how feedback was routed and what cascaded.

        Args:
            routing_summary: Description of routing decision.
            cascade_personas: Ordered list of personas in the cascade.
        """
        cascade = ", ".join(cascade_personas)
        with self._path.open("a") as f:
            f.write(f"\n### Routing\n{routing_summary}. Cascade: {cascade}\n")

    def record_brainstorm_summary(
        self,
        question_count: int,
        approach_selected: str,
        section_count: int,
        brief_path: str,
    ) -> None:
        """Record brainstorm completion summary.

        Args:
            question_count: Number of Q&A rounds completed.
            approach_selected: Name of the selected approach.
            section_count: Number of design sections approved.
            brief_path: Path to the generated design brief file.
        """
        with self._path.open("a") as f:
            f.write(f"\n## Brainstorm Summary\n")
            f.write(f"- {question_count} questions answered\n")
            f.write(f"- Approach selected: {approach_selected}\n")
            f.write(f"- {section_count} design sections approved\n")
            f.write(f"- Brief: `{brief_path}`\n")

    def record_skill_execution(
        self,
        persona_name: str,
        skill_name: str,
        artifact_summary: str,
        context_note: str = "",
    ) -> None:
        """Record an individual skill execution within a phase.

        Args:
            persona_name: Display name of the persona (e.g., "PM").
            skill_name: Name of the skill executed.
            artifact_summary: Short summary of what the skill produced.
            context_note: Optional additional context about inputs or decisions.
        """
        lines = [f"\n**{persona_name} → {skill_name}**: {artifact_summary}"]
        if context_note:
            lines.append(f" {context_note}")
        lines.append("\n")
        with self._path.open("a") as f:
            f.writelines(lines)

    def record_qa_findings(
        self,
        total_checks: int,
        pass_count: int,
        fail_count: int,
        partial_count: int,
        key_findings: list[dict],
        certification: str,
    ) -> None:
        """Record detailed QA compliance results and certification.

        Args:
            total_checks: Total number of compliance checks run.
            pass_count: Number of checks that passed.
            fail_count: Number of checks that failed.
            partial_count: Number of partially passing checks.
            key_findings: List of dicts with id, summary, and severity keys.
            certification: Certification rating string.
        """
        lines = [
            f"\n**QA Compliance Results:** {total_checks} checks"
            f" — {pass_count} PASS, {fail_count} FAIL, {partial_count} PARTIAL\n",
        ]
        if key_findings:
            lines.append("\n**Key Findings:**\n")
            for finding in key_findings:
                fid = finding.get("id", "?")
                severity = finding.get("severity", "?")
                summary = finding.get("summary", "")
                lines.append(f"- {fid} [{severity}]: {summary}\n")
        lines.append(f"\n**Certification: {certification}**\n")
        with self._path.open("a") as f:
            f.writelines(lines)

    def record_findings_routing(
        self,
        routing: dict,
        cascade_personas: list[str],
    ) -> None:
        """Record how findings were classified and routed to personas.

        Args:
            routing: Routing manifest mapping persona names to finding lists.
            cascade_personas: Ordered list of personas in the retry cascade.
        """
        total = sum(len(items) for items in routing.values())
        # Display names: product_manager → Product Manager, etc.
        display = {
            "product_manager": "Product Manager",
            "architect": "Architect",
            "developer": "Developer",
        }
        lines = [f"\n**Findings Routing:** {total} findings classified\n"]
        for persona_key in ("product_manager", "architect", "developer"):
            count = len(routing.get(persona_key, []))
            label = display.get(persona_key, persona_key)
            lines.append(f"- {label}: {count}\n")
        cascade_display = [display.get(p, p) for p in cascade_personas]
        lines.append(f"\n**Cascade:** {' → '.join(cascade_display)}\n")
        with self._path.open("a") as f:
            f.writelines(lines)

    def record_retry_start(
        self,
        pre_retry_certification: str,
        finding_count: int,
        persona_breakdown: dict[str, int],
    ) -> None:
        """Record why an automated retry is starting.

        Args:
            pre_retry_certification: Certification before the retry.
            finding_count: Total number of required fixes.
            persona_breakdown: Map of persona name to finding count.
        """
        display = {
            "product_manager": "Product Manager",
            "architect": "Architect",
            "developer": "Developer",
        }
        lines = [
            f"\n**Trigger:** QA certified {pre_retry_certification}"
            f" with {finding_count} required fixes.\n",
        ]
        for persona_key, count in persona_breakdown.items():
            if count > 0:
                label = display.get(persona_key, persona_key)
                lines.append(f"- {label}: {count}\n")
        with self._path.open("a") as f:
            f.writelines(lines)

    def record_unroutable_findings(
        self, unroutable: dict[str, list[dict]],
    ) -> None:
        """Record findings routed to inactive personas.

        Args:
            unroutable: Map of persona name to list of finding dicts.
        """
        display = {
            "product_manager": "Product Manager",
            "architect": "Architect",
            "developer": "Developer",
        }
        lines = ["\n**Unroutable Findings**\n"]
        for persona, findings in unroutable.items():
            label = display.get(persona, persona)
            lines.append(
                f"- **{label}**: {len(findings)} findings "
                f"cannot be addressed (persona not active in this pipeline mode)\n"
            )
            for finding in findings:
                summary = finding.get("summary", "No summary")
                lines.append(f"  - {summary}\n")
        with self._path.open("a") as f:
            f.writelines(lines)

    def record_final_result(self, certification: str, total_passes: int) -> None:
        """Write the final result summary.

        Args:
            certification: Final certification status.
            total_passes: Total number of passes executed.
        """
        with self._path.open("a") as f:
            f.write(
                f"\n## Final Result\nCertification: {certification}\nTotal passes: {total_passes}\n"
            )
