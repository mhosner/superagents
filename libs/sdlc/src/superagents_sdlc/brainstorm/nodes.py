"""Node factory functions for the brainstorm subgraph."""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Any

from langgraph.types import interrupt

from superagents_sdlc.brainstorm.idea_memory import IdeaMemory
from superagents_sdlc.brainstorm.prompts import (
    APPROACHES_PROMPT,
    BRAINSTORM_SYSTEM,
    DESIGN_SECTION_PROMPT,
    DESIGN_SECTIONS,
    QUESTION_PROMPT,
    SECTION_TITLES,
    SYNTHESIZE_PROMPT,
    _build_brainstorm_cached_prefix,
)
from superagents_sdlc.skills.json_utils import extract_json

if TYPE_CHECKING:
    from collections.abc import Callable

    from superagents_sdlc.brainstorm.state import BrainstormState
    from superagents_sdlc.skills.llm import LLMClient

# Re-export for backward compatibility; new code should import from json_utils.
_extract_json = extract_json

MAX_BRIEF_REVISIONS = 2

def _deferred_title(section: str) -> str:
    """Get display title for a deferred section.

    Args:
        section: Section key name.

    Returns:
        Human-readable title.
    """
    return SECTION_TITLES.get(section, section.replace("_", " ").title())
def _clean_option(text: str) -> str:
    """Strip leading letter prefix like ``a) `` or ``a. `` from an option.

    Args:
        text: Raw option string, possibly with LLM-generated prefix.

    Returns:
        Option text without letter prefix.
    """
    return re.sub(r"^[a-z][).]\s*", "", text)


def _resolve_answer(response: str, options: list[str] | None) -> str:
    """Resolve a letter/number selection to full option text.

    Args:
        response: Raw user input (e.g., "2", "b", or free text).
        options: Available options, or None for open-ended questions.

    Returns:
        Full option text if resolvable, otherwise the raw response.
    """
    if options is None:
        return response

    raw = response.strip().lower()

    # Try as 1-indexed number
    try:
        idx = int(raw) - 1
        if 0 <= idx < len(options):
            return options[idx]
    except ValueError:
        pass

    # Try as letter (a=0, b=1, ...)
    if len(raw) == 1 and raw.isalpha():
        idx = ord(raw) - ord("a")
        if 0 <= idx < len(options):
            return options[idx]

    return response


def _idea_memory_from_state(state: BrainstormState) -> IdeaMemory:
    """Reconstruct IdeaMemory from brainstorm state."""
    return IdeaMemory.from_state(
        state["idea"],
        list(state.get("idea_memory", [])),
        dict(state.get("idea_memory_counts", {"decision": 0, "rejection": 0})),
    )


def make_explore_context_node() -> Callable[..., Any]:
    """Create the explore_context node. No LLM needed.

    Returns:
        Async node function that initializes coverage tracking.
    """

    async def explore_context(state: BrainstormState) -> dict[str, Any]:  # noqa: ARG001
        """Initialize state and set status to questioning."""
        return {
            "status": "questioning",
            "section_readiness": {},
            "confidence_score": 0,
            "gaps": [],
            "deferred_sections": [],
            "round_number": 0,
            "idea_memory": [],
            "idea_memory_counts": {"decision": 0, "rejection": 0},
            "stall_counter": 0,
            "previous_confidence": 0.0,
        }

    return explore_context


def make_stall_exit_node() -> Callable[..., Any]:
    """Create the stall_exit node for confidence plateau handling.

    Returns:
        Async node function that presents stall exit options.
    """

    async def stall_exit(state: BrainstormState) -> dict[str, Any]:
        """Present stall exit options when confidence plateaus."""
        response = interrupt({
            "type": "stall_exit",
            "confidence": state.get("confidence_score", 0),
            "gaps": state.get("gaps", []),
            "options": ["proceed", "continue"],
        })

        response_str = str(response).strip().lower()

        if response_str == "proceed":
            return {"status": "proposing"}

        # Default: continue questioning with reset counter
        return {"status": "questioning", "stall_counter": 0}

    return stall_exit


def make_generate_question_node(llm: LLMClient) -> Callable[..., Any]:
    """Create the generate_question node.

    Args:
        llm: LLM client for generating questions.

    Returns:
        Async node function that generates and presents a question.
    """

    async def generate_question(state: BrainstormState) -> dict[str, Any]:
        """Generate gap-targeting questions and interrupt for human answers."""
        # NOTE: On resume, this LLM call re-executes. Acceptable cost for simplicity.
        readiness = state.get("section_readiness", {})
        gaps = state.get("gaps", [])

        cached_prefix = _build_brainstorm_cached_prefix(
            idea=state["idea"],
            product_context=state["product_context"],
            codebase_context=state["codebase_context"],
        )
        prompt = QUESTION_PROMPT.format(
            idea_memory=_idea_memory_from_state(state).format_for_prompt(),
            section_readiness=json.dumps(readiness),
            gaps=json.dumps(gaps),
        )
        raw = await llm.generate(prompt, system=BRAINSTORM_SYSTEM, cached_prefix=cached_prefix)
        parsed = _extract_json(raw)

        questions = parsed.get("questions", [])
        if not questions:
            # Fallback for old-format single question
            questions = [{"question": parsed.get("question", "?"), "options": parsed.get("options")}]

        answers = interrupt({
            "type": "questions",
            "questions": questions,
            "round": state.get("round_number", 0) + 1,
            "confidence": state.get("confidence_score", 0),
            "gaps_remaining": len(gaps),
        })

        # answers is a list of answer strings (one per question)
        if isinstance(answers, str):
            answers = [answers]

        updated = list(state["transcript"])
        for question, answer in zip(questions, answers, strict=False):
            raw_options = question.get("options")
            cleaned = [_clean_option(o) for o in raw_options] if raw_options else None
            resolved = _resolve_answer(answer, cleaned)
            updated.append({
                "question": question.get("question", "?"),
                "options": cleaned,
                "answer": resolved,
                "targets_section": question.get("targets_section", ""),
            })

        # Update IdeaMemory with decisions
        memory = IdeaMemory.from_state(
            state["idea"],
            list(state.get("idea_memory", [])),
            dict(state.get("idea_memory_counts", {"decision": 0, "rejection": 0})),
        )
        for entry in updated[len(state["transcript"]):]:  # only new entries
            section = entry.get("targets_section", "")
            title = SECTION_TITLES.get(
                section, section.replace("_", " ").title(),
            )
            memory.add_decision(title=title, text=entry["answer"], section=section)

        return {
            "transcript": updated,
            "round_number": state.get("round_number", 0) + 1,
            "idea_memory": memory.to_state(),
            "idea_memory_counts": memory.counts,
        }

    return generate_question



def make_propose_approaches_node(llm: LLMClient) -> Callable[..., Any]:
    """Create the propose_approaches node.

    Args:
        llm: LLM client for generating approaches.

    Returns:
        Async node function that proposes approaches and interrupts for selection.
    """

    async def propose_approaches(state: BrainstormState) -> dict[str, Any]:
        """Generate approaches and interrupt for human selection."""
        # NOTE: On resume, this LLM call re-executes. Acceptable cost for simplicity.
        cached_prefix = _build_brainstorm_cached_prefix(
            idea=state["idea"],
            product_context=state["product_context"],
            codebase_context=state["codebase_context"],
        )
        prompt = APPROACHES_PROMPT.format(
            idea_memory=_idea_memory_from_state(state).format_for_prompt(),
        )
        raw = await llm.generate(prompt, system=BRAINSTORM_SYSTEM, cached_prefix=cached_prefix)
        approaches = _extract_json(raw)

        selected = interrupt({
            "type": "approaches",
            "approaches": approaches,
        })

        return {
            "approaches": approaches,
            "selected_approach": selected,
            "status": "designing",
            "current_section_idx": 0,
        }

    return propose_approaches


def make_generate_design_section_node(llm: LLMClient) -> Callable[..., Any]:
    """Create the generate_design_section node.

    Args:
        llm: LLM client for generating design sections.

    Returns:
        Async node function that generates one section and interrupts for review.
    """

    async def generate_design_section(state: BrainstormState) -> dict[str, Any]:
        """Generate one design section and interrupt for approval or edit."""
        # NOTE: On resume, this LLM call re-executes. Acceptable cost for simplicity.
        idx = state["current_section_idx"]
        section_title = DESIGN_SECTIONS[idx]

        approved_text = "\n\n".join(
            f"### {s['title']}\n{s['content']}"
            for s in state["design_sections"]
            if s.get("approved")
        )

        cached_prefix = _build_brainstorm_cached_prefix(
            idea=state["idea"],
            product_context=state["product_context"],
            codebase_context=state["codebase_context"],
        )
        prompt = DESIGN_SECTION_PROMPT.format(
            selected_approach=state["selected_approach"],
            idea_memory=_idea_memory_from_state(state).format_for_prompt(),
            approved_sections=approved_text or "(none yet)",
            section_title=section_title,
        )
        content = await llm.generate(prompt, system=BRAINSTORM_SYSTEM, cached_prefix=cached_prefix)

        response = interrupt({
            "type": "design_section",
            "title": section_title,
            "content": content,
        })

        # If approved, use LLM content. Otherwise, use human's edited text.
        final_content = content if response.strip().lower() in ("approve", "a") else response

        updated_sections = list(state["design_sections"])
        updated_sections.append({
            "title": section_title,
            "content": final_content,
            "approved": True,
        })

        next_idx = idx + 1
        next_status = "designing" if next_idx < len(DESIGN_SECTIONS) else "synthesizing"

        return {
            "design_sections": updated_sections,
            "current_section_idx": next_idx,
            "status": next_status,
        }

    return generate_design_section


def make_synthesize_brief_node(llm: LLMClient) -> Callable[..., Any]:
    """Create the synthesize_brief node.

    Args:
        llm: LLM client for synthesizing the brief.

    Returns:
        Async node function that synthesizes and interrupts for approval.
    """

    async def synthesize_brief(state: BrainstormState) -> dict[str, Any]:
        """Synthesize design sections into a brief and interrupt for approval."""
        # NOTE: On resume, this LLM call re-executes. Acceptable cost for simplicity.
        deferred = state.get("deferred_sections", [])
        sections_text = "\n\n".join(
            f"### {s['title']}\n{s['content']}"
            for s in state["design_sections"]
        )
        if deferred:
            annotations = "\n\n".join(
                f"### {_deferred_title(section)}\n"
                f"> This section was not addressed during brainstorming "
                f"and is marked for downstream resolution.\n\n"
                f"[Section intentionally left minimal — to be completed "
                f"by the Architect based on implementation context.]"
                for section in deferred
            )
            sections_text = f"{sections_text}\n\n{annotations}"

        cached_prefix = _build_brainstorm_cached_prefix(
            idea=state["idea"],
            product_context=state["product_context"],
            codebase_context=state["codebase_context"],
        )
        prompt = SYNTHESIZE_PROMPT.format(
            selected_approach=state["selected_approach"],
            idea_memory=_idea_memory_from_state(state).format_for_prompt(),
            sections=sections_text,
        )
        brief = await llm.generate(prompt, system=BRAINSTORM_SYSTEM, cached_prefix=cached_prefix)

        response = interrupt({
            "type": "brief",
            "brief": brief,
        })

        if response.strip().lower() in ("approve", "a"):
            return {"brief": brief, "status": "complete"}

        # Revision requested
        revision_count = state["brief_revision_count"] + 1
        if revision_count >= MAX_BRIEF_REVISIONS:
            return {"brief": brief, "status": "complete", "brief_revision_count": revision_count}

        return {"brief_revision_count": revision_count, "status": "synthesizing"}

    return synthesize_brief
