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

For gap descriptions: describe what is MISSING, not what was decided. \
Do not infer implementation details, numeric values, file paths, \
formulas, or architectural choices that the user did not explicitly state.

Return ONLY valid JSON:
{{"sections": {{"problem_statement": {{"readiness": "high"}}, ...}}, \
"gaps": [{{"section": "...", "description": "what is missing"}}]}}
"""


def compute_confidence(sections: dict, deferred: list[str]) -> int:
    """Compute confidence score from section readiness ratings.

    Args:
        sections: Map of section name to {readiness} dict.
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


def make_estimate_confidence_node(  # noqa: C901, PLR0915
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

    def _compute_readiness_changes(
        old: dict, new: dict,
    ) -> dict[str, dict[str, str]]:
        """Compare old and new section readiness, return changes."""
        changes: dict[str, dict[str, str]] = {}
        for section, info in new.items():
            new_r = info.get("readiness", "?")
            old_info = old.get(section)
            old_r = old_info.get("readiness", "?") if old_info else "?"
            if new_r != old_r:
                changes[section] = {"from": old_r, "to": new_r}
        return changes

    async def estimate_confidence(state: BrainstormState) -> dict[str, Any]:  # noqa: C901, PLR0911, PLR0915
        """Assess section readiness and route to questions or approaches.

        Uses a two-pass pattern to avoid double LLM execution on
        LangGraph interrupt/resume.  Pass 1 calls the LLM, caches
        the result, and returns with ``status="awaiting_input"``
        (no interrupt).  The graph routes back to this node.
        Pass 2 reads the cache, calls ``interrupt()`` for HITL,
        and handles the user's response.
        """
        deferred = list(state.get("deferred_sections", []))

        # Absolute safety cap: force proceed
        if state.get("round_number", 0) >= SAFETY_CAP:
            return {"status": "proposing", "section_summaries": {}, "cached_assessment": {}}

        # --- Pass 2: cached assessment exists → interrupt for HITL ---
        cached = state.get("cached_assessment") or {}
        if cached:
            section_readiness = cached["section_readiness"]
            score = cached["confidence_score"]
            gaps = cached["gaps"]
            summaries = cached["section_summaries"]
            counter = cached["stall_counter"]

            response = interrupt({
                "type": "confidence_assessment",
                "confidence": score,
                "threshold": threshold,
                "round": state.get("round_number", 0),
                "sections": section_readiness,
                "summaries": summaries,
                "gaps": gaps,
                "previous_gap_count": len(state.get("gaps", [])),
                "options": ["continue", "defer", "override"],
            })

            response_str = str(response).strip().lower()

            delta = cached.get("confidence_delta", 0)
            changes = cached.get("readiness_changes", {})
            narrative = list(state.get("narrative_entries", []))

            base = {
                "section_readiness": section_readiness,
                "confidence_score": score,
                "gaps": gaps,
                "stall_counter": counter,
                "previous_confidence": float(score),
                "section_summaries": summaries,
                "cached_assessment": {},
            }

            round_num = state.get("round_number", 0)
            assessment_entry = {
                "event": "assessment",
                "round": round_num,
                "confidence": score,
                "confidence_delta": delta,
                "gap_count": len(gaps),
                "section_readiness": section_readiness,
                "readiness_changes": changes,
            }

            if response_str == "override":
                narrative.append(assessment_entry)
                narrative.append({"event": "override", "confidence": score})
                return {**base, "status": "proposing", "narrative_entries": narrative}

            if response_str.startswith("defer"):
                parts = response_str.split(maxsplit=1)
                new_deferred = deferred
                if len(parts) > 1:
                    names = [s.strip() for s in parts[1].split(",") if s.strip()]
                    new_deferred = list(set(deferred + names))
                new_score = compute_confidence(section_readiness, new_deferred)
                new_status = "proposing" if new_score >= threshold else "questioning"
                narrative.append(assessment_entry)
                narrative.append({
                    "event": "deferral",
                    "confidence": new_score,
                    "deferred_sections": new_deferred,
                })
                return {
                    **base,
                    "confidence_score": new_score,
                    "gaps": [g for g in gaps if g["section"] not in new_deferred],
                    "deferred_sections": new_deferred,
                    "status": new_status,
                    "previous_confidence": float(new_score),
                    "narrative_entries": narrative,
                }

            if response_str == "auto_continue":
                narrative.append({
                    "event": "auto_continue",
                    "round": round_num,
                    "confidence": score,
                    "confidence_delta": delta,
                    "gap_count": len(gaps),
                })
                return {**base, "status": "questioning", "narrative_entries": narrative}

            # Default: continue questioning
            narrative.append(assessment_entry)
            return {**base, "status": "questioning", "narrative_entries": narrative}

        # --- Pass 1: no cache → call LLM, compute, cache result ---
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
        summaries = _build_section_summaries(
            section_readiness,
            list(state.get("idea_memory", [])),
        )

        # Auto-proceed if above threshold — no interrupt needed
        if score >= threshold:
            prev = state.get("previous_confidence", 0.0)
            auto_delta = score - int(prev)
            old_readiness = dict(state.get("section_readiness", {}))
            auto_changes = _compute_readiness_changes(old_readiness, section_readiness)
            narrative = list(state.get("narrative_entries", []))
            narrative.append({
                "event": "assessment",
                "round": state.get("round_number", 0),
                "confidence": score,
                "confidence_delta": auto_delta,
                "gap_count": len(gaps),
                "section_readiness": section_readiness,
                "readiness_changes": auto_changes,
            })
            return {
                "section_readiness": section_readiness,
                "confidence_score": score,
                "gaps": gaps,
                "status": "proposing",
                "stall_counter": 0,
                "previous_confidence": float(score),
                "section_summaries": summaries,
                "cached_assessment": {},
                "narrative_entries": narrative,
            }

        # Stall detection
        prev = state.get("previous_confidence", 0.0)
        counter = state.get("stall_counter", 0)
        delta = score - prev

        if delta < 0 or delta >= 2:
            counter = 0
        else:
            counter += 1

        confidence_delta = score - int(prev)
        old_readiness = dict(state.get("section_readiness", {}))
        readiness_changes = _compute_readiness_changes(
            old_readiness, section_readiness,
        )

        if counter >= 3:
            # Stall detected — route to stall_exit, no interrupt
            narrative = list(state.get("narrative_entries", []))
            narrative.append({
                "event": "assessment",
                "round": state.get("round_number", 0),
                "confidence": score,
                "confidence_delta": confidence_delta,
                "gap_count": len(gaps),
                "section_readiness": section_readiness,
                "readiness_changes": readiness_changes,
            })
            return {
                "section_readiness": section_readiness,
                "confidence_score": score,
                "gaps": gaps,
                "status": "stalled",
                "stall_counter": counter,
                "previous_confidence": float(score),
                "section_summaries": summaries,
                "cached_assessment": {},
                "narrative_entries": narrative,
            }

        # Below threshold, no stall — cache and route back for HITL
        return {
            "section_readiness": section_readiness,
            "confidence_score": score,
            "gaps": gaps,
            "status": "awaiting_input",
            "stall_counter": counter,
            "previous_confidence": float(score),
            "section_summaries": summaries,
            "cached_assessment": {
                "section_readiness": section_readiness,
                "confidence_score": score,
                "gaps": gaps,
                "section_summaries": summaries,
                "stall_counter": counter,
                "confidence_delta": confidence_delta,
                "readiness_changes": readiness_changes,
            },
        }

    return estimate_confidence
