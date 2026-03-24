"""Confidence estimation for adaptive brainstorming.

Provides ``compute_confidence`` (pure math) and the
``estimate_confidence`` LangGraph node factory.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from langgraph.types import interrupt

from superagents_sdlc.brainstorm.prompts import BRAINSTORM_SYSTEM
from superagents_sdlc.skills.json_utils import extract_json

if TYPE_CHECKING:
    from collections.abc import Callable

    from superagents_sdlc.brainstorm.state import BrainstormState
    from superagents_sdlc.skills.llm import LLMClient

SECTIONS = (
    "problem_statement",
    "users_and_personas",
    "requirements",
    "acceptance_criteria",
    "scope_boundaries",
    "technical_constraints",
)

READINESS_SCORES = {"high": 90, "medium": 60, "low": 30}

DEFAULT_CONFIDENCE_THRESHOLD = 80
DEFAULT_MAX_ROUNDS = 10

_ASSESSMENT_PROMPT = """\
## Idea
{idea}

## Product context
{product_context}

## Codebase context
{codebase_context}

## Q&A transcript
{transcript}

Assess the brainstorm readiness. For each section below, rate the readiness \
of each brief section and provide evidence.

Readiness ratings:
- "high": Could write this section now with confidence
- "medium": Have partial information, brief would have gaps
- "low": Missing critical information, section would be speculative

Sections to rate the readiness of:
1. problem_statement — Is the problem clear?
2. users_and_personas — Do we know who uses this and how?
3. requirements — Are functional requirements specific enough?
4. acceptance_criteria — Can we write Given/When/Then for core flows?
5. scope_boundaries — Do we know what's in and out?
6. technical_constraints — Do we know tech stack and integration points?

{deferred_note}

Return ONLY valid JSON:
{{"sections": {{"problem_statement": {{"readiness": "high", "evidence": "..."}}, ...}}, \
"gaps": [{{"section": "...", "description": "..."}}], \
"recommendation": "continue" | "ready"}}
"""


def _format_transcript_for_assessment(transcript: list[dict]) -> str:
    """Convert raw transcript entries into structured decision blocks for LLM prompts.

    Each entry is labeled as a settled decision rather than an open question,
    and only the selected answer is shown (options are excluded).

    Args:
        transcript: List of dicts with keys ``question``, ``answer``,
            ``options``, and ``targets_section``.

    Returns:
        Formatted string with one ``### Decision N`` block per entry,
        or a placeholder when the transcript is empty.
    """
    if not transcript:
        return "No questions have been asked yet."

    blocks = []
    for i, entry in enumerate(transcript, start=1):
        block = (
            f"### Decision {i}\n"
            f"**Question:** {entry['question']}\n"
            f"**DECIDED:** {entry['answer']}"
        )
        blocks.append(block)
    return "\n".join(blocks)


def compute_confidence(sections: dict, deferred: list[str]) -> int:
    """Compute confidence score from section readiness ratings.

    Args:
        sections: Map of section name to {readiness, evidence} dict.
        deferred: Section names excluded from scoring.

    Returns:
        Integer confidence score (0-100).
    """
    active = {k: v for k, v in sections.items() if k not in deferred}
    if not active:
        return 100
    total = sum(READINESS_SCORES[v["readiness"]] for v in active.values())
    return total // len(active)


def make_estimate_confidence_node(
    llm: LLMClient,
    *,
    threshold: int = DEFAULT_CONFIDENCE_THRESHOLD,
    max_rounds: int = DEFAULT_MAX_ROUNDS,
) -> Callable[..., Any]:
    """Create the estimate_confidence node.

    Args:
        llm: LLM client for assessment generation.
        threshold: Confidence score to auto-proceed.
        max_rounds: Hard cap on question rounds.

    Returns:
        Async node function.
    """

    async def estimate_confidence(state: BrainstormState) -> dict[str, Any]:
        """Assess section readiness and route to questions or approaches."""
        deferred = list(state.get("deferred_sections", []))

        # Hard cap: force proceed
        if state.get("round_number", 0) >= max_rounds:
            return {"status": "proposing"}

        deferred_note = ""
        if deferred:
            deferred_note = (
                f"Deferred sections (do NOT rate): {', '.join(deferred)}"
            )

        prompt = _ASSESSMENT_PROMPT.format(
            idea=state["idea"],
            product_context=state["product_context"],
            codebase_context=state["codebase_context"],
            transcript=json.dumps(state["transcript"]),
            deferred_note=deferred_note,
        )
        raw = await llm.generate(prompt, system=BRAINSTORM_SYSTEM)
        parsed = extract_json(raw)

        section_readiness = parsed["sections"]
        gaps = parsed.get("gaps", [])
        score = compute_confidence(section_readiness, deferred)

        # Auto-proceed if above threshold
        if score >= threshold:
            return {
                "section_readiness": section_readiness,
                "confidence_score": score,
                "gaps": gaps,
                "status": "proposing",
            }

        # Interrupt for human decision
        response = interrupt({
            "type": "confidence_assessment",
            "confidence": score,
            "threshold": threshold,
            "round": state.get("round_number", 0),
            "sections": section_readiness,
            "gaps": gaps,
            "options": ["continue", "defer", "override"],
        })

        response_str = str(response).strip().lower()

        if response_str == "override":
            return {
                "section_readiness": section_readiness,
                "confidence_score": score,
                "gaps": gaps,
                "status": "proposing",
            }

        if response_str.startswith("defer"):
            # Parse "defer section1,section2"
            parts = response_str.split(maxsplit=1)
            new_deferred = deferred
            if len(parts) > 1:
                names = [s.strip() for s in parts[1].split(",") if s.strip()]
                new_deferred = list(set(deferred + names))
            # Recalculate with new deferrals
            new_score = compute_confidence(section_readiness, new_deferred)
            new_status = "proposing" if new_score >= threshold else "questioning"
            return {
                "section_readiness": section_readiness,
                "confidence_score": new_score,
                "gaps": [g for g in gaps if g["section"] not in new_deferred],
                "deferred_sections": new_deferred,
                "status": new_status,
            }

        # Default: continue questioning
        return {
            "section_readiness": section_readiness,
            "confidence_score": score,
            "gaps": gaps,
            "status": "questioning",
        }

    return estimate_confidence
