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

## Previous Q&A
{transcript}

## Coverage gaps
{coverage}

Generate ONE clarifying question to better understand this idea. \
Prefer multiple-choice options when the question has a bounded answer space. \
Return as JSON: {{"question": "...", "options": ["a", "b", ...] | null}}
"""

COVERAGE_PROMPT = """\
## Idea
{idea}

## Q&A transcript
{transcript}

Evaluate which of these dimensions are now adequately covered: \
users, problem, scope, constraints, integrations, success_metrics.
Return as JSON: {{"covered": ["dim1", ...], "missing": ["dim2", ...], "sufficient": true|false}}
"""

APPROACHES_PROMPT = """\
## Idea
{idea}

## Q&A transcript
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

## Q&A transcript
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
