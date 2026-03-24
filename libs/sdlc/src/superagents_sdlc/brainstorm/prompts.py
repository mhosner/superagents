"""Prompt templates for brainstorm subgraph nodes."""

from __future__ import annotations

BRAINSTORM_SYSTEM = (
    "You are a collaborative product brainstorming assistant. "
    "Ask clarifying questions and help refine ideas into actionable design briefs. "
    "Always return valid JSON when the prompt requests JSON output."
)


def _build_brainstorm_cached_prefix(
    *,
    idea: str,
    product_context: str,
    codebase_context: str,
) -> str | None:
    """Build the stable cached prefix for brainstorm LLM calls.

    Assembles the context that does not change between calls in a
    brainstorm session: the idea, product context, and codebase context.

    Args:
        idea: The feature idea being brainstormed.
        product_context: Product context from context files.
        codebase_context: Codebase context from file analysis.

    Returns:
        Formatted prefix string, or None if all fields are empty.
    """
    parts = []
    for header, value in [
        ("Idea", idea),
        ("Product context", product_context),
        ("Codebase context", codebase_context),
    ]:
        if value:
            parts.append(f"## {header}\n{value}")
    return "\n\n".join(parts) if parts else None

QUESTION_PROMPT = """\
## Decisions Made So Far

The following decisions have been confirmed by the user during this brainstorm \
session. These are FINAL — do not contradict, reinterpret, or question them. \
Do not re-ask about decided topics.

{transcript}

Before generating questions, list each decision the user has made. \
Do not generate questions that contradict or re-ask these decisions.

## Current section readiness
{section_readiness}

## Gaps to address
{gaps}

Generate clarifying questions ONLY about sections rated "low" or "medium". \
Never ask about "high" or "deferred" sections. \
Generate 1 question per gap, up to 4 questions max. \
Each question should be specific enough that the answer directly moves a section toward "high". \
Prefer multiple-choice when the answer space is bounded. \
Return as JSON: {{"questions": [{{"question": "...", "options": ["a", "b"] | null, \
"targets_section": "section_name"}}]}}
"""

APPROACHES_PROMPT = """\
## Decisions Made So Far

The following decisions have been confirmed by the user during this brainstorm \
session. These are FINAL — do not contradict, reinterpret, or question them. \
All proposed approaches must be consistent with these decisions.

{transcript}

Before proposing approaches, list each decision the user has made. \
All approaches must be consistent with every listed decision.

Propose 2-3 distinct implementation approaches. Each should have a clear name, \
description, and honest tradeoffs section.
Return as JSON array: [{{"name": "...", "description": "...", "tradeoffs": "..."}}]
"""

DESIGN_SECTION_PROMPT = """\
## Selected approach
{selected_approach}

## Decisions Made So Far

The following decisions have been confirmed by the user during this brainstorm \
session. These are FINAL — do not contradict, reinterpret, or question them. \
This section must reflect these decisions accurately.

{transcript}

Before writing this section, list each decision the user has made. \
The section content must reflect these decisions exactly.

## Previously approved sections
{approved_sections}

Write the "{section_title}" section of the design document. \
Return the section content as markdown.
"""

SYNTHESIZE_PROMPT = """\
## Selected approach
{selected_approach}

## Decisions Made So Far

The following decisions have been confirmed by the user during this brainstorm \
session. These are FINAL — do not contradict, reinterpret, or question them. \
The brief must incorporate every decision.

{transcript}

Before synthesizing, list each decision the user has made.

## Approved design sections
{sections}

Synthesize all approved sections into a single structured design brief in markdown format. \
The brief should be self-contained and readable as a standalone document.
"""

DESIGN_SECTIONS = [
    "Problem Statement & Goals",
    "Target Users & Personas",
    "Requirements & User Stories",
    "Acceptance Criteria",
    "Scope Boundaries & Out of Scope",
    "Technical Constraints & Dependencies",
]

SECTION_TITLES = {
    "problem_statement": "Problem Statement & Goals",
    "users_and_personas": "Target Users & Personas",
    "requirements": "Requirements & User Stories",
    "acceptance_criteria": "Acceptance Criteria",
    "scope_boundaries": "Scope Boundaries & Out of Scope",
    "technical_constraints": "Technical Constraints & Dependencies",
}
