"""Tests for confidence computation and estimate_confidence node."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from langgraph.errors import GraphInterrupt

from superagents_sdlc.brainstorm.confidence import (
    READINESS_SCORES,
    SECTIONS,
    _ASSESSMENT_PROMPT,
    _build_section_summaries,
    compute_confidence,
    make_estimate_confidence_node,
)
from superagents_sdlc.skills.llm import StubLLMClient

_INTERRUPT_PATH = "superagents_sdlc.brainstorm.confidence.interrupt"


# -- compute_confidence tests --


def test_assessment_prompt_no_evidence_field():
    """Assessment prompt schema must not ask for 'evidence' field."""
    assert '"evidence"' not in _ASSESSMENT_PROMPT


def test_compute_all_high():
    sections = {s: {"readiness": "high"} for s in SECTIONS}
    assert compute_confidence(sections, []) == 90


def test_compute_all_low():
    sections = {s: {"readiness": "low"} for s in SECTIONS}
    assert compute_confidence(sections, []) == 30


def test_compute_mixed():
    """3 high (90*3=270) + 3 low (30*3=90) = 360 / 6 = 60."""
    sections = {}
    for i, s in enumerate(SECTIONS):
        sections[s] = {"readiness": "high" if i < 3 else "low"}
    assert compute_confidence(sections, []) == 60


def test_compute_with_deferred():
    """Deferred sections excluded. 2 high out of 4 active, 2 deferred."""
    sections = {s: {"readiness": "high"} for s in SECTIONS}
    sections["technical_constraints"]["readiness"] = "low"
    sections["scope_boundaries"]["readiness"] = "low"
    deferred = ["technical_constraints", "scope_boundaries"]
    # 4 active sections all high: 90
    assert compute_confidence(sections, deferred) == 90


def test_compute_all_deferred():
    """All sections deferred returns 100."""
    sections = {s: {"readiness": "low"} for s in SECTIONS}
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
        "idea_memory": [],
        "idea_memory_counts": {"decision": 0, "rejection": 0},
        "stall_counter": 0,
        "previous_confidence": 0.0,
        "section_summaries": {},
        "cached_assessment": {},
        "cached_approaches": [],
        "narrative_entries": [],
    }
    base.update(overrides)
    return base


def _high_assessment():
    return json.dumps({
        "sections": {s: {"readiness": "high"} for s in SECTIONS},
        "gaps": [],
    })


def _low_assessment():
    return json.dumps({
        "sections": {
            "problem_statement": {"readiness": "high"},
            "users_and_personas": {"readiness": "high"},
            "requirements": {"readiness": "medium"},
            "acceptance_criteria": {"readiness": "low"},
            "scope_boundaries": {"readiness": "medium"},
            "technical_constraints": {"readiness": "low"},
        },
        "gaps": [
            {"section": "acceptance_criteria", "description": "No error paths"},
            {"section": "technical_constraints", "description": "No storage discussion"},
        ],
    })


async def test_estimate_all_high_scores_above_threshold():
    llm = StubLLMClient(responses={"Readiness ratings": _high_assessment()})
    node = make_estimate_confidence_node(llm)
    result = await node(_make_state())

    assert result["confidence_score"] == 90
    assert result["status"] == "proposing"
    assert result["gaps"] == []
    assert "section_summaries" in result


async def test_estimate_mixed_below_threshold_caches():
    """Below-threshold assessment returns awaiting_input with cached data."""
    llm = StubLLMClient(responses={"Readiness ratings": _low_assessment()})
    node = make_estimate_confidence_node(llm)

    # Pass 1: LLM called, result cached, no interrupt
    result = await node(_make_state())

    assert result["status"] == "awaiting_input"
    assert result["cached_assessment"] != {}
    assert result["cached_assessment"]["confidence_score"] == 60
    assert len(llm.calls) == 1


async def test_estimate_cached_skips_llm():
    """When cached_assessment is populated, LLM is not called."""
    llm = StubLLMClient(responses={"Readiness ratings": _low_assessment()})
    node = make_estimate_confidence_node(llm)

    cached = {
        "section_readiness": {s: {"readiness": "low"} for s in SECTIONS},
        "confidence_score": 30,
        "gaps": [{"section": "requirements", "description": "missing"}],
        "section_summaries": {"requirements": "No decision made yet."},
        "stall_counter": 0,
    }

    with patch(_INTERRUPT_PATH, return_value="continue"):
        result = await node(_make_state(cached_assessment=cached))

    assert len(llm.calls) == 0  # LLM not called
    assert result["status"] == "questioning"
    assert result["cached_assessment"] == {}  # cache cleared


async def test_estimate_resume_continue():
    """Resume with 'continue' from cached assessment."""
    llm = StubLLMClient(responses={"Readiness ratings": _low_assessment()})
    node = make_estimate_confidence_node(llm)

    # Pass 1: cache
    pass1 = await node(_make_state())
    # Pass 2: resume with cached state
    with patch(_INTERRUPT_PATH, return_value="continue"):
        result = await node(_make_state(**pass1))

    assert result["status"] == "questioning"
    assert len(result["gaps"]) == 2
    assert result["confidence_score"] < 80
    assert result["cached_assessment"] == {}


async def test_estimate_with_deferred_sections():
    """Defer sections from cached assessment."""
    llm = StubLLMClient(responses={"Readiness ratings": _low_assessment()})
    node = make_estimate_confidence_node(llm)

    # Pass 1: cache
    pass1 = await node(_make_state())
    # Pass 2: defer
    with patch(_INTERRUPT_PATH, return_value="defer technical_constraints,acceptance_criteria"):
        result = await node(_make_state(**pass1))

    assert "technical_constraints" in result["deferred_sections"]
    assert "acceptance_criteria" in result["deferred_sections"]
    # Recalculated without deferred: high, high, medium, medium = (90+90+60+60)/4 = 75
    assert result["confidence_score"] == 75


async def test_stall_counter_resets_on_significant_gain():
    """Confidence gain >= 2 returns awaiting_input with reset counter."""
    llm = StubLLMClient(responses={"Readiness ratings": _low_assessment()})
    node = make_estimate_confidence_node(llm)

    # Score 60, prev 50 → delta 10 → reset counter → awaiting_input
    result = await node(_make_state(
        previous_confidence=50.0,
        stall_counter=2,
    ))

    assert result["stall_counter"] == 0
    assert result["previous_confidence"] == float(result["confidence_score"])
    assert result["status"] == "awaiting_input"


async def test_stall_counter_resets_on_confidence_drop():
    """Confidence drop resets stall_counter."""
    llm = StubLLMClient(responses={"Readiness ratings": _low_assessment()})
    node = make_estimate_confidence_node(llm)

    # Score = 60, prev 70 → delta -10 → reset counter
    result = await node(_make_state(
        previous_confidence=70.0,
        stall_counter=2,
    ))

    assert result["stall_counter"] == 0
    assert result["status"] == "awaiting_input"


async def test_stall_counter_increments_on_flat_confidence():
    """Confidence change < 2 increments stall_counter."""
    llm = StubLLMClient(responses={"Readiness ratings": _low_assessment()})
    node = make_estimate_confidence_node(llm)

    # Score = 60, prev 60 → delta 0 → increment
    result = await node(_make_state(
        previous_confidence=60.0,
        stall_counter=0,
    ))

    assert result["stall_counter"] == 1
    assert result["status"] == "awaiting_input"


async def test_stall_counter_triggers_stall_exit_at_three():
    """When stall_counter reaches 3, status becomes 'stalled'."""
    llm = StubLLMClient(responses={"Readiness ratings": _low_assessment()})
    node = make_estimate_confidence_node(llm)

    # No interrupt patch needed — stall exit skips the confidence interrupt
    result = await node(_make_state(
        previous_confidence=60.0,
        stall_counter=2,
    ))

    # Score = 60, delta = 0, stall_counter was 2 → becomes 3 → stalled
    assert result["stall_counter"] == 3
    assert result["status"] == "stalled"


async def test_stall_check_uses_first_round_correctly():
    """First round (previous_confidence=0.0) with any score >= 2 resets counter."""
    llm = StubLLMClient(responses={"Readiness ratings": _low_assessment()})
    node = make_estimate_confidence_node(llm)

    result = await node(_make_state(
        previous_confidence=0.0,
        stall_counter=0,
    ))

    # Score = 60, delta = 60 - 0 = 60, >= 2 → reset
    assert result["stall_counter"] == 0
    assert result["status"] == "awaiting_input"


async def test_safety_cap_forces_proceed():
    """Absolute safety cap (50 rounds) forces proceed."""
    llm = StubLLMClient(responses={"Readiness ratings": _low_assessment()})
    node = make_estimate_confidence_node(llm)

    result = await node(_make_state(round_number=50))

    assert result["status"] == "proposing"


async def test_estimate_override_forces_proceed():
    llm = StubLLMClient(responses={"Readiness ratings": _low_assessment()})
    node = make_estimate_confidence_node(llm)

    # Pass 1: cache
    pass1 = await node(_make_state())
    # Pass 2: override from cache
    with patch(_INTERRUPT_PATH, return_value="override"):
        result = await node(_make_state(**pass1))

    assert result["status"] == "proposing"


# -- IdeaMemory in confidence prompt --


async def test_confidence_prompt_contains_idea_memory():
    """Prompt must contain IdeaMemory text, not formatted transcript."""
    llm = StubLLMClient(responses={"Readiness ratings": _high_assessment()})
    node = make_estimate_confidence_node(llm)
    state = _make_state(
        idea_memory=[
            {"id": "D1", "title": "Storage", "type": "decision", "text": "Use PostgreSQL"},
        ],
        idea_memory_counts={"decision": 1, "rejection": 0},
        idea="Build search feature",
    )
    await node(state)

    prompt = llm.calls[0][0]
    assert "IdeaMemory" in prompt
    assert "Use PostgreSQL" in prompt
    assert "D1: Storage [decision]" in prompt
    # Transcript formatter output should NOT be in prompt
    assert "**DECIDED:**" not in prompt


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


async def test_low_confidence_no_stall_keeps_awaiting():
    """B-08 verify: confidence < threshold + no stall = awaiting_input (then questioning)."""
    llm = StubLLMClient(responses={"Readiness ratings": _low_assessment()})
    node = make_estimate_confidence_node(llm)

    # Pass 1: below threshold, no stall → caches
    result = await node(_make_state(
        previous_confidence=30.0,
        stall_counter=0,
    ))

    # Score 60 > prev 30 → delta 30 → reset counter → awaiting_input
    assert result["confidence_score"] < 80
    assert result["status"] == "awaiting_input"
    assert result["stall_counter"] == 0


# -- Anti-fabrication prompt constraints --


# -- _build_section_summaries tests --


def test_build_section_summaries_from_entries():
    """Summaries assembled from IdeaMemory entries matching section keys."""
    readiness = {
        "technical_constraints": {"readiness": "high"},
        "requirements": {"readiness": "low"},
    }
    entries = [
        {"id": "D1", "title": "Tech", "type": "decision",
         "text": "Use PostgreSQL", "section": "technical_constraints"},
    ]
    result = _build_section_summaries(readiness, entries)
    assert result["technical_constraints"] == "Use PostgreSQL"
    assert result["requirements"] == "No decision made yet."


def test_build_section_summaries_multiple_entries():
    """Multiple entries for one section joined with ' | '."""
    readiness = {"technical_constraints": {"readiness": "high"}}
    entries = [
        {"id": "D1", "title": "Tech", "type": "decision",
         "text": "Use PostgreSQL", "section": "technical_constraints"},
        {"id": "D2", "title": "Tech", "type": "decision",
         "text": "Deploy on AWS", "section": "technical_constraints"},
    ]
    result = _build_section_summaries(readiness, entries)
    assert result["technical_constraints"] == "Use PostgreSQL | Deploy on AWS"


def test_build_section_summaries_no_entries():
    """Section with no matching entries returns placeholder."""
    readiness = {"scope_boundaries": {"readiness": "low"}}
    result = _build_section_summaries(readiness, [])
    assert result["scope_boundaries"] == "No decision made yet."


# --- F-07: narrative entry tests ---


async def test_cached_assessment_includes_delta_and_readiness_changes():
    """Pass 1 caches confidence_delta and readiness_changes for narrative."""
    llm = StubLLMClient(responses={"Readiness ratings": _low_assessment()})
    node = make_estimate_confidence_node(llm)

    # previous_confidence=30, score will be 60 → delta=30
    # previous section_readiness has problem_statement as low,
    # new assessment has it as high → readiness change
    result = await node(_make_state(
        previous_confidence=30.0,
        section_readiness={
            "problem_statement": {"readiness": "low"},
            "users_and_personas": {"readiness": "low"},
        },
    ))

    assert result["status"] == "awaiting_input"
    cached = result["cached_assessment"]
    assert "confidence_delta" in cached
    assert cached["confidence_delta"] == 30  # 60 - 30
    assert "readiness_changes" in cached
    # problem_statement went from low → high in _low_assessment
    assert cached["readiness_changes"]["problem_statement"] == {"from": "low", "to": "high"}


async def test_narrative_entry_appended_on_continue():
    """Pass 2 with 'continue' appends an assessment narrative entry."""
    llm = StubLLMClient(responses={"Readiness ratings": _low_assessment()})
    node = make_estimate_confidence_node(llm)

    # Pass 1: cache (with known previous_confidence for delta)
    pass1 = await node(_make_state(previous_confidence=30.0))

    # Pass 2: resume
    with patch(_INTERRUPT_PATH, return_value="continue"):
        result = await node(_make_state(**pass1))

    assert "narrative_entries" in result
    assert len(result["narrative_entries"]) == 1
    entry = result["narrative_entries"][0]
    assert entry["event"] == "assessment"
    assert entry["confidence"] == 60
    assert entry["confidence_delta"] == 30
    assert "section_readiness" in entry
    assert "gap_count" in entry


async def test_narrative_entry_appended_on_auto_continue():
    """Pass 2 with 'auto_continue' appends an auto_continue entry."""
    llm = StubLLMClient(responses={"Readiness ratings": _low_assessment()})
    node = make_estimate_confidence_node(llm)

    pass1 = await node(_make_state(previous_confidence=30.0))

    with patch(_INTERRUPT_PATH, return_value="auto_continue"):
        result = await node(_make_state(**pass1))

    assert len(result["narrative_entries"]) == 1
    entry = result["narrative_entries"][0]
    assert entry["event"] == "auto_continue"
    assert entry["confidence"] == 60
    assert "gap_count" in entry


async def test_auto_proceed_appends_assessment_entry():
    """Confidence >= threshold (auto-proceed) appends assessment entry."""
    llm = StubLLMClient(responses={"Readiness ratings": _high_assessment()})
    node = make_estimate_confidence_node(llm)

    result = await node(_make_state(previous_confidence=50.0))

    assert result["status"] == "proposing"
    assert "narrative_entries" in result
    assert len(result["narrative_entries"]) == 1
    entry = result["narrative_entries"][0]
    assert entry["event"] == "assessment"
    assert entry["confidence"] == 90
    assert entry["confidence_delta"] == 40  # 90 - 50
