"""Tests for brainstorm subgraph assembly and interrupt flow."""

from __future__ import annotations

import json

import pytest
from langgraph.types import Command

from superagents_sdlc.brainstorm.graph import build_brainstorm_graph
from superagents_sdlc.skills.llm import StubLLMClient


def _initial_state() -> dict:
    """Create initial state for graph invocation."""
    return {
        "idea": "Add dark mode",
        "product_context": "Web app",
        "codebase_context": "",
        "transcript": [],
        "coverage": {},
        "approaches": [],
        "selected_approach": "",
        "design_sections": [],
        "current_section_idx": 0,
        "brief": "",
        "status": "exploring",
        "iteration": 0,
        "brief_revision_count": 0,
    }


def _make_full_stub() -> StubLLMClient:
    """Stub that handles all brainstorm node prompts.

    Key ordering matters -- StubLLMClient returns first match.
    """
    return StubLLMClient(responses={
        "Generate ONE": '{"question": "Who are the users?", "options": null}',
        "Evaluate which": json.dumps({
            "covered": [
                "users", "problem", "scope",
                "constraints", "integrations", "success_metrics",
            ],
            "missing": [],
            "sufficient": True,
        }),
        "Propose 2-3": json.dumps([
            {"name": "Simple", "description": "Minimal", "tradeoffs": "Less flexible"},
        ]),
        "Synthesize all": "# Design Brief\nComplete brief content",
        "Problem Statement": "## Problem\nContent",
        "Target Users": "## Users\nContent",
        "Requirements": "## Requirements\nContent",
        "Acceptance Criteria": "## Criteria\nContent",
        "Scope Boundaries": "## Scope\nContent",
        "Technical Constraints": "## Constraints\nContent",
    })


def _config(thread: str) -> dict:
    """Create a LangGraph config with the given thread ID."""
    return {"configurable": {"thread_id": thread}}


async def test_graph_compiles():
    """Graph builds and compiles without error."""
    graph = build_brainstorm_graph(_make_full_stub())
    assert graph is not None


async def test_first_interrupt_is_question():
    """First invocation interrupts with a question."""
    graph = build_brainstorm_graph(_make_full_stub())
    result = await graph.ainvoke(_initial_state(), _config("t-question"))

    interrupts = result.get("__interrupt__", ())
    assert len(interrupts) > 0
    assert interrupts[0].value["type"] == "question"
    assert "Who are the users?" in interrupts[0].value["question"]


async def test_question_to_approaches():
    """After answering with sufficient coverage, approaches interrupt fires."""
    graph = build_brainstorm_graph(_make_full_stub())
    cfg = _config("t-approaches")

    await graph.ainvoke(_initial_state(), cfg)
    result = await graph.ainvoke(Command(resume="Developers"), cfg)

    interrupts = result.get("__interrupt__", ())
    assert len(interrupts) > 0
    assert interrupts[0].value["type"] == "approaches"


async def test_approach_to_design_section():
    """After selecting an approach, design section interrupt fires."""
    graph = build_brainstorm_graph(_make_full_stub())
    cfg = _config("t-design")

    await graph.ainvoke(_initial_state(), cfg)
    await graph.ainvoke(Command(resume="Developers"), cfg)
    result = await graph.ainvoke(Command(resume="Simple"), cfg)

    interrupts = result.get("__interrupt__", ())
    assert len(interrupts) > 0
    assert interrupts[0].value["type"] == "design_section"


async def test_full_flow_to_completion():
    """Full brainstorm flow runs to completion with all approvals."""
    graph = build_brainstorm_graph(_make_full_stub())
    cfg = _config("t-full")

    # Question
    await graph.ainvoke(_initial_state(), cfg)
    # Answer
    await graph.ainvoke(Command(resume="Developers"), cfg)
    # Select approach
    await graph.ainvoke(Command(resume="Simple"), cfg)
    # Approve 6 design sections
    for _ in range(6):
        await graph.ainvoke(Command(resume="approve"), cfg)
    # Approve brief
    result = await graph.ainvoke(Command(resume="approve"), cfg)

    # No more interrupts -- graph complete
    interrupts = result.get("__interrupt__", ())
    assert len(interrupts) == 0
    assert result["status"] == "complete"
    assert "Design Brief" in result["brief"]


async def test_question_loop_max_iterations():
    """After 4 question rounds, evaluation forces transition to approaches."""
    llm = StubLLMClient(responses={
        "Generate ONE": '{"question": "Another question?", "options": null}',
        "Evaluate which": json.dumps({
            "covered": ["users"],
            "missing": ["problem", "scope"],
            "sufficient": False,
        }),
        "Propose 2-3": json.dumps([
            {"name": "A", "description": "d", "tradeoffs": "t"},
        ]),
    })
    graph = build_brainstorm_graph(llm)
    cfg = _config("t-maxloop")

    # First question
    await graph.ainvoke(_initial_state(), cfg)
    # Answer 4 questions (max iterations)
    for i in range(4):
        await graph.ainvoke(Command(resume=f"Answer {i}"), cfg)

    # After 4 iterations, should be past questioning
    snapshot = await graph.aget_state(cfg)
    assert snapshot.values.get("iteration", 0) >= 4


async def test_design_sections_to_synthesize():
    """After approving all 6 sections, next interrupt is brief review."""
    graph = build_brainstorm_graph(_make_full_stub())
    cfg = _config("t-sections")

    await graph.ainvoke(_initial_state(), cfg)
    await graph.ainvoke(Command(resume="Developers"), cfg)
    await graph.ainvoke(Command(resume="Simple"), cfg)

    # Approve 5 sections, check 6th triggers synthesize
    for _ in range(5):
        await graph.ainvoke(Command(resume="approve"), cfg)
    result = await graph.ainvoke(Command(resume="approve"), cfg)

    interrupts = result.get("__interrupt__", ())
    assert len(interrupts) > 0
    assert interrupts[0].value["type"] == "brief"


async def test_state_snapshot_has_transcript():
    """State snapshot contains transcript after answering a question."""
    graph = build_brainstorm_graph(_make_full_stub())
    cfg = _config("t-snapshot")

    await graph.ainvoke(_initial_state(), cfg)
    await graph.ainvoke(Command(resume="PMs"), cfg)

    snapshot = await graph.aget_state(cfg)
    assert len(snapshot.values["transcript"]) == 1
    assert snapshot.values["transcript"][0]["answer"] == "PMs"
