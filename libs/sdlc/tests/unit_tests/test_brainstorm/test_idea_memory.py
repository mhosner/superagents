"""Tests for IdeaMemory canonical decision record."""

from __future__ import annotations

from superagents_sdlc.brainstorm.idea_memory import IdeaMemory


def test_add_decision():
    """Adding a decision assigns ID D1."""
    mem = IdeaMemory(idea_title="Test Feature")
    entry_id = mem.add_decision(title="Storage", text="Use PostgreSQL")
    assert entry_id == "D1"
    assert len(mem.entries) == 1
    assert mem.entries[0].type == "decision"


def test_add_rejection():
    """Adding a rejection assigns ID R1."""
    mem = IdeaMemory(idea_title="Test Feature")
    entry_id = mem.add_rejection(title="Storage", text="Rejected: SQLite")
    assert entry_id == "R1"
    assert mem.entries[0].type == "rejection"


def test_format_for_prompt():
    """Formatted output contains IDs, titles, tags, and text."""
    mem = IdeaMemory(idea_title="Dark Mode")
    mem.add_decision(title="Scope", text="Toggle in settings only")
    mem.add_decision(title="Tech", text="CSS variables")
    mem.add_rejection(title="Scope", text="Rejected: system-wide theme")

    output = mem.format_for_prompt()
    assert "# IdeaMemory: Dark Mode" in output
    assert "Locked Decisions" in output
    assert "### D1: Scope [decision]" in output
    assert "Toggle in settings only" in output
    assert "### D2: Tech [decision]" in output
    assert "### R1: Scope [rejection]" in output
    assert "Rejected: system-wide theme" in output


def test_format_for_prompt_empty():
    """Empty IdeaMemory returns placeholder."""
    mem = IdeaMemory(idea_title="X")
    assert mem.format_for_prompt() == "No decisions have been made yet."


def test_to_state_and_from_state():
    """Round-trip through state serialization."""
    mem = IdeaMemory(idea_title="Feature")
    mem.add_decision(title="A", text="Choice A")
    mem.add_rejection(title="B", text="Not B")

    state_entries = mem.to_state()
    counts = mem.counts

    restored = IdeaMemory.from_state("Feature", state_entries, counts)
    assert len(restored.entries) == 2
    assert restored.entries[0].id == "D1"
    assert restored.entries[1].id == "R1"
    assert restored.format_for_prompt() == mem.format_for_prompt()
