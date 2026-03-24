# IdeaMemory Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace transcript-based decision tracking in brainstorm prompts with IdeaMemory — a ~500-token deterministic document that the LLM cannot misread.

**Architecture:** New `idea_memory.py` module with `MemoryEntry`/`IdeaMemory` dataclasses. Deterministic write path: code appends decisions when users answer questions. IdeaMemory replaces `{transcript}` in all 5 brainstorm prompt templates. Transcript still exists in state for diagnostics. IdeaMemory travels into the pipeline via `--idea-memory` CLI flag.

**Tech Stack:** Python dataclasses, LangGraph state (JSON-serializable), existing brainstorm infrastructure

**Spec:** `docs/superpowers/specs/2026-03-24-idea-memory-design.md`

---

## File Structure

| File | Action | What Changes |
|------|--------|-------------|
| `src/superagents_sdlc/brainstorm/idea_memory.py` | Create | `MemoryEntry` + `IdeaMemory` dataclasses |
| `src/superagents_sdlc/brainstorm/prompts.py` | Modify | Add `SECTION_TITLES`, replace `{transcript}` with `{idea_memory}` in 4 templates |
| `src/superagents_sdlc/brainstorm/nodes.py` | Modify | Remove `_SECTION_TITLES`, add decision capture, pass IdeaMemory to prompts |
| `src/superagents_sdlc/brainstorm/confidence.py` | Modify | Replace `_ASSESSMENT_PROMPT`, remove `_format_transcript_for_assessment`, pass IdeaMemory |
| `src/superagents_sdlc/brainstorm/state.py` | Modify | Add 2 fields |
| `src/superagents_sdlc/cli.py` | Modify | Write `idea_memory.md`, add `--idea-memory` flag |
| `src/superagents_sdlc/workflows/orchestrator.py` | Modify | Include IdeaMemory in cached prefix |
| `tests/unit_tests/test_brainstorm/test_idea_memory.py` | Create | 5 data model tests |
| `tests/unit_tests/test_brainstorm/test_confidence.py` | Modify | Remove old tests, add IdeaMemory test, update helpers |
| `tests/unit_tests/test_brainstorm/test_nodes.py` | Modify | Remove old tests, add IdeaMemory tests, update helpers |
| `tests/unit_tests/test_brainstorm/test_graph.py` | Modify | Update state helpers |
| `tests/unit_tests/test_brainstorm/test_cli_brainstorm.py` | Modify | Add disk output test |
| `tests/unit_tests/test_workflows/test_orchestrator.py` | Modify | Add cached prefix test |

All paths relative to `libs/sdlc/`.

---

### Task 1: IdeaMemory data model + 5 tests

**Files:**
- Create: `src/superagents_sdlc/brainstorm/idea_memory.py`
- Create: `tests/unit_tests/test_brainstorm/test_idea_memory.py`

- [ ] **Step 1: Write the 5 failing tests**

Create `tests/unit_tests/test_brainstorm/test_idea_memory.py`:

```python
"""Tests for IdeaMemory canonical decision record."""

from __future__ import annotations

from superagents_sdlc.brainstorm.idea_memory import IdeaMemory


def test_add_decision():
    """Adding a decision assigns ID D1."""
    mem = IdeaMemory(idea_title="Test Feature")
    entry_id = mem.add_decision(title="Storage", text="Use PostgreSQL")
    assert entry_id == "D1"
    assert len(mem.entries) == 1
    assert mem.entries[0].type == "decision"


def test_add_rejection():
    """Adding a rejection assigns ID R1."""
    mem = IdeaMemory(idea_title="Test Feature")
    entry_id = mem.add_rejection(title="Storage", text="Rejected: SQLite")
    assert entry_id == "R1"
    assert mem.entries[0].type == "rejection"


def test_format_for_prompt():
    """Formatted output contains IDs, titles, tags, and text."""
    mem = IdeaMemory(idea_title="Dark Mode")
    mem.add_decision(title="Scope", text="Toggle in settings only")
    mem.add_decision(title="Tech", text="CSS variables")
    mem.add_rejection(title="Scope", text="Rejected: system-wide theme")

    output = mem.format_for_prompt()
    assert "# IdeaMemory: Dark Mode" in output
    assert "Locked Decisions" in output
    assert "### D1: Scope [decision]" in output
    assert "Toggle in settings only" in output
    assert "### D2: Tech [decision]" in output
    assert "### R1: Scope [rejection]" in output
    assert "Rejected: system-wide theme" in output


def test_format_for_prompt_empty():
    """Empty IdeaMemory returns placeholder."""
    mem = IdeaMemory(idea_title="X")
    assert mem.format_for_prompt() == "No decisions have been made yet."


def test_to_state_and_from_state():
    """Round-trip through state serialization."""
    mem = IdeaMemory(idea_title="Feature")
    mem.add_decision(title="A", text="Choice A")
    mem.add_rejection(title="B", text="Not B")

    state_entries = mem.to_state()
    counts = mem.counts

    restored = IdeaMemory.from_state("Feature", state_entries, counts)
    assert len(restored.entries) == 2
    assert restored.entries[0].id == "D1"
    assert restored.entries[1].id == "R1"
    assert restored.format_for_prompt() == mem.format_for_prompt()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd libs/sdlc && uv run --group test pytest tests/unit_tests/test_brainstorm/test_idea_memory.py -v`
Expected: ImportError — `idea_memory` module doesn't exist.

- [ ] **Step 3: Write the implementation**

Create `src/superagents_sdlc/brainstorm/idea_memory.py`:

```python
"""IdeaMemory — canonical decision record for brainstorm sessions.

Provides a deterministic, structured, immutable record of user decisions.
Written by code (not LLM) and injected into all brainstorm prompts as the
single source of truth for what was decided.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class MemoryEntry:
    """Single entry in IdeaMemory.

    Attributes:
        id: Stable identifier (e.g., "D1", "R1").
        title: Human-readable section title.
        type: Entry type ("decision" or "rejection").
        text: Canonical text (1-3 sentences).
    """

    id: str
    title: str
    type: str
    text: str


@dataclass
class IdeaMemory:
    """Canonical record of brainstorm decisions.

    Attributes:
        idea_title: The feature being brainstormed.
        entries: Ordered list of decision/rejection entries.
    """

    idea_title: str
    entries: list[MemoryEntry] = field(default_factory=list)
    _decision_count: int = field(default=0, repr=False, compare=False)
    _rejection_count: int = field(default=0, repr=False, compare=False)

    @property
    def counts(self) -> dict:
        """Return current entry counts for state serialization."""
        return {"decision": self._decision_count, "rejection": self._rejection_count}

    def add_decision(self, title: str, text: str) -> str:
        """Add a decision entry.

        Args:
            title: Human-readable section title.
            text: Canonical decision text.

        Returns:
            Assigned entry ID (e.g., "D1").
        """
        self._decision_count += 1
        entry_id = f"D{self._decision_count}"
        self.entries.append(MemoryEntry(
            id=entry_id, title=title, type="decision", text=text,
        ))
        return entry_id

    def add_rejection(self, title: str, text: str) -> str:
        """Add a rejection entry.

        Args:
            title: Human-readable section title.
            text: Canonical rejection text.

        Returns:
            Assigned entry ID (e.g., "R1").
        """
        self._rejection_count += 1
        entry_id = f"R{self._rejection_count}"
        self.entries.append(MemoryEntry(
            id=entry_id, title=title, type="rejection", text=text,
        ))
        return entry_id

    def format_for_prompt(self) -> str:
        """Format IdeaMemory as a prompt block.

        Returns:
            Structured text for LLM prompt injection, or a placeholder
            when no decisions exist.
        """
        if not self.entries:
            return "No decisions have been made yet."

        lines = [
            f"# IdeaMemory: {self.idea_title}",
            "",
            "## Locked Decisions (DO NOT OVERRIDE)",
            "",
        ]
        for entry in self.entries:
            lines.append(f"### {entry.id}: {entry.title} [{entry.type}]")
            lines.append(entry.text)
            lines.append("")
        return "\n".join(lines)

    def to_markdown(self) -> str:
        """Serialize to markdown for writing to disk.

        Returns:
            Same as ``format_for_prompt()``.
        """
        return self.format_for_prompt()

    def to_state(self) -> list[dict]:
        """Serialize entries for LangGraph state.

        Returns:
            List of dicts, each with id, title, type, text keys.
        """
        return [
            {"id": e.id, "title": e.title, "type": e.type, "text": e.text}
            for e in self.entries
        ]

    @classmethod
    def from_state(
        cls,
        idea_title: str,
        entries: list[dict],
        counts: dict,
    ) -> IdeaMemory:
        """Reconstruct IdeaMemory from LangGraph state.

        Args:
            idea_title: The feature being brainstormed.
            entries: Serialized entry dicts from state.
            counts: Dict with "decision" and "rejection" counters.

        Returns:
            Reconstructed IdeaMemory instance.
        """
        mem = cls(idea_title=idea_title)
        mem._decision_count = counts.get("decision", 0)
        mem._rejection_count = counts.get("rejection", 0)
        mem.entries = [
            MemoryEntry(
                id=e["id"], title=e["title"], type=e["type"], text=e["text"],
            )
            for e in entries
        ]
        return mem
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd libs/sdlc && uv run --group test pytest tests/unit_tests/test_brainstorm/test_idea_memory.py -v`
Expected: 5 PASSED

- [ ] **Step 5: Commit**

```bash
git add src/superagents_sdlc/brainstorm/idea_memory.py tests/unit_tests/test_brainstorm/test_idea_memory.py
git commit -m "feat(sdlc): add IdeaMemory data model with serialization"
```

---

### Task 2: Move SECTION_TITLES to prompts.py

**Files:**
- Modify: `src/superagents_sdlc/brainstorm/prompts.py`
- Modify: `src/superagents_sdlc/brainstorm/nodes.py`

No new tests — this is a pure refactor. Existing tests cover the behavior.

- [ ] **Step 1: Add `SECTION_TITLES` to `prompts.py`**

Add after the `_build_brainstorm_cached_prefix` function (or after `DESIGN_SECTIONS` list):

```python
SECTION_TITLES = {
    "problem_statement": "Problem Statement & Goals",
    "users_and_personas": "Target Users & Personas",
    "requirements": "Requirements & User Stories",
    "acceptance_criteria": "Acceptance Criteria",
    "scope_boundaries": "Scope Boundaries & Out of Scope",
    "technical_constraints": "Technical Constraints & Dependencies",
}
```

- [ ] **Step 2: Update `nodes.py` to import from prompts**

Remove the `_SECTION_TITLES` dict (lines 34-41 of `nodes.py`).

Add `SECTION_TITLES` to the import from `prompts`:
```python
from superagents_sdlc.brainstorm.prompts import (
    ...
    SECTION_TITLES,
)
```

Replace all references to `_SECTION_TITLES` with `SECTION_TITLES` in `nodes.py`. There's one reference in `_deferred_title` (line 52):
```python
return SECTION_TITLES.get(section, section.replace("_", " ").title())
```

- [ ] **Step 3: Run brainstorm tests**

Run: `cd libs/sdlc && uv run --group test pytest tests/unit_tests/test_brainstorm/ -v`
Expected: ALL pass (no behavior change).

- [ ] **Step 4: Commit**

```bash
git add src/superagents_sdlc/brainstorm/prompts.py src/superagents_sdlc/brainstorm/nodes.py
git commit -m "refactor(sdlc): move SECTION_TITLES to prompts.py to avoid circular imports"
```

---

### Task 3: State fields + explore_context initialization + test helper updates

**Files:**
- Modify: `src/superagents_sdlc/brainstorm/state.py`
- Modify: `src/superagents_sdlc/brainstorm/nodes.py`
- Modify: `tests/unit_tests/test_brainstorm/test_nodes.py`
- Modify: `tests/unit_tests/test_brainstorm/test_confidence.py`
- Modify: `tests/unit_tests/test_brainstorm/test_graph.py`

- [ ] **Step 1: Add fields to `BrainstormState`**

In `state.py`, add two fields to the TypedDict and docstring:

```python
    idea_memory: list[dict]
    idea_memory_counts: dict
```

- [ ] **Step 2: Update `explore_context` in `nodes.py`**

Add to the return dict in `explore_context`:
```python
            "idea_memory": [],
            "idea_memory_counts": {"decision": 0, "rejection": 0},
```

- [ ] **Step 3: Update all test state helpers**

In `test_nodes.py` `_make_state()`, add:
```python
        "idea_memory": [],
        "idea_memory_counts": {"decision": 0, "rejection": 0},
```

In `test_confidence.py` `_make_state()`, add the same two fields.

In `test_graph.py`, find the initial state dict (in `_initial_state()` or inline) and add the same two fields.

Update `test_brainstorm_state_is_typeddict` in `test_nodes.py`: change `assert len(state) == 16` to `assert len(state) == 18`.

- [ ] **Step 4: Run all brainstorm tests**

Run: `cd libs/sdlc && uv run --group test pytest tests/unit_tests/test_brainstorm/ -v`
Expected: ALL pass.

- [ ] **Step 5: Commit**

```bash
git add src/superagents_sdlc/brainstorm/state.py src/superagents_sdlc/brainstorm/nodes.py tests/unit_tests/test_brainstorm/
git commit -m "feat(sdlc): add idea_memory fields to BrainstormState"
```

---

### Task 4: Decision capture in generate_question + 3 tests

**Files:**
- Modify: `src/superagents_sdlc/brainstorm/nodes.py`
- Test: `tests/unit_tests/test_brainstorm/test_nodes.py`

- [ ] **Step 1: Write the 3 failing tests**

Append to `tests/unit_tests/test_brainstorm/test_nodes.py`:

```python
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
    """Decision title comes from SECTION_TITLES mapping."""
    llm = StubLLMClient(responses={
        "## Gaps to address": json.dumps({
            "questions": [
                {"question": "Tech?", "options": None,
                 "targets_section": "technical_constraints"},
            ],
        }),
    })
    node = make_generate_question_node(llm)

    with patch(_INTERRUPT_PATH, return_value=["PostgreSQL"]):
        result = await node(_make_state())

    assert result["idea_memory"][0]["title"] == "Technical Constraints & Dependencies"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd libs/sdlc && uv run --group test pytest tests/unit_tests/test_brainstorm/test_nodes.py -k "idea_memory" -v`
Expected: FAIL — `idea_memory` key not in result dict.

- [ ] **Step 3: Update `generate_question` in `nodes.py`**

Add import at top:
```python
from superagents_sdlc.brainstorm.idea_memory import IdeaMemory
```

In the `generate_question` function, after the answer resolution loop (after line ~175 where transcript is built), add IdeaMemory capture:

```python
        # Update IdeaMemory with decisions (reuse already-resolved answers from transcript)
        memory = IdeaMemory.from_state(
            state["idea"],
            list(state.get("idea_memory", [])),
            dict(state.get("idea_memory_counts", {"decision": 0, "rejection": 0})),
        )
        for entry in updated[len(state["transcript"]):]:  # only new entries
            section = entry.get("targets_section", "")
            title = SECTION_TITLES.get(
                section, section.replace("_", " ").title(),
            )
            memory.add_decision(title=title, text=entry["answer"])
```

Update the return dict to include:
```python
            "idea_memory": memory.to_state(),
            "idea_memory_counts": memory.counts,
```

Note: The answer resolution already happens earlier in the existing code. The `resolved` variable is already computed. Reuse it — don't re-resolve. Adjust the code to capture the resolved answer text that's already being stored in the transcript.

- [ ] **Step 4: Run tests**

Run: `cd libs/sdlc && uv run --group test pytest tests/unit_tests/test_brainstorm/test_nodes.py -v`
Expected: ALL pass.

- [ ] **Step 5: Commit**

```bash
git add src/superagents_sdlc/brainstorm/nodes.py tests/unit_tests/test_brainstorm/test_nodes.py
git commit -m "feat(sdlc): capture decisions in IdeaMemory during question answering"
```

---

### Task 5: Replace transcript with IdeaMemory in confidence prompt + 1 test

**Files:**
- Modify: `src/superagents_sdlc/brainstorm/confidence.py`
- Modify: `tests/unit_tests/test_brainstorm/test_confidence.py`

This task also removes `_format_transcript_for_assessment` and its tests, and removes the echo-first tests.

- [ ] **Step 1: Write the failing test**

Add to `test_confidence.py`:

```python
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
```

- [ ] **Step 2: Remove obsolete tests**

Remove from `test_confidence.py`:
- `test_format_transcript_empty`
- `test_format_transcript_single_entry`
- `test_format_transcript_excludes_options`
- `test_format_transcript_multiple_entries`
- `test_confidence_prompt_contains_decisions_framing`
- `test_confidence_prompt_uses_formatted_transcript`
- `test_confidence_prompt_requires_echo_step`
- `test_confidence_prompt_contains_critical_rules`
- `test_confidence_prompt_evidence_quote_only`

Also remove the import of `_format_transcript_for_assessment` from the test file.

- [ ] **Step 3: Run new test to verify it fails**

Run: `cd libs/sdlc && uv run --group test pytest tests/unit_tests/test_brainstorm/test_confidence.py::test_confidence_prompt_contains_idea_memory -v`
Expected: FAIL — prompt still uses transcript.

- [ ] **Step 4: Update `confidence.py`**

Keep `_format_transcript_for_assessment` in the file for now — `nodes.py` still imports it. It will be removed in Task 6 when `nodes.py` drops the import.

Add import:
```python
from superagents_sdlc.brainstorm.idea_memory import IdeaMemory
```

Replace `_ASSESSMENT_PROMPT`:

```python
_ASSESSMENT_PROMPT = """\
## IdeaMemory — Canonical Decisions

The following decisions are FINAL. They were recorded exactly as the user \
stated them. You MUST NOT contradict, reinterpret, narrow, extend, or \
synthesize beyond what is written here.

{idea_memory}

Rate each section's readiness based ONLY on what IdeaMemory contains. \
If IdeaMemory has no entry for a section, rate it "low". \
If IdeaMemory has a clear decision for a section, rate it "high".

Readiness ratings:
- "high": Could write this section now with confidence
- "medium": Have partial information, brief would have gaps
- "low": Missing critical information, section would be speculative

Sections to rate:
1. problem_statement — Is the problem clear?
2. users_and_personas — Do we know who uses this and how?
3. requirements — Are functional requirements specific enough?
4. acceptance_criteria — Can we write Given/When/Then for core flows?
5. scope_boundaries — Do we know what's in and out?
6. technical_constraints — Do we know tech stack and integration points?

{deferred_note}

Return ONLY valid JSON:
For the "evidence" field: quote ONLY from IdeaMemory above. \
If no entry addresses this section, write "No decision made yet."
{{"sections": {{"problem_statement": {{"readiness": "high", "evidence": "..."}}, ...}}, \
"gaps": [{{"section": "...", "description": "..."}}], \
"recommendation": "continue" | "ready"}}
"""
```

Update `estimate_confidence` function — replace transcript formatting with IdeaMemory:

```python
        memory = IdeaMemory.from_state(
            state["idea"],
            list(state.get("idea_memory", [])),
            dict(state.get("idea_memory_counts", {"decision": 0, "rejection": 0})),
        )

        prompt = _ASSESSMENT_PROMPT.format(
            idea_memory=memory.format_for_prompt(),
            deferred_note=deferred_note,
        )
```

- [ ] **Step 5: Update graph test stub matcher**

In `tests/unit_tests/test_brainstorm/test_graph.py`, in `_make_full_stub()`, change `"rate the readiness"` to `"Readiness ratings"`. The old matcher `"rate the readiness"` no longer appears in the new prompt template (which says "Rate each section's readiness" and "Readiness ratings:").

- [ ] **Step 6: Run ALL brainstorm tests (confidence + graph)**

Run: `cd libs/sdlc && uv run --group test pytest tests/unit_tests/test_brainstorm/test_confidence.py tests/unit_tests/test_brainstorm/test_graph.py -v`
Expected: ALL pass.

- [ ] **Step 7: Commit**

```bash
git add src/superagents_sdlc/brainstorm/confidence.py tests/unit_tests/test_brainstorm/test_confidence.py tests/unit_tests/test_brainstorm/test_graph.py
git commit -m "feat(sdlc): replace transcript with IdeaMemory in confidence assessment"
```

---

### Task 6: Replace transcript in 4 node prompts + remove old tests + 3 tests

**Files:**
- Modify: `src/superagents_sdlc/brainstorm/prompts.py`
- Modify: `src/superagents_sdlc/brainstorm/nodes.py`
- Modify: `tests/unit_tests/test_brainstorm/test_nodes.py`

This is an atomic task: templates, node wiring, and tests change together.

- [ ] **Step 1: Write the 4 failing tests**

Add to `test_nodes.py` (use `_SpyLLMClient` which already exists):

```python
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
        section_readiness={"requirements": {"readiness": "low", "evidence": "missing"}},
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
```

- [ ] **Step 2: Remove obsolete tests from `test_nodes.py`**

Remove:
- `test_node_prompts_contain_echo_instruction`
- `test_synthesize_node_includes_transcript`

- [ ] **Step 3: Run new tests to verify they fail**

Run: `cd libs/sdlc && uv run --group test pytest tests/unit_tests/test_brainstorm/test_nodes.py -k "idea_memory" -v`
Expected: FAIL — prompts still use `{transcript}`.

- [ ] **Step 4: Update prompt templates in `prompts.py`**

Replace `{transcript}` and surrounding framing with `{idea_memory}` in all 4 templates. Remove echo-first instructions.

`QUESTION_PROMPT`:
```python
QUESTION_PROMPT = """\
## IdeaMemory — Canonical Decisions

{idea_memory}

Do not ask about topics already decided in IdeaMemory.

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

`APPROACHES_PROMPT`:
```python
APPROACHES_PROMPT = """\
## IdeaMemory — Canonical Decisions

{idea_memory}

All approaches must be consistent with IdeaMemory.

Propose 2-3 distinct implementation approaches. Each should have a clear name, \
description, and honest tradeoffs section.
Return as JSON array: [{{"name": "...", "description": "...", "tradeoffs": "..."}}]
"""
```

`DESIGN_SECTION_PROMPT`:
```python
DESIGN_SECTION_PROMPT = """\
## Selected approach
{selected_approach}

## IdeaMemory — Canonical Decisions

{idea_memory}

This section must reflect IdeaMemory decisions exactly.

## Previously approved sections
{approved_sections}

Write the "{section_title}" section of the design document. \
Return the section content as markdown.
"""
```

`SYNTHESIZE_PROMPT`:
```python
SYNTHESIZE_PROMPT = """\
## Selected approach
{selected_approach}

## IdeaMemory — Canonical Decisions

{idea_memory}

The brief must incorporate every IdeaMemory entry.

## Approved design sections
{sections}

Synthesize all approved sections into a single structured design brief in markdown format. \
The brief should be self-contained and readable as a standalone document.
"""
```

- [ ] **Step 5: Update all 4 nodes in `nodes.py`**

Remove the `_format_transcript_for_assessment` import from `nodes.py`. Also remove the `_format_transcript_for_assessment` function from `confidence.py` (deferred from Task 5 to avoid breaking the nodes import).

Add `IdeaMemory` import (if not already present from Task 4):
```python
from superagents_sdlc.brainstorm.idea_memory import IdeaMemory
```

Add a helper to reconstruct IdeaMemory from state (used by all nodes):
```python
def _idea_memory_from_state(state: BrainstormState) -> IdeaMemory:
    """Reconstruct IdeaMemory from brainstorm state."""
    return IdeaMemory.from_state(
        state["idea"],
        list(state.get("idea_memory", [])),
        dict(state.get("idea_memory_counts", {"decision": 0, "rejection": 0})),
    )
```

Update each node's prompt formatting:

**generate_question**: replace `transcript=_format_transcript_for_assessment(state["transcript"])` with `idea_memory=_idea_memory_from_state(state).format_for_prompt()`. Remove `idea`, `product_context`, `codebase_context` — those are already gone (they're in cached_prefix). Keep `section_readiness` and `gaps`.

**propose_approaches**: replace `transcript=...` with `idea_memory=_idea_memory_from_state(state).format_for_prompt()`.

**generate_design_section**: replace `transcript=...` with `idea_memory=_idea_memory_from_state(state).format_for_prompt()`.

**synthesize_brief**: replace `transcript=...` with `idea_memory=_idea_memory_from_state(state).format_for_prompt()`.

- [ ] **Step 6: Run ALL brainstorm tests**

Run: `cd libs/sdlc && uv run --group test pytest tests/unit_tests/test_brainstorm/ -v`
Expected: ALL pass.

- [ ] **Step 7: Commit**

```bash
git add src/superagents_sdlc/brainstorm/prompts.py src/superagents_sdlc/brainstorm/nodes.py tests/unit_tests/test_brainstorm/test_nodes.py
git commit -m "feat(sdlc): replace transcript with IdeaMemory in all brainstorm prompts"
```

---

### Task 7: Write IdeaMemory to disk + 1 test

**Files:**
- Modify: `src/superagents_sdlc/cli.py`
- Test: `tests/unit_tests/test_brainstorm/test_cli_brainstorm.py`

- [ ] **Step 1: Write the failing test**

Add to `test_cli_brainstorm.py`:

```python
def test_idea_memory_written_to_disk(tmp_path):
    """IdeaMemory file is written alongside the brief."""
    from superagents_sdlc.brainstorm.idea_memory import IdeaMemory

    mem = IdeaMemory(idea_title="Test")
    mem.add_decision(title="Tech", text="Use Go")

    out = tmp_path / "output"
    out.mkdir()
    (out / "idea_memory.md").write_text(mem.to_markdown())

    content = (out / "idea_memory.md").read_text()
    assert "IdeaMemory: Test" in content
    assert "Use Go" in content
```

This tests the IdeaMemory → disk path in isolation. The actual CLI wiring is tested by the existing end-to-end test if it uses `--output-dir`.

- [ ] **Step 2: Update `_run_brainstorm` in `cli.py`**

After the existing brief-writing block (around line 507), add IdeaMemory output:

```python
        # Write IdeaMemory
        from superagents_sdlc.brainstorm.idea_memory import IdeaMemory  # noqa: PLC0415

        memory = IdeaMemory.from_state(
            args.idea,
            result.get("idea_memory", []),
            result.get("idea_memory_counts", {"decision": 0, "rejection": 0}),
        )
        (out / "idea_memory.md").write_text(memory.to_markdown())
        if not args.quiet:
            print(f"IdeaMemory written to {out / 'idea_memory.md'}")  # noqa: T201
```

- [ ] **Step 3: Run test**

Run: `cd libs/sdlc && uv run --group test pytest tests/unit_tests/test_brainstorm/test_cli_brainstorm.py -v`
Expected: ALL pass.

- [ ] **Step 4: Commit**

```bash
git add src/superagents_sdlc/cli.py tests/unit_tests/test_brainstorm/test_cli_brainstorm.py
git commit -m "feat(sdlc): write idea_memory.md alongside design brief"
```

---

### Task 8: CLI --idea-memory flag + orchestrator wiring + 1 test

**Files:**
- Modify: `src/superagents_sdlc/cli.py`
- Modify: `src/superagents_sdlc/workflows/orchestrator.py`
- Test: `tests/unit_tests/test_workflows/test_orchestrator.py`

- [ ] **Step 1: Write the failing test**

Add to `test_orchestrator.py`:

```python
async def test_cached_prefix_includes_idea_memory():
    """Orchestrator includes IdeaMemory in cached prefix when provided."""
    orchestrator, _ = _make_orchestrator()
    params = {
        "idea_memory": "# IdeaMemory: Test\n## Locked Decisions\n### D1: Tech [decision]\nUse Go",
    }
    prefix = orchestrator._build_cached_prefix(params)
    assert prefix is not None
    assert "IdeaMemory" in prefix
    assert "Use Go" in prefix
```

Check how `_make_orchestrator` works in the existing test file to construct this correctly.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd libs/sdlc && uv run --group test pytest tests/unit_tests/test_workflows/test_orchestrator.py::test_cached_prefix_includes_idea_memory -v`
Expected: FAIL — `idea_memory` key not in the parts loop.

- [ ] **Step 3: Add `--idea-memory` to CLI shared parser**

In `cli.py`, in the `parse_args` function, add to the shared parser:

```python
    shared.add_argument(
        "--idea-memory",
        type=Path,
        default=None,
        help="Path to IdeaMemory file from brainstorm",
    )
```

In the pipeline entry point (where context is assembled for the orchestrator), read the file and pass it as context:

```python
    if args.idea_memory:
        context_overrides["idea_memory"] = args.idea_memory.read_text()
```

- [ ] **Step 4: Add `idea_memory` to `_build_cached_prefix`**

In `orchestrator.py`, add to the `parts` loop list:

```python
            ("idea_memory", "IdeaMemory — Locked Decisions"),
```

- [ ] **Step 5: Run test**

Run: `cd libs/sdlc && uv run --group test pytest tests/unit_tests/test_workflows/test_orchestrator.py::test_cached_prefix_includes_idea_memory -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/superagents_sdlc/cli.py src/superagents_sdlc/workflows/orchestrator.py tests/unit_tests/test_workflows/test_orchestrator.py
git commit -m "feat(sdlc): add --idea-memory CLI flag and orchestrator integration"
```

---

### Task 9: Full test suite pass + lint

**Files:** None (verification only)

- [ ] **Step 1: Run the full unit test suite**

Run: `cd libs/sdlc && uv run --group test pytest tests/unit_tests/ -v`
Expected: All tests pass (count will change due to removed/added tests).

- [ ] **Step 2: Run linter**

Run: `cd /home/matt/coding/superagents && make lint`
Expected: No new violations.

- [ ] **Step 3: Fix any failures**

Common issues:
- Unused imports of `_format_transcript_for_assessment`
- StubLLMClient matchers that no longer match (template text changed)
- Missing `idea_memory`/`idea_memory_counts` in test state dicts
- E501 line length on new prompt text

- [ ] **Step 4: Final commit if any fixes needed**

```bash
git commit -m "fix(sdlc): resolve lint/test issues from IdeaMemory integration"
```
