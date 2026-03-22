"""Node factory functions for the brainstorm subgraph."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from langgraph.types import interrupt

from superagents_sdlc.brainstorm.prompts import (
    APPROACHES_PROMPT,
    BRAINSTORM_SYSTEM,
    COVERAGE_PROMPT,
    DESIGN_SECTION_PROMPT,
    DESIGN_SECTIONS,
    QUESTION_PROMPT,
    SYNTHESIZE_PROMPT,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from superagents_sdlc.brainstorm.state import BrainstormState
    from superagents_sdlc.skills.llm import LLMClient

_COVERAGE_DIMENSIONS = [
    "users", "problem", "scope", "constraints", "integrations", "success_metrics",
]


def _extract_json(raw: str) -> Any:
    """Extract JSON from LLM response that may contain markdown fences or prose.

    Args:
        raw: Raw LLM response text.

    Returns:
        Parsed JSON object.

    Raises:
        ValueError: If no valid JSON found.
    """
    text = raw.strip()

    # Strip markdown code fences
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(lines[1:])
        if text.endswith("```"):
            text = text[:-3].strip()

    # Try parsing as-is first
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Find first { or [ and try parsing from there
    for i, ch in enumerate(text):
        if ch in ("{", "["):
            try:
                return json.loads(text[i:])
            except json.JSONDecodeError:
                continue

    msg = f"No valid JSON found in LLM response: {raw[:200]}"
    raise ValueError(msg)

MAX_QUESTION_ROUNDS = 4
MAX_BRIEF_REVISIONS = 2


def make_explore_context_node() -> Callable[..., Any]:
    """Create the explore_context node. No LLM needed.

    Returns:
        Async node function that initializes coverage tracking.
    """

    async def explore_context(state: BrainstormState) -> dict[str, Any]:  # noqa: ARG001
        """Initialize coverage dict and set status to questioning."""
        return {
            "status": "questioning",
            "coverage": dict.fromkeys(_COVERAGE_DIMENSIONS, False),
            "iteration": 0,
        }

    return explore_context


def make_generate_question_node(llm: LLMClient) -> Callable[..., Any]:
    """Create the generate_question node.

    Args:
        llm: LLM client for generating questions.

    Returns:
        Async node function that generates and presents a question.
    """

    async def generate_question(state: BrainstormState) -> dict[str, Any]:
        """Generate a clarifying question and interrupt for human answer."""
        # NOTE: On resume, this LLM call re-executes. Acceptable cost for simplicity.
        prompt = QUESTION_PROMPT.format(
            idea=state["idea"],
            product_context=state["product_context"],
            codebase_context=state["codebase_context"],
            transcript=json.dumps(state["transcript"]),
            coverage=json.dumps(state["coverage"]),
        )
        raw = await llm.generate(prompt, system=BRAINSTORM_SYSTEM)
        parsed = _extract_json(raw)

        answer = interrupt({
            "type": "question",
            "question": parsed["question"],
            "options": parsed.get("options"),
        })

        updated = list(state["transcript"])
        updated.append({"question": parsed["question"], "answer": answer})
        return {
            "transcript": updated,
            "iteration": state["iteration"] + 1,
        }

    return generate_question


def make_evaluate_coverage_node(llm: LLMClient) -> Callable[..., Any]:
    """Create the evaluate_coverage node.

    Args:
        llm: LLM client for evaluating coverage.

    Returns:
        Async node function that evaluates dimension coverage.
    """

    async def evaluate_coverage(state: BrainstormState) -> dict[str, Any]:
        """Evaluate which brainstorming dimensions are covered."""
        prompt = COVERAGE_PROMPT.format(
            idea=state["idea"],
            transcript=json.dumps(state["transcript"]),
        )
        raw = await llm.generate(prompt, system=BRAINSTORM_SYSTEM)
        parsed = _extract_json(raw)

        covered = {
            dim: dim in parsed["covered"]
            for dim in state["coverage"]
        }
        sufficient = parsed["sufficient"] or state["iteration"] >= MAX_QUESTION_ROUNDS

        return {
            "coverage": covered,
            "status": "proposing" if sufficient else "questioning",
        }

    return evaluate_coverage


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
        prompt = APPROACHES_PROMPT.format(
            idea=state["idea"],
            transcript=json.dumps(state["transcript"]),
            product_context=state["product_context"],
            codebase_context=state["codebase_context"],
        )
        raw = await llm.generate(prompt, system=BRAINSTORM_SYSTEM)
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

        prompt = DESIGN_SECTION_PROMPT.format(
            idea=state["idea"],
            selected_approach=state["selected_approach"],
            transcript=json.dumps(state["transcript"]),
            approved_sections=approved_text or "(none yet)",
            section_title=section_title,
        )
        content = await llm.generate(prompt, system=BRAINSTORM_SYSTEM)

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
        sections_text = "\n\n".join(
            f"### {s['title']}\n{s['content']}"
            for s in state["design_sections"]
        )

        prompt = SYNTHESIZE_PROMPT.format(
            idea=state["idea"],
            selected_approach=state["selected_approach"],
            sections=sections_text,
        )
        brief = await llm.generate(prompt, system=BRAINSTORM_SYSTEM)

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
