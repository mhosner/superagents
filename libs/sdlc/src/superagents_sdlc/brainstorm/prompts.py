"""Prompt templates for brainstorm subgraph nodes."""

from __future__ import annotations

BRAINSTORM_SYSTEM = (
    "You are a collaborative product brainstorming assistant. "
    "Ask clarifying questions and help refine ideas into actionable design briefs. "
    "Always return valid JSON when the prompt requests JSON output."
)

QUESTION_PROMPT = """\
## Idea
{idea}

## Product context
{product_context}

## Codebase context
{codebase_context}

## Decisions Made So Far

The following decisions have been confirmed by the user during this brainstorm session. These are FINAL — do not contradict, reinterpret, or question them. Do not re-ask about decided topics.

{transcript}

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
## Idea
{idea}

## Decisions Made So Far

The following decisions have been confirmed by the user during this brainstorm session. These are FINAL — do not contradict, reinterpret, or question them. All proposed approaches must be consistent with these decisions.

{transcript}

## Product context
{product_context}

## Codebase context
{codebase_context}

Propose 2-3 distinct implementation approaches. Each should have a clear name, \
description, and honest tradeoffs section.
Return as JSON array: [{{"name": "...", "description": "...", "tradeoffs": "..."}}]
"""

DESIGN_SECTION_PROMPT = """\
## Idea
{idea}

## Selected approach
{selected_approach}

## Decisions Made So Far

The following decisions have been confirmed by the user during this brainstorm session. These are FINAL — do not contradict, reinterpret, or question them. This section must reflect these decisions accurately.

{transcript}

## Previously approved sections
{approved_sections}

Write the "{section_title}" section of the design document. \
Return the section content as markdown.
"""

SYNTHESIZE_PROMPT = """\
## Idea
{idea}

## Selected approach
{selected_approach}

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
