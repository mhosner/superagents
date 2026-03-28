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
## IdeaMemory — Canonical Decisions

{idea_memory}

Do not ask about topics already decided in IdeaMemory.

## Current section readiness
{section_readiness}

## Gaps to address
{gaps}

Generate exactly 1 question — the single most important question to resolve next \
given the current IdeaMemory state. \
Only ask about sections rated "low" or "medium". \
Never ask about "high" or "deferred" sections. \
The question should be specific enough that the answer directly moves a section toward "high". \
Prefer multiple-choice when the answer space is bounded. \
Prefer questions with mutually exclusive options (pick one). \
Avoid "select all that apply" — if multiple aspects need to be decided, ask them as \
separate questions in subsequent rounds. \
When multiple sections are rated "low" or "medium", prefer asking about sections earlier in \
this dependency order: problem_statement → users_and_personas → requirements → \
technical_constraints, acceptance_criteria, scope_boundaries. \
Only target a derived section if all foundational sections are already "high". \
Return as JSON: {{"questions": [{{"question": "...", "options": ["a", "b"] | null, \
"targets_section": "section_name"}}]}}
"""

APPROACHES_PROMPT = """\
## IdeaMemory — Canonical Decisions

{idea_memory}

All approaches must be consistent with every IdeaMemory entry. \
Do not propose approaches that contradict any decision or rejection. \
If IdeaMemory says "no new command", no approach may introduce a command. \
If IdeaMemory specifies a file location, all approaches must use that location.

Propose 2-3 distinct implementation approaches. Each should have a clear name, \
description, and honest tradeoffs section.
Return as JSON array: [{{"name": "...", "description": "...", "tradeoffs": "..."}}]
"""

DESIGN_SECTION_PROMPT = """\
## Selected approach
{selected_approach}

## IdeaMemory — Canonical Decisions

{idea_memory}

MANDATORY: Before outputting this section, verify it against \
every IdeaMemory entry. For each entry, confirm your section \
does not contradict it. Specifically check:
- If IdeaMemory specifies a file path or location, use that exact path — do not invent a different one
- If IdeaMemory specifies a trigger mechanism, describe that exact mechanism — do not substitute another
- If IdeaMemory specifies what is out of scope, include it in Non-Goals
- If IdeaMemory specifies an output format, use that format
- If IdeaMemory says "qualitative", do not produce numeric formulas
- If IdeaMemory says "no new command", do not introduce one

Any contradiction between your section and IdeaMemory is an error. IdeaMemory always wins.

## Previously approved sections
{approved_sections}

Write the "{section_title}" section of the design document. \
Return the section content as markdown.
"""

SYNTHESIZE_PROMPT = """\
## Selected approach
{selected_approach}

## IdeaMemory — Canonical Decisions

{idea_memory}

The brief must incorporate every IdeaMemory entry. Before \
finalizing, verify each entry against the brief text. Any \
contradiction is an error — IdeaMemory always wins.

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
