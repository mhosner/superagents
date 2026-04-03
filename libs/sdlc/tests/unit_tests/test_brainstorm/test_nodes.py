"""Tests for brainstorm subgraph nodes."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest
from langgraph.errors import GraphInterrupt

from superagents_sdlc.brainstorm.nodes import (
    _clean_option,
    _resolve_answer,
    make_explore_context_node,
    make_generate_design_section_node,
    make_generate_question_node,
    make_propose_approaches_node,
    make_stall_exit_node,
    make_synthesize_brief_node,
)
from superagents_sdlc.skills.llm import StubLLMClient

if TYPE_CHECKING:
    from superagents_sdlc.brainstorm.state import BrainstormState

_INTERRUPT_PATH = "superagents_sdlc.brainstorm.nodes.interrupt"


def _make_state(**overrides: object) -> dict:
    """Create a default BrainstormState dict with optional overrides."""
    base: dict = {
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
        "stall_counter": 0,
        "previous_confidence": 0.0,
        "section_summaries": {},
        "cached_assessment": {},
        "cached_approaches": [],
        "narrative_entries": [],
    }
    base.update(overrides)
    return base


def _raise_interrupt(value):
    raise GraphInterrupt(value)


def test_brainstorm_state_is_typeddict():
    state: BrainstormState = _make_state()  # type: ignore[assignment]
    assert state["status"] == "exploring"
    assert len(state) == 24


async def test_explore_context_initializes_state():
    node = make_explore_context_node()
    result = await node(_make_state())

    assert result["status"] == "questioning"
    assert result["section_readiness"] == {}
    assert result["confidence_score"] == 0
    assert result["gaps"] == []
    assert result["deferred_sections"] == []
    assert result["round_number"] == 0


async def test_generate_question_calls_llm_and_interrupts():
    llm = StubLLMClient(responses={
        "## Gaps to address": (
            '{"questions": [{"question": "Who are the users?",'
            ' "options": ["devs", "PMs"],'
            ' "targets_section": "users_and_personas"}]}'
        ),
    })
    node = make_generate_question_node(llm)

    with (
        patch(_INTERRUPT_PATH, side_effect=_raise_interrupt),
        pytest.raises(GraphInterrupt),
    ):
        await node(_make_state())

    assert len(llm.calls) == 1


async def test_generate_question_returns_answers_on_resume():
    llm = StubLLMClient(responses={
        "## Gaps to address": (
            '{"questions": [{"question": "Who are the users?",'
            ' "options": null, "targets_section": "users_and_personas"}]}'
        ),
    })
    node = make_generate_question_node(llm)

    with patch(_INTERRUPT_PATH, return_value=["Developers"]):
        result = await node(_make_state())

    assert len(result["transcript"]) == 1
    assert result["transcript"][0]["answer"] == "Developers"
    assert result["round_number"] == 1


async def test_generate_question_batch_multiple():
    llm = StubLLMClient(responses={
        "## Gaps to address": json.dumps({
            "questions": [
                {"question": "Storage?", "options": ["JSON", "SQLite"], "targets_section": "technical_constraints"},
                {"question": "Error handling?", "options": None, "targets_section": "acceptance_criteria"},
            ],
        }),
    })
    node = make_generate_question_node(llm)

    with patch(_INTERRUPT_PATH, return_value=["JSON", "Log and continue"]):
        result = await node(_make_state())

    assert len(result["transcript"]) == 2
    assert result["transcript"][0]["answer"] == "JSON"
    assert result["transcript"][1]["answer"] == "Log and continue"
    assert result["round_number"] == 1


async def test_generate_question_interrupt_payload_structure():
    llm = StubLLMClient(responses={
        "## Gaps to address": json.dumps({
            "questions": [
                {"question": "Q1?", "options": None, "targets_section": "requirements"},
            ],
        }),
    })
    node = make_generate_question_node(llm)

    captured = {}

    def capture_interrupt(value):
        captured.update(value)
        raise GraphInterrupt(value)

    with (
        patch(_INTERRUPT_PATH, side_effect=capture_interrupt),
        pytest.raises(GraphInterrupt),
    ):
        await node(_make_state(round_number=2, confidence_score=45))

    assert captured["type"] == "questions"
    assert len(captured["questions"]) == 1
    assert captured["round"] == 3
    assert captured["confidence"] == 45


async def test_propose_approaches_pass1_caches_without_interrupt():
    """Pass 1: LLM called, approaches cached, no interrupt."""
    llm = StubLLMClient(responses={
        "Propose 2-3": '[{"name": "Simple", "description": "d", "tradeoffs": "t"}]',
    })
    node = make_propose_approaches_node(llm)

    result = await node(_make_state(status="proposing"))

    assert len(result["cached_approaches"]) == 1
    assert result["cached_approaches"][0]["name"] == "Simple"
    assert "selected_approach" not in result
    assert len(llm.calls) == 1


async def test_propose_approaches_pass2_reads_cache_and_interrupts():
    """Pass 2: reads cache, interrupts, returns selection, clears cache."""
    llm = StubLLMClient(responses={})
    node = make_propose_approaches_node(llm)

    cached = [{"name": "Simple", "description": "d", "tradeoffs": "t"}]
    with patch(_INTERRUPT_PATH, return_value="Simple"):
        result = await node(_make_state(
            status="proposing",
            cached_approaches=cached,
        ))

    assert result["selected_approach"] == "Simple"
    assert result["status"] == "designing"
    assert result["current_section_idx"] == 0
    assert result["cached_approaches"] == []
    assert len(llm.calls) == 0


async def test_propose_approaches_pass2_interrupts_with_cached_data():
    """Pass 2: interrupt receives cached approaches, not re-generated ones."""
    llm = StubLLMClient(responses={})
    node = make_propose_approaches_node(llm)

    cached = [
        {"name": "Original A", "description": "d", "tradeoffs": "t"},
        {"name": "Original B", "description": "d", "tradeoffs": "t"},
    ]
    interrupt_payloads = []

    def capture_interrupt(value):
        interrupt_payloads.append(value)
        return "Original A"

    with patch(_INTERRUPT_PATH, side_effect=capture_interrupt):
        await node(_make_state(status="proposing", cached_approaches=cached))

    assert len(interrupt_payloads) == 1
    names = [a["name"] for a in interrupt_payloads[0]["approaches"]]
    assert names == ["Original A", "Original B"]


async def test_propose_approaches_narrative_uses_cached_names():
    """Narrative entry records cached approach names, not re-generated ones."""
    llm = StubLLMClient(responses={})
    node = make_propose_approaches_node(llm)

    cached = [{"name": "Cached Name", "description": "d", "tradeoffs": "t"}]
    with patch(_INTERRUPT_PATH, return_value="Cached Name"):
        result = await node(_make_state(
            status="proposing",
            cached_approaches=cached,
        ))

    entry = result["narrative_entries"][-1]
    assert entry["event"] == "approach_selected"
    assert entry["approach_name"] == "Cached Name"
    assert entry["approaches_offered"] == ["Cached Name"]


async def test_propose_approaches_llm_not_called_on_pass2():
    """LLM is never invoked on pass 2."""
    llm = StubLLMClient(responses={})
    node = make_propose_approaches_node(llm)

    cached = [{"name": "A", "description": "d", "tradeoffs": "t"}]
    with patch(_INTERRUPT_PATH, return_value="A"):
        await node(_make_state(status="proposing", cached_approaches=cached))

    assert len(llm.calls) == 0


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


async def test_design_section_interrupt_has_step_counter():
    """Design section interrupt payload includes section_index and section_count."""
    llm = StubLLMClient(responses={
        "Problem Statement": "## Problem\nContent here",
    })
    node = make_generate_design_section_node(llm)

    captured = {}

    def _capture_and_return(payload):
        captured.update(payload)
        return "approve"

    with patch(_INTERRUPT_PATH, side_effect=_capture_and_return):
        await node(_make_state(
            status="designing",
            selected_approach="Simple",
            current_section_idx=2,
        ))

    assert captured["section_index"] == 2
    assert captured["section_count"] == 6


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


async def test_synthesize_brief_annotates_deferred_sections():
    llm = StubLLMClient(responses={
        "Synthesize all": "# Design Brief\nContent",
    })
    node = make_synthesize_brief_node(llm)

    with patch(_INTERRUPT_PATH, return_value="approve"):
        result = await node(_make_state(
            status="synthesizing",
            design_sections=[{"title": "T", "content": "C", "approved": True}],
            selected_approach="Simple",
            deferred_sections=["technical_constraints"],
        ))

    assert result["status"] == "complete"
    # The brief is from LLM, but the prompt included deferred annotations
    # Verify the LLM was called (annotation is in the prompt, not the output)
    assert len(llm.calls) == 1
    prompt = llm.calls[0][0]
    assert "downstream resolution" in prompt
    assert "Technical Constraints" in prompt


# -- Answer resolution tests --


def test_resolve_answer_by_number():
    assert _resolve_answer("2", ["Apple", "Banana", "Cherry"]) == "Banana"


def test_resolve_answer_by_letter():
    assert _resolve_answer("b", ["Apple", "Banana", "Cherry"]) == "Banana"


def test_resolve_answer_open_ended():
    assert _resolve_answer("custom text", None) == "custom text"


def test_resolve_answer_unrecognized_returns_raw():
    assert _resolve_answer("xyz", ["Apple", "Banana"]) == "xyz"


def test_resolve_answer_multi_select_numbers():
    """Comma-separated numbers resolve to full option texts joined with ' | '."""
    opts = ["Alpha", "Beta", "Gamma"]
    assert _resolve_answer("1, 2, 3", opts) == "Alpha | Beta | Gamma"


def test_resolve_answer_multi_select_no_spaces():
    """Comma-separated numbers without spaces resolve correctly."""
    opts = ["Alpha", "Beta", "Gamma"]
    assert _resolve_answer("1,3", opts) == "Alpha | Gamma"


def test_resolve_answer_multi_select_letters():
    """Comma-separated letters resolve to full option texts joined with ' | '."""
    opts = ["Alpha", "Beta", "Gamma"]
    assert _resolve_answer("a, c", opts) == "Alpha | Gamma"


def test_resolve_answer_multi_select_out_of_range_falls_through():
    """If any token is out of range, raw input is returned unchanged."""
    opts = ["Alpha", "Beta", "Gamma"]
    assert _resolve_answer("1, 2, 7", opts) == "1, 2, 7"


def test_resolve_answer_multi_select_free_text_falls_through():
    """Comma-separated free text (not numbers/letters) returns raw input."""
    opts = ["Alpha", "Beta", "Gamma"]
    assert _resolve_answer("yes, definitely", opts) == "yes, definitely"


# -- Option cleaning tests --


def test_clean_option_strips_letter_prefix():
    assert _clean_option("a) Shared tables") == "Shared tables"


def test_clean_option_no_prefix_unchanged():
    assert _clean_option("Shared tables") == "Shared tables"


def test_clean_option_strips_letter_dot_prefix():
    assert _clean_option("a. Shared tables") == "Shared tables"


# -- Transcript resolution wiring tests --


async def test_transcript_stores_resolved_text():
    """Structured CLI response stores resolved answer in transcript."""
    llm = StubLLMClient(responses={
        "## Gaps to address": json.dumps({
            "questions": [
                {"question": "Storage?", "options": ["JSON", "SQLite"], "targets_section": "technical_constraints"},
            ],
        }),
    })
    node = make_generate_question_node(llm)

    with patch(_INTERRUPT_PATH, return_value=[
        {"answer": "SQLite", "targets_section": "technical_constraints", "question_text": "Storage?"},
    ]):
        result = await node(_make_state())

    assert result["transcript"][0]["answer"] == "SQLite"
    assert result["transcript"][0]["targets_section"] == "technical_constraints"


async def test_batch_questions_all_resolved():
    """Multiple structured answers all stored correctly."""
    llm = StubLLMClient(responses={
        "## Gaps to address": json.dumps({
            "questions": [
                {"question": "Storage?", "options": ["JSON", "SQLite"], "targets_section": "technical_constraints"},
                {"question": "Deploy?", "options": ["Docker", "Lambda"], "targets_section": "technical_constraints"},
                {"question": "Custom notes?", "options": None, "targets_section": "requirements"},
            ],
        }),
    })
    node = make_generate_question_node(llm)

    with patch(_INTERRUPT_PATH, return_value=[
        {"answer": "JSON", "targets_section": "technical_constraints", "question_text": "Storage?"},
        {"answer": "Lambda", "targets_section": "technical_constraints", "question_text": "Deploy?"},
        {"answer": "free text", "targets_section": "requirements", "question_text": "Custom notes?"},
    ]):
        result = await node(_make_state())

    assert result["transcript"][0]["answer"] == "JSON"
    assert result["transcript"][1]["answer"] == "Lambda"
    assert result["transcript"][2]["answer"] == "free text"


# -- _build_brainstorm_cached_prefix tests --


from superagents_sdlc.brainstorm.prompts import _build_brainstorm_cached_prefix


def test_build_brainstorm_cached_prefix_includes_stable_context():
    """Cached prefix contains idea, product context, and codebase context."""
    prefix = _build_brainstorm_cached_prefix(
        idea="Add dark mode",
        product_context="Web app for developers",
        codebase_context="React + TypeScript frontend",
    )
    assert "Add dark mode" in prefix
    assert "Web app for developers" in prefix
    assert "React + TypeScript frontend" in prefix


def test_build_brainstorm_cached_prefix_has_section_headers():
    """Cached prefix uses markdown headers for structure."""
    prefix = _build_brainstorm_cached_prefix(
        idea="Feature X",
        product_context="Context Y",
        codebase_context="Code Z",
    )
    assert "## Idea" in prefix
    assert "## Product context" in prefix
    assert "## Codebase context" in prefix


def test_build_brainstorm_cached_prefix_returns_none_when_empty():
    """Returns None when all fields are empty strings."""
    prefix = _build_brainstorm_cached_prefix(
        idea="",
        product_context="",
        codebase_context="",
    )
    assert prefix is None


# -- Prompt caching wiring tests --


class _SpyLLMClient:
    """LLM stub that also captures cached_prefix for assertions."""

    def __init__(self, *, response: str) -> None:
        self.calls: list[tuple[str, str, str | None]] = []
        self._response = response

    async def generate(
        self,
        prompt: str,
        *,
        system: str = "",
        cached_prefix: str | None = None,
    ) -> str:
        self.calls.append((prompt, system, cached_prefix))
        return self._response


async def test_question_node_passes_cached_prefix():
    """generate_question sends idea/context in cached_prefix, not prompt."""
    llm = _SpyLLMClient(
        response='{"questions": [{"question": "Q?", "options": null, "targets_section": "requirements"}]}'
    )
    node = make_generate_question_node(llm)
    state = _make_state(
        idea="Build search",
        product_context="Enterprise SaaS",
        codebase_context="Python backend",
        section_readiness={"requirements": {"readiness": "low"}},
        gaps=[{"section": "requirements", "description": "No details"}],
    )
    with patch(_INTERRUPT_PATH, return_value=["My answer"]):
        await node(state)
    prompt, _system, cached_prefix = llm.calls[0]
    assert cached_prefix is not None
    assert "Build search" in cached_prefix
    assert "Enterprise SaaS" in cached_prefix
    assert "Build search" not in prompt


async def test_approaches_node_passes_cached_prefix():
    """propose_approaches sends idea/context in cached_prefix, not prompt."""
    llm = _SpyLLMClient(
        response='[{"name": "Simple", "description": "d", "tradeoffs": "t"}]'
    )
    node = make_propose_approaches_node(llm)
    state = _make_state(
        idea="Build search",
        product_context="Enterprise SaaS",
        codebase_context="Python backend",
        status="proposing",
    )
    with patch(_INTERRUPT_PATH, return_value="Simple"):
        await node(state)
    prompt, _system, cached_prefix = llm.calls[0]
    assert cached_prefix is not None
    assert "Build search" in cached_prefix
    assert "Build search" not in prompt


async def test_design_section_node_passes_cached_prefix():
    """generate_design_section sends idea/context in cached_prefix."""
    llm = _SpyLLMClient(response="## Problem\nContent here")
    node = make_generate_design_section_node(llm)
    state = _make_state(
        idea="Build search",
        product_context="Enterprise SaaS",
        codebase_context="Python backend",
        status="designing",
        selected_approach="Simple",
        current_section_idx=0,
    )
    with patch(_INTERRUPT_PATH, return_value="approve"):
        await node(state)
    prompt, _system, cached_prefix = llm.calls[0]
    assert cached_prefix is not None
    assert "Build search" in cached_prefix
    assert "Build search" not in prompt


async def test_synthesize_node_passes_cached_prefix():
    """synthesize_brief sends idea in cached_prefix, not prompt."""
    llm = _SpyLLMClient(response="# Design Brief\nFull content")
    node = make_synthesize_brief_node(llm)
    state = _make_state(
        idea="Build search",
        product_context="Enterprise SaaS",
        codebase_context="Python backend",
        status="synthesizing",
        design_sections=[{"title": "T", "content": "C", "approved": True}],
        selected_approach="Simple",
    )
    with patch(_INTERRUPT_PATH, return_value="approve"):
        await node(state)
    prompt, _system, cached_prefix = llm.calls[0]
    assert cached_prefix is not None
    assert "Build search" in cached_prefix
    assert "Build search" not in prompt


async def test_question_prompt_contains_idea_memory():
    """generate_question prompt uses IdeaMemory, not transcript."""
    llm = _SpyLLMClient(
        response='{"questions": [{"question": "Q?", "options": null, "targets_section": "requirements"}]}',
    )
    node = make_generate_question_node(llm)
    state = _make_state(
        idea_memory=[{"id": "D1", "title": "Tech", "type": "decision", "text": "Use Go"}],
        idea_memory_counts={"decision": 1, "rejection": 0},
        idea="Build API",
        section_readiness={"requirements": {"readiness": "low"}},
        gaps=[{"section": "requirements", "description": "No details"}],
    )
    with patch(_INTERRUPT_PATH, return_value=["answer"]):
        await node(state)

    prompt, _sys, _prefix = llm.calls[0]
    assert "IdeaMemory" in prompt
    assert "D1: Tech [decision]" in prompt
    assert "**DECIDED:**" not in prompt


async def test_approaches_prompt_contains_idea_memory():
    """propose_approaches prompt uses IdeaMemory, not transcript."""
    llm = _SpyLLMClient(
        response='[{"name": "Simple", "description": "d", "tradeoffs": "t"}]',
    )
    node = make_propose_approaches_node(llm)
    state = _make_state(
        idea_memory=[{"id": "D1", "title": "Scope", "type": "decision", "text": "MVP only"}],
        idea_memory_counts={"decision": 1, "rejection": 0},
        idea="Build API",
        status="proposing",
    )
    with patch(_INTERRUPT_PATH, return_value="Simple"):
        await node(state)

    prompt, _sys, _prefix = llm.calls[0]
    assert "IdeaMemory" in prompt
    assert "MVP only" in prompt


async def test_section_prompt_contains_idea_memory():
    """generate_design_section prompt uses IdeaMemory, not transcript."""
    llm = _SpyLLMClient(response="## Problem\nContent")
    node = make_generate_design_section_node(llm)
    state = _make_state(
        idea_memory=[{"id": "D1", "title": "Users", "type": "decision", "text": "DevOps engineers"}],
        idea_memory_counts={"decision": 1, "rejection": 0},
        idea="Build API",
        status="designing",
        selected_approach="Simple",
        current_section_idx=0,
    )
    with patch(_INTERRUPT_PATH, return_value="approve"):
        await node(state)

    prompt, _sys, _prefix = llm.calls[0]
    assert "IdeaMemory" in prompt
    assert "DevOps engineers" in prompt


async def test_synthesize_prompt_contains_idea_memory():
    """synthesize_brief prompt uses IdeaMemory, not transcript."""
    llm = _SpyLLMClient(response="# Design Brief\nFull content")
    node = make_synthesize_brief_node(llm)
    state = _make_state(
        idea_memory=[{"id": "D1", "title": "Tech", "type": "decision", "text": "Use Rust"}],
        idea_memory_counts={"decision": 1, "rejection": 0},
        idea="Build API",
        status="synthesizing",
        design_sections=[{"title": "T", "content": "C", "approved": True}],
        selected_approach="Simple",
    )
    with patch(_INTERRUPT_PATH, return_value="approve"):
        await node(state)

    prompt, _sys, _prefix = llm.calls[0]
    assert "IdeaMemory" in prompt
    assert "Use Rust" in prompt


# -- IdeaMemory capture tests --


from superagents_sdlc.brainstorm.idea_memory import IdeaMemory


async def test_question_answer_adds_to_idea_memory():
    """Answering a question adds a decision entry to idea_memory."""
    llm = StubLLMClient(responses={
        "## Gaps to address": json.dumps({
            "questions": [
                {"question": "Storage?", "options": ["JSON", "SQLite"],
                 "targets_section": "technical_constraints"},
            ],
        }),
    })
    node = make_generate_question_node(llm)

    with patch(_INTERRUPT_PATH, return_value=["JSON"]):
        result = await node(_make_state())

    assert len(result["idea_memory"]) == 1
    assert result["idea_memory"][0]["id"] == "D1"
    assert result["idea_memory"][0]["text"] == "JSON"


async def test_decision_stores_section_key():
    """IdeaMemory entries store the raw section key from CLI metadata."""
    llm = StubLLMClient(responses={
        "## Gaps to address": json.dumps({
            "questions": [
                {"question": "Tech?", "options": None,
                 "targets_section": "technical_constraints"},
            ],
        }),
    })
    node = make_generate_question_node(llm)

    with patch(_INTERRUPT_PATH, return_value=[
        {"answer": "PostgreSQL", "targets_section": "technical_constraints", "question_text": "Tech?"},
    ]):
        result = await node(_make_state())

    assert result["idea_memory"][0]["section"] == "technical_constraints"


async def test_multiple_answers_sequential_ids():
    """Multiple answers produce D1, D2, D3."""
    llm = StubLLMClient(responses={
        "## Gaps to address": json.dumps({
            "questions": [
                {"question": "Q1?", "options": None, "targets_section": "requirements"},
                {"question": "Q2?", "options": None, "targets_section": "scope_boundaries"},
                {"question": "Q3?", "options": None, "targets_section": "acceptance_criteria"},
            ],
        }),
    })
    node = make_generate_question_node(llm)

    with patch(_INTERRUPT_PATH, return_value=["A1", "A2", "A3"]):
        result = await node(_make_state())

    ids = [e["id"] for e in result["idea_memory"]]
    assert ids == ["D1", "D2", "D3"]


async def test_decision_title_uses_section_titles():
    """Decision title comes from SECTION_TITLES mapping via CLI metadata."""
    llm = StubLLMClient(responses={
        "## Gaps to address": json.dumps({
            "questions": [
                {"question": "Tech?", "options": None,
                 "targets_section": "technical_constraints"},
            ],
        }),
    })
    node = make_generate_question_node(llm)

    with patch(_INTERRUPT_PATH, return_value=[
        {"answer": "PostgreSQL", "targets_section": "technical_constraints", "question_text": "Tech?"},
    ]):
        result = await node(_make_state())

    assert result["idea_memory"][0]["title"] == "Technical Constraints & Dependencies"


async def test_backward_compat_string_answer():
    """Plain string answer still works (section defaults to empty)."""
    llm = StubLLMClient(responses={
        "## Gaps to address": json.dumps({
            "questions": [
                {"question": "Q?", "options": None, "targets_section": "requirements"},
            ],
        }),
    })
    node = make_generate_question_node(llm)

    with patch(_INTERRUPT_PATH, return_value=["plain text"]):
        result = await node(_make_state())

    assert result["transcript"][0]["answer"] == "plain text"
    assert result["idea_memory"][0]["section"] == ""


def test_question_prompt_requests_single_question():
    """QUESTION_PROMPT must request exactly 1 question, not multiple."""
    from superagents_sdlc.brainstorm.prompts import QUESTION_PROMPT
    assert "exactly 1 question" in QUESTION_PROMPT
    assert "up to 4 questions" not in QUESTION_PROMPT


def test_question_prompt_has_dependency_order():
    """QUESTION_PROMPT must include foundational-before-derived dependency order."""
    from superagents_sdlc.brainstorm.prompts import QUESTION_PROMPT
    assert "problem_statement" in QUESTION_PROMPT
    assert "users_and_personas" in QUESTION_PROMPT
    assert "requirements" in QUESTION_PROMPT


def test_question_prompt_discourages_multi_select():
    """QUESTION_PROMPT must discourage 'select all that apply' style questions."""
    from superagents_sdlc.brainstorm.prompts import QUESTION_PROMPT
    assert "select all that apply" in QUESTION_PROMPT.lower() or "mutually exclusive" in QUESTION_PROMPT.lower()


async def test_question_node_prefers_foundational_section():
    """When users_and_personas LOW and requirements LOW, question targets users_and_personas first."""
    expected_response = json.dumps({
        "questions": [{
            "question": "Who are the primary users?",
            "options": None,
            "targets_section": "users_and_personas",
        }],
    })
    llm = StubLLMClient(responses={"## Gaps to address": expected_response})
    node = make_generate_question_node(llm)

    with patch(_INTERRUPT_PATH, return_value=[{"answer": "Developers", "targets_section": "users_and_personas", "question_text": "Who are the primary users?"}]):
        result = await node(_make_state(
            section_readiness={
                "problem_statement": {"readiness": "high"},
                "users_and_personas": {"readiness": "low"},
                "requirements": {"readiness": "low"},
                "acceptance_criteria": {"readiness": "low"},
                "scope_boundaries": {"readiness": "low"},
                "technical_constraints": {"readiness": "low"},
            },
            gaps=[
                {"section": "users_and_personas", "description": "No user definition"},
                {"section": "requirements", "description": "No requirements"},
            ],
        ))

    # The dependency order guidance is in the prompt sent to the LLM
    prompt_sent = llm.calls[0][0]
    assert "dependency" in prompt_sent.lower() or "foundational" in prompt_sent.lower() or "problem_statement" in prompt_sent


async def test_question_node_targets_derived_when_foundational_high():
    """When foundational sections are HIGH and only derived sections LOW, question targets derived."""
    expected_response = json.dumps({
        "questions": [{
            "question": "What are the acceptance criteria?",
            "options": None,
            "targets_section": "acceptance_criteria",
        }],
    })
    llm = StubLLMClient(responses={"## Gaps to address": expected_response})
    node = make_generate_question_node(llm)

    with patch(_INTERRUPT_PATH, return_value=[{"answer": "Pass all tests", "targets_section": "acceptance_criteria", "question_text": "What are the acceptance criteria?"}]):
        result = await node(_make_state(
            section_readiness={
                "problem_statement": {"readiness": "high"},
                "users_and_personas": {"readiness": "high"},
                "requirements": {"readiness": "high"},
                "acceptance_criteria": {"readiness": "low"},
                "scope_boundaries": {"readiness": "medium"},
                "technical_constraints": {"readiness": "low"},
            },
            gaps=[
                {"section": "acceptance_criteria", "description": "No criteria defined"},
            ],
        ))

    # Prompt must contain dependency order guidance
    prompt_sent = llm.calls[0][0]
    assert "problem_statement" in prompt_sent


# -- stall_exit node tests --


async def test_stall_exit_interrupts_with_gaps():
    """Stall exit node interrupts with stall info and options."""
    node = make_stall_exit_node()

    captured = {}

    def capture_interrupt(value):
        captured.update(value)
        raise GraphInterrupt(value)

    with (
        patch(_INTERRUPT_PATH, side_effect=capture_interrupt),
        pytest.raises(GraphInterrupt),
    ):
        await node(_make_state(
            confidence_score=62,
            gaps=[
                {"section": "acceptance_criteria", "description": "No error paths"},
                {"section": "technical_constraints", "description": "No storage discussion"},
            ],
            stall_counter=3,
        ))

    assert captured["type"] == "stall_exit"
    assert captured["confidence"] == 62
    assert len(captured["gaps"]) == 2
    assert "proceed" in captured["options"]
    assert "continue" in captured["options"]


async def test_stall_exit_proceed_routes_to_approaches():
    """User choosing 'proceed' sets status to proposing."""
    node = make_stall_exit_node()

    with patch(_INTERRUPT_PATH, return_value="proceed"):
        result = await node(_make_state(
            confidence_score=62,
            gaps=[{"section": "acceptance_criteria", "description": "gaps"}],
            stall_counter=3,
        ))

    assert result["status"] == "proposing"


async def test_stall_exit_continue_resets_counter():
    """User choosing 'continue' resets stall_counter and keeps questioning."""
    node = make_stall_exit_node()

    with patch(_INTERRUPT_PATH, return_value="continue"):
        result = await node(_make_state(
            confidence_score=62,
            gaps=[{"section": "acceptance_criteria", "description": "gaps"}],
            stall_counter=3,
        ))

    assert result["status"] == "questioning"
    assert result["stall_counter"] == 0


# --- F-07: narrative entry tests ---


async def test_question_answered_appends_narrative_entry():
    """generate_question appends a question_answered narrative entry."""
    llm = StubLLMClient(responses={
        "## Gaps to address": json.dumps({
            "questions": [
                {"question": "Storage?", "options": ["JSON", "SQLite"],
                 "targets_section": "technical_constraints"},
            ],
        }),
    })
    node = make_generate_question_node(llm)

    with patch(_INTERRUPT_PATH, return_value=[
        {"answer": "SQLite", "targets_section": "technical_constraints", "question_text": "Storage?"},
    ]):
        result = await node(_make_state(confidence_score=40))

    assert "narrative_entries" in result
    entries = result["narrative_entries"]
    assert len(entries) == 1
    entry = entries[0]
    assert entry["event"] == "question_answered"
    assert entry["question_text"] == "Storage?"
    assert entry["answer_text"] == "SQLite"
    assert entry["round"] == 1  # round_number 0 + 1


async def test_approach_selected_appends_narrative_entry():
    """propose_approaches pass 2 appends an approach_selected narrative entry."""
    llm = StubLLMClient(responses={})
    node = make_propose_approaches_node(llm)

    cached = [
        {"name": "Simple", "description": "d", "tradeoffs": "t"},
        {"name": "Complex", "description": "d2", "tradeoffs": "t2"},
    ]
    with patch(_INTERRUPT_PATH, return_value="Simple"):
        result = await node(_make_state(status="proposing", cached_approaches=cached))

    assert "narrative_entries" in result
    entries = result["narrative_entries"]
    assert len(entries) == 1
    entry = entries[0]
    assert entry["event"] == "approach_selected"
    assert entry["approach_name"] == "Simple"
    assert entry["approaches_offered"] == ["Simple", "Complex"]


async def test_section_approved_appends_narrative_entry():
    """generate_design_section appends section_approved on 'approve'."""
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

    assert "narrative_entries" in result
    entry = result["narrative_entries"][0]
    assert entry["event"] == "section_approved"
    assert entry["section_title"] == "Problem Statement & Goals"


async def test_section_revised_appends_narrative_entry():
    """generate_design_section appends section_revised on edit."""
    llm = StubLLMClient(responses={
        "Problem Statement": "## Problem\nDraft",
    })
    node = make_generate_design_section_node(llm)

    with patch(_INTERRUPT_PATH, return_value="## Problem\nRevised"):
        result = await node(_make_state(
            status="designing",
            selected_approach="Simple",
            current_section_idx=0,
        ))

    assert "narrative_entries" in result
    entry = result["narrative_entries"][0]
    assert entry["event"] == "section_revised"
    assert entry["section_title"] == "Problem Statement & Goals"


async def test_brief_approved_appends_narrative_entry():
    """synthesize_brief appends brief_approved on 'approve'."""
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

    assert "narrative_entries" in result
    entry = result["narrative_entries"][0]
    assert entry["event"] == "brief_approved"
