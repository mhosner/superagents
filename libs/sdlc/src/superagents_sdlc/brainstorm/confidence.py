"""Confidence estimation for adaptive brainstorming.

Provides ``compute_confidence`` (pure math) and the
``estimate_confidence`` LangGraph node factory.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from langgraph.types import interrupt

from superagents_sdlc.brainstorm.idea_memory import IdeaMemory
from superagents_sdlc.brainstorm.prompts import (
    BRAINSTORM_SYSTEM,
    _build_brainstorm_cached_prefix,
)
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
SAFETY_CAP = 50

_ASSESSMENT_PROMPT = """\
## IdeaMemory — Canonical Decisions

The following decisions are FINAL. They were recorded exactly as the user \
stated them. You MUST NOT contradict, reinterpret, narrow, extend, or \
synthesize beyond what is written here.

CRITICAL: Your section summaries must ONLY reference decisions that appear \
verbatim in IdeaMemory above. Do not infer implementation details, numeric \
values, file paths, formulas, or architectural choices that the user did \
not explicitly state. If IdeaMemory says "weighted separately" you must \
NOT invent a weighting scheme. If IdeaMemory says "separate file" you must \
NOT specify which existing file to write to. Summaries must use the same \
language as IdeaMemory — paraphrase for brevity, never embellish.

{idea_memory}

Rate each section's readiness based ONLY on what IdeaMemory contains. \
If IdeaMemory has no entry for a section, rate it "low". \
If IdeaMemory has a clear decision for a section, rate it "high".

Readiness ratings:
- "high": Could write this section now with confidence
- "medium": Have partial information, brief would have gaps
- "low": Missing critical information, section would be speculative

Sections to rate:
1. problem_statement — Is the problem clear?
2. users_and_personas — Do we know who uses this and how?
3. requirements — Are functional requirements specific enough?
4. acceptance_criteria — Can we write Given/When/Then for core flows?
5. scope_boundaries — Do we know what's in and out?
6. technical_constraints — Do we know tech stack and integration points?

{deferred_note}

Before returning your response, verify each section summary against \
IdeaMemory. For every specific detail in your summary (file names, \
numbers, formulas, paths, formats), confirm it appears in IdeaMemory. \
If it doesn't, remove it.

Return ONLY valid JSON:
For the "evidence" field: quote ONLY from IdeaMemory above. \
If no entry addresses this section, write "No decision made yet."
{{"sections": {{"problem_statement": {{"readiness": "high", "evidence": "..."}}, ...}}, \
"gaps": [{{"section": "...", "description": "..."}}], \
"recommendation": "continue" | "ready"}}
"""


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


def _build_section_summaries(
    section_readiness: dict,
    idea_memory: list[dict],
) -> dict[str, str]:
    """Build display summaries from IdeaMemory, not LLM output.

    Args:
        section_readiness: Section name to readiness dict.
        idea_memory: Serialized IdeaMemory entries from state.

    Returns:
        Section name to summary text mapping.
    """
    summaries: dict[str, str] = {}
    for section_key in section_readiness:
        entries = [
            e["text"] for e in idea_memory
            if e.get("section") == section_key
        ]
        if entries:
            summaries[section_key] = " | ".join(entries)
        else:
            summaries[section_key] = "No decision made yet."
    return summaries


def make_estimate_confidence_node(
    llm: LLMClient,
    *,
    threshold: int = DEFAULT_CONFIDENCE_THRESHOLD,
) -> Callable[..., Any]:
    """Create the estimate_confidence node.

    Args:
        llm: LLM client for assessment generation.
        threshold: Confidence score to auto-proceed.

    Returns:
        Async node function.
    """

    async def estimate_confidence(state: BrainstormState) -> dict[str, Any]:
        """Assess section readiness and route to questions or approaches."""
        deferred = list(state.get("deferred_sections", []))

        # Absolute safety cap: force proceed
        if state.get("round_number", 0) >= SAFETY_CAP:
            return {"status": "proposing"}

        deferred_note = ""
        if deferred:
            deferred_note = (
                f"Deferred sections (do NOT rate): {', '.join(deferred)}"
            )

        cached_prefix = _build_brainstorm_cached_prefix(
            idea=state["idea"],
            product_context=state["product_context"],
            codebase_context=state["codebase_context"],
        )

        memory = IdeaMemory.from_state(
            state["idea"],
            list(state.get("idea_memory", [])),
            dict(state.get("idea_memory_counts", {"decision": 0, "rejection": 0})),
        )

        prompt = _ASSESSMENT_PROMPT.format(
            idea_memory=memory.format_for_prompt(),
            deferred_note=deferred_note,
        )
        raw = await llm.generate(
            prompt, system=BRAINSTORM_SYSTEM, cached_prefix=cached_prefix,
        )
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
                "stall_counter": 0,
                "previous_confidence": float(score),
            }

        # Stall detection
        prev = state.get("previous_confidence", 0.0)
        counter = state.get("stall_counter", 0)
        delta = score - prev

        if delta < 0 or delta >= 2:
            # Drop or significant gain → reset counter
            counter = 0
        else:
            # Flat or tiny wobble → increment
            counter += 1

        if counter >= 3:
            # Stall detected — skip interrupt, route to stall_exit node
            return {
                "section_readiness": section_readiness,
                "confidence_score": score,
                "gaps": gaps,
                "status": "stalled",
                "stall_counter": counter,
                "previous_confidence": float(score),
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
                "stall_counter": counter,
                "previous_confidence": float(score),
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
                "stall_counter": counter,
                "previous_confidence": float(new_score),
            }

        # Default: continue questioning
        return {
            "section_readiness": section_readiness,
            "confidence_score": score,
            "gaps": gaps,
            "status": "questioning",
            "stall_counter": counter,
            "previous_confidence": float(score),
        }

    return estimate_confidence
