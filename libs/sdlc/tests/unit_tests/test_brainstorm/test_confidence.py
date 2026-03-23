"""Tests for confidence computation and estimate_confidence node."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from langgraph.errors import GraphInterrupt

from superagents_sdlc.brainstorm.confidence import (
    READINESS_SCORES,
    SECTIONS,
    compute_confidence,
    make_estimate_confidence_node,
)
from superagents_sdlc.skills.llm import StubLLMClient

_INTERRUPT_PATH = "superagents_sdlc.brainstorm.confidence.interrupt"


# -- compute_confidence tests --


def test_compute_all_high():
    sections = {s: {"readiness": "high", "evidence": "good"} for s in SECTIONS}
    assert compute_confidence(sections, []) == 90


def test_compute_all_low():
    sections = {s: {"readiness": "low", "evidence": "missing"} for s in SECTIONS}
    assert compute_confidence(sections, []) == 30


def test_compute_mixed():
    """3 high (90*3=270) + 3 low (30*3=90) = 360 / 6 = 60."""
    sections = {}
    for i, s in enumerate(SECTIONS):
        sections[s] = {
            "readiness": "high" if i < 3 else "low",
            "evidence": "test",
        }
    assert compute_confidence(sections, []) == 60


def test_compute_with_deferred():
    """Deferred sections excluded. 2 high out of 4 active, 2 deferred."""
    sections = {s: {"readiness": "high", "evidence": "ok"} for s in SECTIONS}
    sections["technical_constraints"]["readiness"] = "low"
    sections["scope_boundaries"]["readiness"] = "low"
    deferred = ["technical_constraints", "scope_boundaries"]
    # 4 active sections all high: 90
    assert compute_confidence(sections, deferred) == 90


def test_compute_all_deferred():
    """All sections deferred returns 100."""
    sections = {s: {"readiness": "low", "evidence": "x"} for s in SECTIONS}
    assert compute_confidence(sections, list(SECTIONS)) == 100


# -- estimate_confidence node tests --


def _make_state(**overrides):
    base = {
        "idea": "Add dark mode",
        "product_context": "Web app",
        "codebase_context": "",
        "transcript": [{"question": "Who?", "answer": "Devs"}],
        "section_readiness": {},
        "confidence_score": 0,
        "gaps": [],
        "deferred_sections": [],
        "round_number": 1,
        "approaches": [],
        "selected_approach": "",
        "design_sections": [],
        "current_section_idx": 0,
        "brief": "",
        "status": "questioning",
        "brief_revision_count": 0,
    }
    base.update(overrides)
    return base


def _high_assessment():
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
            "technical_constraints": {"readiness": "low", "evidence": "no discussion"},
        },
        "gaps": [
            {"section": "acceptance_criteria", "description": "No error paths"},
            {"section": "technical_constraints", "description": "No storage discussion"},
        ],
        "recommendation": "continue",
    })


async def test_estimate_all_high_scores_above_threshold():
    llm = StubLLMClient(responses={"rate the readiness": _high_assessment()})
    node = make_estimate_confidence_node(llm)
    result = await node(_make_state())

    assert result["confidence_score"] == 90
    assert result["status"] == "proposing"
    assert result["gaps"] == []


async def test_estimate_mixed_scores_below_threshold():
    llm = StubLLMClient(responses={"rate the readiness": _low_assessment()})
    node = make_estimate_confidence_node(llm)

    def _raise_interrupt(value):
        raise GraphInterrupt(value)

    with (
        patch(_INTERRUPT_PATH, side_effect=_raise_interrupt),
        pytest.raises(GraphInterrupt),
    ):
        await node(_make_state())


async def test_estimate_mixed_on_resume_continue():
    llm = StubLLMClient(responses={"rate the readiness": _low_assessment()})
    node = make_estimate_confidence_node(llm)

    with patch(_INTERRUPT_PATH, return_value="continue"):
        result = await node(_make_state())

    assert result["status"] == "questioning"
    assert len(result["gaps"]) == 2
    assert result["confidence_score"] < 80


async def test_estimate_with_deferred_sections():
    llm = StubLLMClient(responses={"rate the readiness": _low_assessment()})
    node = make_estimate_confidence_node(llm)

    with patch(_INTERRUPT_PATH, return_value="defer technical_constraints,acceptance_criteria"):
        result = await node(_make_state())

    assert "technical_constraints" in result["deferred_sections"]
    assert "acceptance_criteria" in result["deferred_sections"]
    # Recalculated without deferred: high, high, medium, medium = (90+90+60+60)/4 = 75
    assert result["confidence_score"] == 75


async def test_estimate_max_rounds_forces_proceed():
    llm = StubLLMClient(responses={"rate the readiness": _low_assessment()})
    node = make_estimate_confidence_node(llm)

    result = await node(_make_state(round_number=10))

    assert result["status"] == "proposing"


async def test_estimate_override_forces_proceed():
    llm = StubLLMClient(responses={"rate the readiness": _low_assessment()})
    node = make_estimate_confidence_node(llm)

    with patch(_INTERRUPT_PATH, return_value="override"):
        result = await node(_make_state())

    assert result["status"] == "proposing"
