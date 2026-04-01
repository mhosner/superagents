"""Brainstorm narrative renderer.

Converts structured narrative entries from BrainstormState into a
stakeholder-readable markdown document. All text is code-assembled —
no LLM writes narrative content.
"""

from __future__ import annotations

_DESIGN_EVENTS = {"approach_selected", "section_approved", "section_revised"}
_BRIEF_EVENTS = {"brief_approved", "brief_revised"}


def render_narrative_markdown(entries: list[dict], idea: str) -> str:
    """Render narrative entries to a markdown document.

    Args:
        entries: Structured narrative entries from BrainstormState.
        idea: The original feature idea.

    Returns:
        Complete markdown document string.
    """
    lines: list[str] = [f"# Brainstorm Narrative: {idea}"]

    if not entries:
        return "\n".join(lines) + "\n"

    # Partition entries by phase
    exploration: list[dict] = []
    design: list[dict] = []
    brief: list[dict] = []

    for entry in entries:
        event = entry.get("event", "")
        if event in _BRIEF_EVENTS:
            brief.append(entry)
        elif event in _DESIGN_EVENTS:
            design.append(entry)
        else:
            exploration.append(entry)

    if exploration:
        lines.append("")
        lines.append("## Exploration")
        _render_exploration(exploration, lines)

    if design:
        lines.append("")
        lines.append("## Design")
        _render_design(design, lines)

    if brief:
        lines.append("")
        lines.append("## Brief")
        _render_brief(brief, lines)

    return "\n".join(lines) + "\n"


def _format_delta(delta: int | None) -> str:
    """Format a confidence delta as a signed string.

    Args:
        delta: Confidence change, or None.

    Returns:
        Formatted string like "+5", "-3", or "".
    """
    if delta is None:
        return ""
    return f"+{delta}" if delta >= 0 else str(delta)


def _render_exploration(entries: list[dict], lines: list[str]) -> None:  # noqa: C901, PLR0912
    """Render exploration-phase entries with round headers.

    Args:
        entries: Exploration-phase narrative entries.
        lines: Output lines list (mutated in place).
    """
    current_round: int | None = None

    for entry in entries:
        event = entry.get("event", "")
        entry_round = entry.get("round")

        # Insert round header when round changes
        if entry_round is not None and entry_round != current_round:
            current_round = entry_round
            if current_round == 0:
                lines.append("")
                lines.append("### Round 0 — Initial Assessment")
            else:
                lines.append("")
                lines.append(f"### Round {current_round}")

        if event == "assessment":
            confidence = entry.get("confidence", 0)
            delta = entry.get("confidence_delta")
            gap_count = entry.get("gap_count", 0)
            delta_str = f" ({_format_delta(delta)})" if delta is not None else ""
            lines.append(
                f"**Assessment**: Confidence {confidence}%{delta_str}."
                f" {gap_count} gaps remaining."
            )

            readiness_changes = entry.get("readiness_changes", {})
            if readiness_changes:
                for section, change in readiness_changes.items():
                    lines.append(f"- {section}: {change['from'].upper()} → {change['to'].upper()}")

            section_readiness = entry.get("section_readiness", {})
            if section_readiness and delta is None:
                # First assessment — show all sections
                for section, info in section_readiness.items():
                    readiness = info.get("readiness", "?")
                    markers = {"high": "✓", "medium": "~", "low": "✗"}
                    marker = markers.get(readiness, "?")
                    lines.append(f"- {marker} {section}: {readiness.upper()}")

        elif event == "question_answered":
            question = entry.get("question_text", "?")
            answer = entry.get("answer_text", "")
            lines.append(f"**Question**: {question}")
            lines.append(f"**Answer**: {answer}")

        elif event == "auto_continue":
            gap_count = entry.get("gap_count", 0)
            confidence = entry.get("confidence", 0)
            lines.append(f"*Auto-continued* (confidence {confidence}%, {gap_count} gaps remaining)")

        elif event == "stall_exit":
            choice = entry.get("choice", "?")
            gaps = entry.get("gaps", [])
            lines.append(f"**Stall exit**: chose to {choice} ({len(gaps)} gaps remaining)")

        elif event == "deferral":
            sections = entry.get("deferred_sections", [])
            lines.append(f"**Deferred**: {', '.join(sections)}")

        elif event == "override":
            lines.append("**Override**: user forced proceed to design phase")

        lines.append("")


def _render_design(entries: list[dict], lines: list[str]) -> None:
    """Render design-phase entries.

    Args:
        entries: Design-phase narrative entries.
        lines: Output lines list (mutated in place).
    """
    for entry in entries:
        event = entry.get("event", "")
        if event == "approach_selected":
            name = entry.get("approach_name", "?")
            offered = entry.get("approaches_offered", [])
            lines.append(f"**Approach selected**: {name} (from: {', '.join(offered)})")
            lines.append("")
        elif event == "section_approved":
            title = entry.get("section_title", "?")
            lines.append(f"- ✓ {title} — approved")
        elif event == "section_revised":
            title = entry.get("section_title", "?")
            lines.append(f"- ✎ {title} — revised")


def _render_brief(entries: list[dict], lines: list[str]) -> None:
    """Render brief-phase entries.

    Args:
        entries: Brief-phase narrative entries.
        lines: Output lines list (mutated in place).
    """
    for entry in entries:
        event = entry.get("event", "")
        if event == "brief_approved":
            lines.append("Brief approved.")
        elif event == "brief_revised":
            revision = entry.get("revision_number", "?")
            lines.append(f"Brief revised (revision {revision}).")
