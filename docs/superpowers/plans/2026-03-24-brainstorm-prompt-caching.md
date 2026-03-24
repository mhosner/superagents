# Brainstorm Prompt Caching Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add prompt caching to all brainstorm LLM calls so the stable context (idea, product context, codebase context) is cached across the 12+ Sonnet calls in a session, reducing input token cost by ~85%.

**Architecture:** Split each brainstorm prompt into a stable `cached_prefix` (idea + product/codebase context) and a variable `prompt` (transcript + node-specific instructions). Pass `cached_prefix` to `llm.generate()` which already supports it via `AnthropicLLMClient`. A shared helper `_build_brainstorm_cached_prefix()` builds the prefix from state; each node constructs only its variable prompt.

**Tech Stack:** Python, LangGraph, Anthropic API (existing `cached_prefix` support in `LLMClient`)

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `libs/sdlc/src/superagents_sdlc/brainstorm/prompts.py` | Modify | Split prompt templates: remove stable context placeholders (`{idea}`, `{product_context}`, `{codebase_context}`), keep only variable parts. Add `_build_brainstorm_cached_prefix()` helper. |
| `libs/sdlc/src/superagents_sdlc/brainstorm/confidence.py` | Modify | Update `_ASSESSMENT_PROMPT` to remove stable context. Pass `cached_prefix` to `llm.generate()`. |
| `libs/sdlc/src/superagents_sdlc/brainstorm/nodes.py` | Modify | Update 4 node factories to use `_build_brainstorm_cached_prefix()` and pass it to `llm.generate()`. |
| `tests/unit_tests/test_brainstorm/test_confidence.py` | Modify | Add caching tests for confidence node. |
| `tests/unit_tests/test_brainstorm/test_nodes.py` | Modify | Add caching tests for question, approaches, design section, and synthesize nodes. |

All paths below are relative to `libs/sdlc/`.

---

### Task 1: Add `_build_brainstorm_cached_prefix` helper + tests

**Files:**
- Modify: `src/superagents_sdlc/brainstorm/prompts.py`
- Test: `tests/unit_tests/test_brainstorm/test_nodes.py`

The helper builds the stable context string from brainstorm state fields. It lives in `prompts.py` alongside the other prompt infrastructure.

- [ ] **Step 1: Write the failing tests**

Add to `tests/unit_tests/test_brainstorm/test_nodes.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd libs/sdlc && uv run --group test pytest tests/unit_tests/test_brainstorm/test_nodes.py::test_build_brainstorm_cached_prefix_includes_stable_context tests/unit_tests/test_brainstorm/test_nodes.py::test_build_brainstorm_cached_prefix_has_section_headers tests/unit_tests/test_brainstorm/test_nodes.py::test_build_brainstorm_cached_prefix_returns_none_when_empty -v`
Expected: ImportError — `_build_brainstorm_cached_prefix` does not exist yet.

- [ ] **Step 3: Write minimal implementation**

Add to `src/superagents_sdlc/brainstorm/prompts.py` (after the `BRAINSTORM_SYSTEM` constant):

```python
def _build_brainstorm_cached_prefix(
    *,
    idea: str,
    product_context: str,
    codebase_context: str,
) -> str | None:
    """Build the stable cached prefix for brainstorm LLM calls.

    Assembles the context that does not change between calls in a
    brainstorm session: the idea, product context, and codebase context.

    Args:
        idea: The feature idea being brainstormed.
        product_context: Product context from context files.
        codebase_context: Codebase context from file analysis.

    Returns:
        Formatted prefix string, or None if all fields are empty.
    """
    parts = []
    for header, value in [
        ("Idea", idea),
        ("Product context", product_context),
        ("Codebase context", codebase_context),
    ]:
        if value:
            parts.append(f"## {header}\n{value}")
    return "\n\n".join(parts) if parts else None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd libs/sdlc && uv run --group test pytest tests/unit_tests/test_brainstorm/test_nodes.py -k "build_brainstorm_cached_prefix" -v`
Expected: 3 PASSED

- [ ] **Step 5: Commit**

```bash
git add src/superagents_sdlc/brainstorm/prompts.py tests/unit_tests/test_brainstorm/test_nodes.py
git commit -m "feat(sdlc): add _build_brainstorm_cached_prefix helper"
```

---

### Task 2: Split confidence assessment prompt and wire caching + tests

**Files:**
- Modify: `src/superagents_sdlc/brainstorm/confidence.py`
- Test: `tests/unit_tests/test_brainstorm/test_confidence.py`

Remove the stable context (`{idea}`, `{product_context}`, `{codebase_context}`) from `_ASSESSMENT_PROMPT`. Those now go in `cached_prefix`. The prompt template keeps only the variable parts: transcript, assessment instructions, and deferred note.

- [ ] **Step 1: Write the failing tests**

Add to `tests/unit_tests/test_brainstorm/test_confidence.py`:

```python
async def test_confidence_node_passes_cached_prefix():
    """The confidence node passes cached_prefix containing idea and context."""
    llm = StubLLMClient(responses={"rate the readiness": _high_assessment()})
    node = make_estimate_confidence_node(llm)
    state = _make_state(
        idea="Build search feature",
        product_context="Enterprise SaaS",
        codebase_context="Python FastAPI backend",
    )
    await node(state)

    # StubLLMClient tracks calls as (prompt, system).
    # We need to check that cached_prefix was passed.
    # Since StubLLMClient ignores cached_prefix, we verify the prompt
    # does NOT contain the stable context (it's in cached_prefix instead).
    prompt = llm.calls[0][0]
    assert "Build search feature" not in prompt
    assert "Enterprise SaaS" not in prompt
    assert "Python FastAPI backend" not in prompt


async def test_confidence_node_cached_prefix_excludes_transcript():
    """The transcript must be in the variable prompt, not cached_prefix."""
    # We verify this indirectly: the prompt DOES contain the transcript
    llm = StubLLMClient(responses={"rate the readiness": _high_assessment()})
    node = make_estimate_confidence_node(llm)
    state = _make_state(
        transcript=[{"question": "Who?", "answer": "Devs", "options": None, "targets_section": ""}],
    )
    await node(state)

    prompt = llm.calls[0][0]
    assert "DECIDED: Devs" in prompt
```

These tests verify the split: stable context is NOT in the prompt (it's in cached_prefix), but the transcript IS in the prompt.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd libs/sdlc && uv run --group test pytest tests/unit_tests/test_brainstorm/test_confidence.py::test_confidence_node_passes_cached_prefix tests/unit_tests/test_brainstorm/test_confidence.py::test_confidence_node_cached_prefix_excludes_transcript -v`
Expected: FAIL — prompt currently contains the stable context.

- [ ] **Step 3: Write minimal implementation**

In `src/superagents_sdlc/brainstorm/confidence.py`:

1. Add import:
```python
from superagents_sdlc.brainstorm.prompts import (
    BRAINSTORM_SYSTEM,
    _build_brainstorm_cached_prefix,
)
```
(Update the existing import line to include `_build_brainstorm_cached_prefix`.)

2. Replace `_ASSESSMENT_PROMPT` — remove the stable context sections, keep only variable parts:

```python
_ASSESSMENT_PROMPT = """\
## Decisions Made So Far

The following decisions have been confirmed by the user during this brainstorm \
session. These are FINAL — do not contradict, reinterpret, or question them. \
Your readiness assessment must be consistent with these decisions.

{transcript}

Assess the brainstorm readiness. For each section below, rate the readiness \
of each brief section and provide evidence.

Readiness ratings:
- "high": Could write this section now with confidence
- "medium": Have partial information, brief would have gaps
- "low": Missing critical information, section would be speculative

Sections to rate the readiness of:
1. problem_statement — Is the problem clear?
2. users_and_personas — Do we know who uses this and how?
3. requirements — Are functional requirements specific enough?
4. acceptance_criteria — Can we write Given/When/Then for core flows?
5. scope_boundaries — Do we know what's in and out?
6. technical_constraints — Do we know tech stack and integration points?

{deferred_note}

Return ONLY valid JSON:
{{"sections": {{"problem_statement": {{"readiness": "high", "evidence": "..."}}, ...}}, \
"gaps": [{{"section": "...", "description": "..."}}], \
"recommendation": "continue" | "ready"}}
"""
```

3. Update the `estimate_confidence` function to build and pass `cached_prefix`:

```python
        cached_prefix = _build_brainstorm_cached_prefix(
            idea=state["idea"],
            product_context=state["product_context"],
            codebase_context=state["codebase_context"],
        )

        prompt = _ASSESSMENT_PROMPT.format(
            transcript=_format_transcript_for_assessment(state["transcript"]),
            deferred_note=deferred_note,
        )
        raw = await llm.generate(
            prompt, system=BRAINSTORM_SYSTEM, cached_prefix=cached_prefix,
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd libs/sdlc && uv run --group test pytest tests/unit_tests/test_brainstorm/test_confidence.py -v`
Expected: ALL pass (19 tests — 17 existing + 2 new).

Note: Existing tests use `StubLLMClient(responses={"rate the readiness": ...})`. The stub matches on prompt substring. The prompt still contains "rate the readiness" so existing stubs still match. The stable context ("Add dark mode", "Web app") is no longer in the prompt — verify none of the existing stub matchers depend on those strings (they don't — they match on "rate the readiness").

- [ ] **Step 5: Commit**

```bash
git add src/superagents_sdlc/brainstorm/confidence.py tests/unit_tests/test_brainstorm/test_confidence.py
git commit -m "feat(sdlc): add prompt caching to confidence assessment node"
```

---

### Task 3: Split remaining prompt templates + wire caching into all 4 nodes + tests

**Files:**
- Modify: `src/superagents_sdlc/brainstorm/prompts.py`
- Modify: `src/superagents_sdlc/brainstorm/nodes.py`
- Test: `tests/unit_tests/test_brainstorm/test_nodes.py`

This task is atomic: template changes and node wiring happen together so every commit leaves the codebase in a working state. Remove `{idea}`, `{product_context}`, `{codebase_context}` from all 4 remaining prompt templates AND update the 4 node factories to build `cached_prefix` and pass it to `llm.generate()`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/unit_tests/test_brainstorm/test_nodes.py`:

```python
from superagents_sdlc.brainstorm.prompts import _build_brainstorm_cached_prefix


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
    llm = _SpyLLMClient(response='{"questions": [{"question": "Q?", "options": null, "targets_section": "requirements"}]}')
    node = make_generate_question_node(llm)
    state = _make_state(
        idea="Build search",
        product_context="Enterprise SaaS",
        codebase_context="Python backend",
        section_readiness={"requirements": {"readiness": "low", "evidence": "missing"}},
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
    llm = _SpyLLMClient(response='[{"name": "Simple", "description": "d", "tradeoffs": "t"}]')
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd libs/sdlc && uv run --group test pytest tests/unit_tests/test_brainstorm/test_nodes.py -k "passes_cached_prefix" -v`
Expected: FAIL — nodes don't pass `cached_prefix` yet.

- [ ] **Step 3: Update prompt templates in `prompts.py`**

Update `QUESTION_PROMPT` — remove `## Idea`, `## Product context`, `## Codebase context` sections:

```python
QUESTION_PROMPT = """\
## Decisions Made So Far

The following decisions have been confirmed by the user during this brainstorm \
session. These are FINAL — do not contradict, reinterpret, or question them. \
Do not re-ask about decided topics.

{transcript}

## Current section readiness
{section_readiness}

## Gaps to address
{gaps}

Generate clarifying questions ONLY about sections rated "low" or "medium". \
Never ask about "high" or "deferred" sections. \
Generate 1 question per gap, up to 4 questions max. \
Each question should be specific enough that the answer directly moves a section toward "high". \
Prefer multiple-choice when the answer space is bounded. \
Return as JSON: {{"questions": [{{"question": "...", "options": ["a", "b"] | null, \
"targets_section": "section_name"}}]}}
"""
```

Update `APPROACHES_PROMPT` — remove stable context:

```python
APPROACHES_PROMPT = """\
## Decisions Made So Far

The following decisions have been confirmed by the user during this brainstorm \
session. These are FINAL — do not contradict, reinterpret, or question them. \
All proposed approaches must be consistent with these decisions.

{transcript}

Propose 2-3 distinct implementation approaches. Each should have a clear name, \
description, and honest tradeoffs section.
Return as JSON array: [{{"name": "...", "description": "...", "tradeoffs": "..."}}]
"""
```

Update `DESIGN_SECTION_PROMPT` — remove `## Idea`:

```python
DESIGN_SECTION_PROMPT = """\
## Selected approach
{selected_approach}

## Decisions Made So Far

The following decisions have been confirmed by the user during this brainstorm \
session. These are FINAL — do not contradict, reinterpret, or question them. \
This section must reflect these decisions accurately.

{transcript}

## Previously approved sections
{approved_sections}

Write the "{section_title}" section of the design document. \
Return the section content as markdown.
"""
```

Update `SYNTHESIZE_PROMPT` — remove `## Idea`:

```python
SYNTHESIZE_PROMPT = """\
## Selected approach
{selected_approach}

## Approved design sections
{sections}

Synthesize all approved sections into a single structured design brief in markdown format. \
The brief should be self-contained and readable as a standalone document.
"""
```

- [ ] **Step 4: Update `nodes.py` — add import and update all 4 nodes**

Add to imports at top of `nodes.py`:
```python
from superagents_sdlc.brainstorm.prompts import (
    ...
    _build_brainstorm_cached_prefix,
)
```

Update `generate_question` — build cached_prefix, remove stable context from format call:
```python
        cached_prefix = _build_brainstorm_cached_prefix(
            idea=state["idea"],
            product_context=state["product_context"],
            codebase_context=state["codebase_context"],
        )

        prompt = QUESTION_PROMPT.format(
            transcript=_format_transcript_for_assessment(state["transcript"]),
            section_readiness=json.dumps(readiness),
            gaps=json.dumps(gaps),
        )
        raw = await llm.generate(
            prompt, system=BRAINSTORM_SYSTEM, cached_prefix=cached_prefix,
        )
```

Update `propose_approaches` — same pattern:
```python
        cached_prefix = _build_brainstorm_cached_prefix(
            idea=state["idea"],
            product_context=state["product_context"],
            codebase_context=state["codebase_context"],
        )

        prompt = APPROACHES_PROMPT.format(
            transcript=_format_transcript_for_assessment(state["transcript"]),
        )
        raw = await llm.generate(
            prompt, system=BRAINSTORM_SYSTEM, cached_prefix=cached_prefix,
        )
```

Update `generate_design_section` — same pattern:
```python
        cached_prefix = _build_brainstorm_cached_prefix(
            idea=state["idea"],
            product_context=state["product_context"],
            codebase_context=state["codebase_context"],
        )

        prompt = DESIGN_SECTION_PROMPT.format(
            selected_approach=state["selected_approach"],
            transcript=_format_transcript_for_assessment(state["transcript"]),
            approved_sections=approved_text or "(none yet)",
            section_title=section_title,
        )
        content = await llm.generate(
            prompt, system=BRAINSTORM_SYSTEM, cached_prefix=cached_prefix,
        )
```

Update `synthesize_brief` — same pattern:
```python
        cached_prefix = _build_brainstorm_cached_prefix(
            idea=state["idea"],
            product_context=state["product_context"],
            codebase_context=state["codebase_context"],
        )

        prompt = SYNTHESIZE_PROMPT.format(
            selected_approach=state["selected_approach"],
            sections=sections_text,
        )
        brief = await llm.generate(
            prompt, system=BRAINSTORM_SYSTEM, cached_prefix=cached_prefix,
        )
```

- [ ] **Step 5: Run ALL brainstorm tests**

Run: `cd libs/sdlc && uv run --group test pytest tests/unit_tests/test_brainstorm/ -v`
Expected: ALL pass. Existing StubLLMClient tests still work because:
- Stub ignores `cached_prefix`
- Stub matches on prompt substring — the instruction keywords ("Gaps to address", "Propose 2-3", section titles, "Synthesize all") are still in the variable prompt
- The new `_SpyLLMClient` tests verify `cached_prefix` is passed and prompt doesn't contain stable context

- [ ] **Step 6: Commit**

```bash
git add src/superagents_sdlc/brainstorm/prompts.py src/superagents_sdlc/brainstorm/nodes.py tests/unit_tests/test_brainstorm/test_nodes.py
git commit -m "feat(sdlc): add prompt caching to all brainstorm node factories"
```

---

### Task 4: Full test suite pass + lint

**Files:** None (verification only)

- [ ] **Step 1: Run the full unit test suite**

Run: `cd libs/sdlc && uv run --group test pytest tests/unit_tests/ -v`
Expected: All 377+ tests pass (368 existing + 9 new).

- [ ] **Step 2: Run linter**

Run: `cd /home/matt/coding/superagents && make lint`
Expected: No new violations.

- [ ] **Step 3: Fix any failures**

If tests fail, identify root cause and fix. Common issues:
- StubLLMClient matcher substring no longer in prompt (adjust matcher)
- KeyError from template placeholders that were removed but still referenced
- Import ordering

- [ ] **Step 4: Final commit if any fixes needed**

```bash
git commit -m "fix(sdlc): resolve lint/test issues from brainstorm caching"
```
