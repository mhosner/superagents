"""IdeaMemory — canonical decision record for brainstorm sessions.

Provides a deterministic, structured, immutable record of user decisions.
Written by code (not LLM) and injected into all brainstorm prompts as the
single source of truth for what was decided.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class MemoryEntry:
    """Single entry in IdeaMemory.

    Attributes:
        id: Stable identifier (e.g., "D1", "R1").
        title: Human-readable section title.
        type: Entry type ("decision" or "rejection").
        text: Canonical text (1-3 sentences).
        section: Section key for code-assembled summaries (e.g., "technical_constraints").
    """

    id: str
    title: str
    type: str
    text: str
    section: str = ""


@dataclass
class IdeaMemory:
    """Canonical record of brainstorm decisions.

    Attributes:
        idea_title: The feature being brainstormed.
        entries: Ordered list of decision/rejection entries.
    """

    idea_title: str
    entries: list[MemoryEntry] = field(default_factory=list)
    _decision_count: int = field(default=0, repr=False, compare=False)
    _rejection_count: int = field(default=0, repr=False, compare=False)

    @property
    def counts(self) -> dict:
        """Return current entry counts for state serialization."""
        return {"decision": self._decision_count, "rejection": self._rejection_count}

    def add_decision(self, title: str, text: str, *, section: str = "") -> str:
        """Add a decision entry.

        Args:
            title: Human-readable section title.
            text: Canonical decision text.
            section: Section key for code-assembled summaries.

        Returns:
            Assigned entry ID (e.g., "D1").
        """
        self._decision_count += 1
        entry_id = f"D{self._decision_count}"
        self.entries.append(
            MemoryEntry(id=entry_id, title=title, type="decision", text=text, section=section)
        )
        return entry_id

    def add_rejection(self, title: str, text: str, *, section: str = "") -> str:
        """Add a rejection entry.

        Args:
            title: Human-readable section title.
            text: Canonical rejection text.
            section: Section key for code-assembled summaries.

        Returns:
            Assigned entry ID (e.g., "R1").
        """
        self._rejection_count += 1
        entry_id = f"R{self._rejection_count}"
        self.entries.append(
            MemoryEntry(id=entry_id, title=title, type="rejection", text=text, section=section)
        )
        return entry_id

    def format_for_prompt(self) -> str:
        """Format IdeaMemory as a prompt block.

        Returns:
            Structured text for LLM prompt injection, or a placeholder
            when no decisions exist.
        """
        if not self.entries:
            return "No decisions have been made yet."

        lines = [
            f"# IdeaMemory: {self.idea_title}",
            "",
            "## Locked Decisions (DO NOT OVERRIDE)",
            "",
        ]
        for entry in self.entries:
            lines.append(f"### {entry.id}: {entry.title} [{entry.type}]")
            lines.append(entry.text)
            lines.append("")
        return "\n".join(lines)

    def to_markdown(self) -> str:
        """Serialize to markdown for writing to disk.

        Returns:
            Same as ``format_for_prompt()``.
        """
        return self.format_for_prompt()

    def to_state(self) -> list[dict]:
        """Serialize entries for LangGraph state.

        Returns:
            List of dicts, each with id, title, type, text keys.
        """
        return [
            {"id": e.id, "title": e.title, "type": e.type, "text": e.text, "section": e.section}
            for e in self.entries
        ]

    @classmethod
    def from_state(
        cls,
        idea_title: str,
        entries: list[dict],
        counts: dict,
    ) -> IdeaMemory:
        """Reconstruct IdeaMemory from LangGraph state.

        Args:
            idea_title: The feature being brainstormed.
            entries: Serialized entry dicts from state.
            counts: Dict with "decision" and "rejection" counters.

        Returns:
            Reconstructed IdeaMemory instance.
        """
        mem = cls(idea_title=idea_title)
        mem._decision_count = counts.get("decision", 0)
        mem._rejection_count = counts.get("rejection", 0)
        mem.entries = [
            MemoryEntry(
                id=e["id"],
                title=e["title"],
                type=e["type"],
                text=e["text"],
                section=e.get("section", ""),
            )
            for e in entries
        ]
        return mem
