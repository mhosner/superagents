"""Tests for brainstorm subgraph assembly and interrupt flow."""

from __future__ import annotations

import json

import pytest
from langgraph.types import Command

from superagents_sdlc.brainstorm.confidence import SECTIONS
from superagents_sdlc.brainstorm.graph import build_brainstorm_graph
from superagents_sdlc.skills.llm import StubLLMClient


def _initial_state() -> dict:
    """Create initial state for graph invocation."""
    return {
        "idea": "Add dark mode",
        "product_context": "Web app",
        "codebase_context": "",
        "transcript": [],
        "section_readiness": {},
        "confidence_score": 0,
        "gaps": [],
        "deferred_sections": [],
        "round_number": 0,
        "approaches": [],
        "selected_approach": "",
        "design_sections": [],
        "current_section_idx": 0,
        "brief": "",
        "status": "exploring",
        "brief_revision_count": 0,
        "idea_memory": [],
        "idea_memory_counts": {"decision": 0, "rejection": 0},
    }


def _all_high_assessment():
    return json.dumps({
        "sections": {s: {"readiness": "high", "evidence": "clear"} for s in SECTIONS},
        "gaps": [],
        "recommendation": "ready",
    })


def _low_assessment():
    return json.dumps({
        "sections": {
            "problem_statement": {"readiness": "high", "evidence": "clear"},
            "users_and_personas": {"readiness": "high", "evidence": "clear"},
            "requirements": {"readiness": "medium", "evidence": "partial"},
            "acceptance_criteria": {"readiness": "low", "evidence": "missing"},
            "scope_boundaries": {"readiness": "medium", "evidence": "vague"},
            "technical_constraints": {"readiness": "low", "evidence": "none"},
        },
        "gaps": [
            {"section": "acceptance_criteria", "description": "No error paths"},
            {"section": "technical_constraints", "description": "No storage discussion"},
        ],
        "recommendation": "continue",
    })


def _make_full_stub() -> StubLLMClient:
    """Stub that handles all brainstorm node prompts.

    Key ordering matters -- StubLLMClient returns first match.
    """
    return StubLLMClient(responses={
        # Confidence assessment — must come before question prompts
        "rate the readiness": _all_high_assessment(),
        # Questions (gap-targeting)
        "## Gaps to address": json.dumps({
            "questions": [
                {"question": "Who are the users?", "options": None, "targets_section": "users_and_personas"},
            ],
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


async def test_confidence_above_threshold_proceeds_to_approaches():
    """All-high confidence auto-proceeds to approaches interrupt."""
    graph = build_brainstorm_graph(_make_full_stub())
    result = await graph.ainvoke(_initial_state(), _config("t-high-conf"))

    # Should skip questions and go straight to approaches
    interrupts = result.get("__interrupt__", ())
    assert len(interrupts) > 0
    assert interrupts[0].value["type"] == "approaches"


async def test_confidence_below_threshold_shows_assessment():
    """Low confidence interrupts with confidence_assessment."""
    stub = StubLLMClient(responses={
        "rate the readiness": _low_assessment(),
        "## Gaps to address": json.dumps({
            "questions": [{"question": "Q?", "options": None, "targets_section": "requirements"}],
        }),
    })
    graph = build_brainstorm_graph(stub)
    result = await graph.ainvoke(_initial_state(), _config("t-low-conf"))

    interrupts = result.get("__interrupt__", ())
    assert len(interrupts) > 0
    assert interrupts[0].value["type"] == "confidence_assessment"


async def test_continue_loops_to_questions():
    """'continue' response loops to question generation."""
    stub = StubLLMClient(responses={
        "rate the readiness": _low_assessment(),
        "## Gaps to address": json.dumps({
            "questions": [{"question": "Storage?", "options": ["JSON", "SQLite"], "targets_section": "technical_constraints"}],
        }),
    })
    graph = build_brainstorm_graph(stub)
    cfg = _config("t-continue")

    # First: confidence assessment interrupt
    await graph.ainvoke(_initial_state(), cfg)
    # Continue → questions interrupt
    result = await graph.ainvoke(Command(resume="continue"), cfg)

    interrupts = result.get("__interrupt__", ())
    assert len(interrupts) > 0
    assert interrupts[0].value["type"] == "questions"


async def test_full_flow_to_completion():
    """Full brainstorm flow with high confidence runs to completion."""
    graph = build_brainstorm_graph(_make_full_stub())
    cfg = _config("t-full")

    # High confidence → approaches interrupt
    result = await graph.ainvoke(_initial_state(), cfg)
    # Select approach
    result = await graph.ainvoke(Command(resume="Simple"), cfg)
    # Approve 6 design sections
    for _ in range(6):
        result = await graph.ainvoke(Command(resume="approve"), cfg)
    # Approve brief
    result = await graph.ainvoke(Command(resume="approve"), cfg)

    interrupts = result.get("__interrupt__", ())
    assert len(interrupts) == 0
    assert result["status"] == "complete"
    assert "Design Brief" in result["brief"]


async def test_override_forces_proceed():
    """'override' response bypasses threshold and proceeds to approaches."""
    stub = StubLLMClient(responses={
        "rate the readiness": _low_assessment(),
        "Propose 2-3": json.dumps([
            {"name": "A", "description": "d", "tradeoffs": "t"},
        ]),
    })
    graph = build_brainstorm_graph(stub)
    cfg = _config("t-override")

    await graph.ainvoke(_initial_state(), cfg)
    result = await graph.ainvoke(Command(resume="override"), cfg)

    interrupts = result.get("__interrupt__", ())
    assert len(interrupts) > 0
    assert interrupts[0].value["type"] == "approaches"


async def test_state_snapshot_has_transcript():
    """State snapshot contains transcript after answering questions."""
    stub = StubLLMClient(responses={
        "rate the readiness": _low_assessment(),
        "## Gaps to address": json.dumps({
            "questions": [{"question": "Q?", "options": None, "targets_section": "requirements"}],
        }),
    })
    graph = build_brainstorm_graph(stub)
    cfg = _config("t-snapshot")

    # Confidence assessment
    await graph.ainvoke(_initial_state(), cfg)
    # Continue
    await graph.ainvoke(Command(resume="continue"), cfg)
    # Answer question
    await graph.ainvoke(Command(resume=["My answer"]), cfg)

    snapshot = await graph.aget_state(cfg)
    assert len(snapshot.values["transcript"]) == 1
    assert snapshot.values["transcript"][0]["answer"] == "My answer"
    assert snapshot.values["round_number"] >= 1
