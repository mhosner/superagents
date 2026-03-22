"""Tests for brainstorm subgraph nodes."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest
from langgraph.errors import GraphInterrupt

from superagents_sdlc.brainstorm.nodes import (
    make_evaluate_coverage_node,
    make_explore_context_node,
    make_generate_design_section_node,
    make_generate_question_node,
    make_propose_approaches_node,
    make_synthesize_brief_node,
)
from superagents_sdlc.skills.llm import StubLLMClient

if TYPE_CHECKING:
    from superagents_sdlc.brainstorm.state import BrainstormState

_INTERRUPT_PATH = "superagents_sdlc.brainstorm.nodes.interrupt"

_ALL_DIMS = [
    "users", "problem", "scope",
    "constraints", "integrations", "success_metrics",
]


def _make_state(**overrides: object) -> dict:
    """Create a default BrainstormState dict with optional overrides."""
    base: dict = {
        "idea": "Add dark mode",
        "product_context": "Web app",
        "codebase_context": "",
        "transcript": [],
        "coverage": {
            "users": False, "problem": False, "scope": False,
            "constraints": False, "integrations": False, "success_metrics": False,
        },
        "approaches": [],
        "selected_approach": "",
        "design_sections": [],
        "current_section_idx": 0,
        "brief": "",
        "status": "exploring",
        "iteration": 0,
        "brief_revision_count": 0,
    }
    base.update(overrides)
    return base


def _raise_interrupt(value):
    raise GraphInterrupt(value)


def test_brainstorm_state_is_typeddict():
    state: BrainstormState = _make_state()  # type: ignore[assignment]
    assert state["status"] == "exploring"
    assert len(state) == 13


async def test_explore_context_initializes_state():
    node = make_explore_context_node()
    result = await node(_make_state())

    assert result["status"] == "questioning"
    assert all(v is False for v in result["coverage"].values())
    assert len(result["coverage"]) == 6
    assert result["iteration"] == 0


async def test_generate_question_calls_llm_and_interrupts():
    llm = StubLLMClient(responses={
        "Generate ONE": '{"question": "Who are the users?", "options": ["devs", "PMs"]}',
    })
    node = make_generate_question_node(llm)

    with (
        patch(_INTERRUPT_PATH, side_effect=_raise_interrupt),
        pytest.raises(GraphInterrupt),
    ):
        await node(_make_state())

    assert len(llm.calls) == 1


async def test_generate_question_returns_answer_on_resume():
    llm = StubLLMClient(responses={
        "Generate ONE": '{"question": "Who are the users?", "options": null}',
    })
    node = make_generate_question_node(llm)

    with patch(_INTERRUPT_PATH, return_value="Developers"):
        result = await node(_make_state())

    assert result["transcript"] == [{"question": "Who are the users?", "answer": "Developers"}]
    assert result["iteration"] == 1


async def test_evaluate_coverage_sufficient():
    all_covered = _ALL_DIMS
    llm = StubLLMClient(responses={
        "Evaluate which": json.dumps({
            "covered": all_covered,
            "missing": [],
            "sufficient": True,
        }),
    })
    node = make_evaluate_coverage_node(llm)
    result = await node(_make_state(iteration=2))

    assert result["status"] == "proposing"
    assert all(result["coverage"].values())


async def test_evaluate_coverage_needs_more():
    llm = StubLLMClient(responses={
        "Evaluate which": json.dumps({
            "covered": ["users"],
            "missing": ["problem", "scope"],
            "sufficient": False,
        }),
    })
    node = make_evaluate_coverage_node(llm)
    result = await node(_make_state(iteration=1))

    assert result["status"] == "questioning"


async def test_evaluate_coverage_forced_at_max_iterations():
    llm = StubLLMClient(responses={
        "Evaluate which": json.dumps({
            "covered": ["users"],
            "missing": ["problem"],
            "sufficient": False,
        }),
    })
    node = make_evaluate_coverage_node(llm)
    result = await node(_make_state(iteration=4))

    assert result["status"] == "proposing"


async def test_propose_approaches_interrupts():
    llm = StubLLMClient(responses={
        "Propose 2-3": '[{"name": "Simple", "description": "d", "tradeoffs": "t"}]',
    })
    node = make_propose_approaches_node(llm)

    with (
        patch(_INTERRUPT_PATH, side_effect=_raise_interrupt),
        pytest.raises(GraphInterrupt),
    ):
        await node(_make_state(status="proposing"))


async def test_propose_approaches_returns_selection_on_resume():
    llm = StubLLMClient(responses={
        "Propose 2-3": '[{"name": "Simple", "description": "d", "tradeoffs": "t"}]',
    })
    node = make_propose_approaches_node(llm)

    with patch(_INTERRUPT_PATH, return_value="Simple"):
        result = await node(_make_state(status="proposing"))

    assert result["selected_approach"] == "Simple"
    assert result["status"] == "designing"
    assert result["current_section_idx"] == 0
    assert len(result["approaches"]) == 1


async def test_generate_design_section_approve():
    llm = StubLLMClient(responses={
        "Problem Statement": "## Problem\nContent here",
    })
    node = make_generate_design_section_node(llm)

    with patch(_INTERRUPT_PATH, return_value="approve"):
        result = await node(_make_state(
            status="designing",
            selected_approach="Simple",
            current_section_idx=0,
        ))

    assert len(result["design_sections"]) == 1
    assert result["design_sections"][0]["approved"] is True
    assert result["design_sections"][0]["content"] == "## Problem\nContent here"
    assert result["current_section_idx"] == 1
    assert result["status"] == "designing"


async def test_generate_design_section_edit():
    llm = StubLLMClient(responses={
        "Problem Statement": "## Problem\nDraft",
    })
    node = make_generate_design_section_node(llm)

    edited = "## Problem\nRevised content with more detail"
    with patch(_INTERRUPT_PATH, return_value=edited):
        result = await node(_make_state(
            status="designing",
            selected_approach="Simple",
            current_section_idx=0,
        ))

    assert result["design_sections"][0]["content"] == edited
    assert result["design_sections"][0]["approved"] is True


async def test_generate_design_section_last_sets_synthesizing():
    llm = StubLLMClient(responses={
        "Technical Constraints": "## Constraints\nContent",
    })
    node = make_generate_design_section_node(llm)

    existing = [{"title": f"S{i}", "content": "c", "approved": True} for i in range(5)]
    with patch(_INTERRUPT_PATH, return_value="approve"):
        result = await node(_make_state(
            status="designing",
            selected_approach="Simple",
            current_section_idx=5,
            design_sections=existing,
        ))

    assert result["status"] == "synthesizing"
    assert result["current_section_idx"] == 6
    assert len(result["design_sections"]) == 6


async def test_synthesize_brief_approved():
    llm = StubLLMClient(responses={
        "Synthesize all": "# Design Brief\nFull content",
    })
    node = make_synthesize_brief_node(llm)

    sections = [{"title": "T", "content": "C", "approved": True}]
    with patch(_INTERRUPT_PATH, return_value="approve"):
        result = await node(_make_state(
            status="synthesizing",
            design_sections=sections,
            selected_approach="Simple",
        ))

    assert result["status"] == "complete"
    assert "Design Brief" in result["brief"]


async def test_synthesize_brief_revision():
    llm = StubLLMClient(responses={
        "Synthesize all": "# Design Brief\nV1",
    })
    node = make_synthesize_brief_node(llm)

    revision_value = "Add more caching detail"
    with patch(_INTERRUPT_PATH, return_value=revision_value):
        result = await node(_make_state(
            status="synthesizing",
            design_sections=[{"title": "T", "content": "C", "approved": True}],
            selected_approach="Simple",
            brief_revision_count=0,
        ))

    assert result["status"] == "synthesizing"
    assert result["brief_revision_count"] == 1


async def test_synthesize_brief_max_revisions():
    llm = StubLLMClient(responses={
        "Synthesize all": "# Design Brief\nV3",
    })
    node = make_synthesize_brief_node(llm)

    with patch(_INTERRUPT_PATH, return_value="More changes please"):
        result = await node(_make_state(
            status="synthesizing",
            design_sections=[{"title": "T", "content": "C", "approved": True}],
            selected_approach="Simple",
            brief_revision_count=2,
        ))

    assert result["status"] == "complete"
