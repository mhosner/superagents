"""Brainstorm subgraph — LangGraph StateGraph assembly."""

from __future__ import annotations

from typing import TYPE_CHECKING

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, StateGraph

from superagents_sdlc.brainstorm.confidence import make_estimate_confidence_node
from superagents_sdlc.brainstorm.nodes import (
    make_explore_context_node,
    make_generate_design_section_node,
    make_generate_question_node,
    make_propose_approaches_node,
    make_stall_exit_node,
    make_synthesize_brief_node,
)
from superagents_sdlc.brainstorm.state import BrainstormState

if TYPE_CHECKING:
    from langgraph.graph.state import CompiledStateGraph
    from superagents_sdlc.skills.llm import LLMClient


def build_brainstorm_graph(
    llm: LLMClient,
    *,
    checkpointer: object | None = None,
    confidence_threshold: int = 80,
    max_rounds: int | None = None,  # noqa: ARG001
) -> CompiledStateGraph:
    """Build and compile the brainstorm subgraph.

    Args:
        llm: LLM client for node generation.
        checkpointer: LangGraph checkpointer. Defaults to InMemorySaver.
        confidence_threshold: Confidence score to auto-proceed.
        max_rounds: Deprecated. Stall detection replaces the hard cap.

    Returns:
        Compiled StateGraph ready for invocation.
    """
    if checkpointer is None:
        checkpointer = InMemorySaver()

    builder = StateGraph(BrainstormState)

    # Add nodes
    builder.add_node("explore_context", make_explore_context_node())
    builder.add_node("estimate_confidence", make_estimate_confidence_node(
        llm, threshold=confidence_threshold,
    ))
    builder.add_node("generate_question", make_generate_question_node(llm))
    builder.add_node("stall_exit", make_stall_exit_node())
    builder.add_node("propose_approaches", make_propose_approaches_node(llm))
    builder.add_node("generate_design_section", make_generate_design_section_node(llm))
    builder.add_node("synthesize_brief", make_synthesize_brief_node(llm))

    # Entry: explore → estimate_confidence
    builder.set_entry_point("explore_context")
    builder.add_edge("explore_context", "estimate_confidence")

    # After questions → estimate confidence again
    builder.add_edge("generate_question", "estimate_confidence")

    # After stall_exit → route based on status
    def route_after_stall_exit(state: BrainstormState) -> str:
        """Route after stall exit decision."""
        if state["status"] == "proposing":
            return "propose_approaches"
        return "generate_question"

    builder.add_conditional_edges(
        "stall_exit",
        route_after_stall_exit,
        ["propose_approaches", "generate_question"],
    )

    # After approach selection → design sections
    builder.add_edge("propose_approaches", "generate_design_section")

    # Conditional: after confidence estimation
    def route_after_confidence(state: BrainstormState) -> str:
        """Route to questions, stall exit, or approaches."""
        if state["status"] == "stalled":
            return "stall_exit"
        if state["status"] == "questioning":
            return "generate_question"
        return "propose_approaches"

    builder.add_conditional_edges(
        "estimate_confidence",
        route_after_confidence,
        ["generate_question", "stall_exit", "propose_approaches"],
    )

    # Conditional: after design section
    def route_after_section(state: BrainstormState) -> str:
        """Route to next section or to synthesis."""
        if state["status"] == "designing":
            return "generate_design_section"
        return "synthesize_brief"

    builder.add_conditional_edges(
        "generate_design_section",
        route_after_section,
        ["generate_design_section", "synthesize_brief"],
    )

    # Conditional: after brief synthesis
    def route_after_brief(state: BrainstormState) -> str:
        """Route to completion or revision loop."""
        if state["status"] == "complete":
            return END
        return "synthesize_brief"

    builder.add_conditional_edges(
        "synthesize_brief",
        route_after_brief,
        ["synthesize_brief", END],
    )

    return builder.compile(checkpointer=checkpointer)
