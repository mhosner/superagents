"""Brainstorm subgraph — LangGraph StateGraph assembly."""

from __future__ import annotations

from typing import TYPE_CHECKING

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, StateGraph

from superagents_sdlc.brainstorm.nodes import (
    make_evaluate_coverage_node,
    make_explore_context_node,
    make_generate_design_section_node,
    make_generate_question_node,
    make_propose_approaches_node,
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
) -> CompiledStateGraph:
    """Build and compile the brainstorm subgraph.

    Args:
        llm: LLM client for node generation.
        checkpointer: LangGraph checkpointer. Defaults to InMemorySaver.

    Returns:
        Compiled StateGraph ready for invocation.
    """
    if checkpointer is None:
        checkpointer = InMemorySaver()

    builder = StateGraph(BrainstormState)

    # Add nodes
    builder.add_node("explore_context", make_explore_context_node())
    builder.add_node("generate_question", make_generate_question_node(llm))
    builder.add_node("evaluate_coverage", make_evaluate_coverage_node(llm))
    builder.add_node("propose_approaches", make_propose_approaches_node(llm))
    builder.add_node("generate_design_section", make_generate_design_section_node(llm))
    builder.add_node("synthesize_brief", make_synthesize_brief_node(llm))

    # Linear edges
    builder.set_entry_point("explore_context")
    builder.add_edge("explore_context", "generate_question")
    builder.add_edge("generate_question", "evaluate_coverage")
    builder.add_edge("propose_approaches", "generate_design_section")

    # Conditional: after coverage evaluation
    def route_after_coverage(state: BrainstormState) -> str:
        """Route back to questions or forward to approaches."""
        if state["status"] == "questioning":
            return "generate_question"
        return "propose_approaches"

    builder.add_conditional_edges(
        "evaluate_coverage",
        route_after_coverage,
        ["generate_question", "propose_approaches"],
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
