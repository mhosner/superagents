"""Tests for confidence computation and estimate_confidence node."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from langgraph.errors import GraphInterrupt

from superagents_sdlc.brainstorm.confidence import (
    READINESS_SCORES,
    SECTIONS,
    _format_transcript_for_assessment,
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
    llm = StubLLMClient(responses={"Readiness ratings": _high_assessment()})
    node = make_estimate_confidence_node(llm)
    result = await node(_make_state())

    assert result["confidence_score"] == 90
    assert result["status"] == "proposing"
    assert result["gaps"] == []


async def test_estimate_mixed_scores_below_threshold():
    llm = StubLLMClient(responses={"Readiness ratings": _low_assessment()})
    node = make_estimate_confidence_node(llm)

    def _raise_interrupt(value):
        raise GraphInterrupt(value)

    with (
        patch(_INTERRUPT_PATH, side_effect=_raise_interrupt),
        pytest.raises(GraphInterrupt),
    ):
        await node(_make_state())


async def test_estimate_mixed_on_resume_continue():
    llm = StubLLMClient(responses={"Readiness ratings": _low_assessment()})
    node = make_estimate_confidence_node(llm)

    with patch(_INTERRUPT_PATH, return_value="continue"):
        result = await node(_make_state())

    assert result["status"] == "questioning"
    assert len(result["gaps"]) == 2
    assert result["confidence_score"] < 80


async def test_estimate_with_deferred_sections():
    llm = StubLLMClient(responses={"Readiness ratings": _low_assessment()})
    node = make_estimate_confidence_node(llm)

    with patch(_INTERRUPT_PATH, return_value="defer technical_constraints,acceptance_criteria"):
        result = await node(_make_state())

    assert "technical_constraints" in result["deferred_sections"]
    assert "acceptance_criteria" in result["deferred_sections"]
    # Recalculated without deferred: high, high, medium, medium = (90+90+60+60)/4 = 75
    assert result["confidence_score"] == 75


async def test_estimate_max_rounds_forces_proceed():
    llm = StubLLMClient(responses={"Readiness ratings": _low_assessment()})
    node = make_estimate_confidence_node(llm)

    result = await node(_make_state(round_number=10))

    assert result["status"] == "proposing"


async def test_estimate_override_forces_proceed():
    llm = StubLLMClient(responses={"Readiness ratings": _low_assessment()})
    node = make_estimate_confidence_node(llm)

    with patch(_INTERRUPT_PATH, return_value="override"):
        result = await node(_make_state())

    assert result["status"] == "proposing"


# -- _format_transcript_for_assessment tests --


def test_format_transcript_empty():
    """Empty transcript returns a placeholder message."""
    result = _format_transcript_for_assessment([])
    assert result == "No questions have been asked yet."


def test_format_transcript_single_entry():
    """Single Q&A formats as Decision 1 with DECIDED label."""
    transcript = [
        {
            "question": "Who is the target user?",
            "answer": "Mobile developers",
            "options": None,
            "targets_section": "users_and_personas",
        }
    ]
    result = _format_transcript_for_assessment(transcript)
    assert "### Decision 1" in result
    assert "**Question:** Who is the target user?" in result
    assert "**DECIDED:** Mobile developers" in result


def test_format_transcript_excludes_options():
    """Options list must not appear in formatted output."""
    transcript = [
        {
            "question": "Which database?",
            "answer": "PostgreSQL",
            "options": ["MySQL", "PostgreSQL", "SQLite"],
            "targets_section": "technical_constraints",
        }
    ]
    result = _format_transcript_for_assessment(transcript)
    assert "PostgreSQL" in result
    assert "MySQL" not in result
    assert "SQLite" not in result
    assert "Option" not in result


def test_format_transcript_multiple_entries():
    """Three Q&As numbered Decision 1/2/3 with correct answers."""
    transcript = [
        {
            "question": "What problem?",
            "answer": "Slow deployments",
            "options": ["Slow deployments", "Bad UX"],
            "targets_section": "problem_statement",
        },
        {
            "question": "Who uses it?",
            "answer": "DevOps engineers",
            "options": None,
            "targets_section": "users_and_personas",
        },
        {
            "question": "What stack?",
            "answer": "Python + Docker",
            "options": ["Python + Docker", "Go + K8s"],
            "targets_section": "technical_constraints",
        },
    ]
    result = _format_transcript_for_assessment(transcript)
    assert "### Decision 1" in result
    assert "### Decision 2" in result
    assert "### Decision 3" in result
    assert "**DECIDED:** Slow deployments" in result
    assert "**DECIDED:** DevOps engineers" in result
    assert "**DECIDED:** Python + Docker" in result
    # Excluded options should not appear
    assert "Bad UX" not in result
    assert "Go + K8s" not in result


# -- Wiring tests: formatted transcript in confidence prompt --


async def test_confidence_prompt_contains_decisions_framing():
    """Assessment prompt must frame transcript as settled decisions."""
    llm = StubLLMClient(responses={"Readiness ratings": _high_assessment()})
    node = make_estimate_confidence_node(llm)
    await node(_make_state())

    prompt = llm.calls[0][0]
    assert "Decisions Made So Far" in prompt
    assert "FINAL" in prompt


async def test_confidence_prompt_uses_formatted_transcript():
    """Assessment prompt uses formatted transcript, not raw JSON."""
    transcript = [
        {
            "question": "Trigger method?",
            "answer": "Automatic sub-step",
            "options": ["Automatic sub-step", "/sfn-analyze slash command"],
            "targets_section": "scope_boundaries",
        }
    ]
    llm = StubLLMClient(responses={"Readiness ratings": _high_assessment()})
    node = make_estimate_confidence_node(llm)
    await node(_make_state(transcript=transcript))

    prompt = llm.calls[0][0]
    assert "**DECIDED:** Automatic sub-step" in prompt
    assert "/sfn-analyze slash command" not in prompt
    # No raw JSON transcript data before the decisions block
    before_decisions = prompt.lower().split("## decisions made so far")[0]
    assert "json" not in before_decisions


async def test_confidence_node_passes_cached_prefix():
    """The confidence node passes cached_prefix containing idea and context."""
    llm = StubLLMClient(responses={"Readiness ratings": _high_assessment()})
    node = make_estimate_confidence_node(llm)
    state = _make_state(
        idea="Build search feature",
        product_context="Enterprise SaaS",
        codebase_context="Python FastAPI backend",
    )
    await node(state)

    # StubLLMClient tracks calls as (prompt, system).
    # Since StubLLMClient ignores cached_prefix, we verify the prompt
    # does NOT contain the stable context (it's in cached_prefix instead).
    prompt = llm.calls[0][0]
    assert "Build search feature" not in prompt
    assert "Enterprise SaaS" not in prompt
    assert "Python FastAPI backend" not in prompt


async def test_confidence_node_cached_prefix_excludes_transcript():
    """The transcript must be in the variable prompt, not cached_prefix."""
    llm = StubLLMClient(responses={"Readiness ratings": _high_assessment()})
    node = make_estimate_confidence_node(llm)
    state = _make_state(
        transcript=[{"question": "Who?", "answer": "Devs", "options": None, "targets_section": ""}],
    )
    await node(state)

    prompt = llm.calls[0][0]
    assert "**DECIDED:** Devs" in prompt


async def test_confidence_prompt_requires_echo_step():
    """Prompt must instruct LLM to echo decisions before JSON."""
    llm = StubLLMClient(responses={"Readiness ratings": _high_assessment()})
    node = make_estimate_confidence_node(llm)
    await node(_make_state())

    prompt = llm.calls[0][0]
    assert "Write out each decision verbatim" in prompt
    assert "before your JSON" in prompt


async def test_confidence_prompt_contains_critical_rules():
    """Prompt must contain all three Do NOT rules."""
    llm = StubLLMClient(responses={"Readiness ratings": _high_assessment()})
    node = make_estimate_confidence_node(llm)
    await node(_make_state())

    prompt = llm.calls[0][0]
    assert "Do NOT infer" in prompt
    assert "Do NOT extend" in prompt
    assert "Do NOT combine" in prompt


async def test_confidence_prompt_evidence_quote_only():
    """Evidence field must be constrained to quote-only."""
    llm = StubLLMClient(responses={"Readiness ratings": _high_assessment()})
    node = make_estimate_confidence_node(llm)
    await node(_make_state())

    prompt = llm.calls[0][0]
    assert "quote ONLY from the Decisions Made" in prompt
