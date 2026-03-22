"""Brainstorm subgraph state definition."""

from __future__ import annotations

from typing import TypedDict


class BrainstormState(TypedDict):
    """State for the brainstorm LangGraph subgraph.

    Attributes:
        idea: The initial feature idea.
        product_context: Product context from context files.
        codebase_context: Codebase context from --codebase-context file.
        transcript: Question-answer pairs from clarifying rounds.
        coverage: Tracks which brainstorming dimensions are covered.
        approaches: Generated implementation approaches.
        selected_approach: Human-selected approach name.
        design_sections: Design sections with approval status.
        current_section_idx: Index of current section being generated.
        brief: Final synthesized design brief.
        status: Current subgraph phase.
        iteration: Question round counter (max 4).
        brief_revision_count: Brief revision counter (max 2).
    """

    idea: str
    product_context: str
    codebase_context: str
    transcript: list[dict]
    coverage: dict
    approaches: list[dict]
    selected_approach: str
    design_sections: list[dict]
    current_section_idx: int
    brief: str
    status: str
    iteration: int
    brief_revision_count: int
