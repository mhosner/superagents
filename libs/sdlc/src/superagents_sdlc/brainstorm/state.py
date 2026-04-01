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
        section_readiness: Per-section readiness ratings from confidence assessment.
        confidence_score: Computed from section_readiness (0-100).
        gaps: Sections needing more information.
        deferred_sections: Sections human chose to defer to downstream personas.
        round_number: Question round counter.
        approaches: Generated implementation approaches.
        selected_approach: Human-selected approach name.
        design_sections: Design sections with approval status.
        current_section_idx: Index of current section being generated.
        brief: Final synthesized design brief.
        status: Current subgraph phase.
        brief_revision_count: Brief revision counter (max 2).
        idea_memory: Structured memory entries from brainstorm decisions.
        idea_memory_counts: Counts of memory entries by type.
        stall_counter: Consecutive questions with < 2pt confidence gain.
        previous_confidence: Confidence score from prior iteration.
        section_summaries: Code-assembled summaries from IdeaMemory entries.
        cached_assessment: Cached confidence assessment to prevent double LLM execution.
        narrative_entries: Structured narrative entries accumulated during brainstorm.
    """

    idea: str
    product_context: str
    codebase_context: str
    transcript: list[dict]
    section_readiness: dict
    confidence_score: int
    gaps: list[dict]
    deferred_sections: list[str]
    round_number: int
    approaches: list[dict]
    selected_approach: str
    design_sections: list[dict]
    current_section_idx: int
    brief: str
    status: str
    brief_revision_count: int
    idea_memory: list[dict]
    idea_memory_counts: dict
    stall_counter: int
    previous_confidence: float
    section_summaries: dict
    cached_assessment: dict
    narrative_entries: list[dict]
