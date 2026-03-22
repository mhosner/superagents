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
