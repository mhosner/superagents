# IdeaMemory — Canonical Decision Record Design Spec

## Problem

Three rounds of prompt engineering (DECIDED framing, structured formatting, echo-first with critical rules) failed to stop the confidence assessment from misreading user decisions. The LLM consistently narrows broad decisions, invents features never discussed, and inverts explicit rejections.

Root cause: the transcript is conversation history embedded in a large prompt. The LLM synthesizes from it rather than reading it as constraints. No amount of prompt instruction reliably prevents this.

## Solution

IdeaMemory replaces transcript-based decision tracking with a short (~500 token), structured, immutable document written by deterministic code. No LLM in the write path.

## Design Decisions (locked)

- **Deterministic write path.** When the user answers a question, code extracts the decision text and appends it to IdeaMemory. The LLM never writes to IdeaMemory.
- **Two entry types for V1:** `decision` and `rejection`. V1 only auto-generates decisions. Rejections are reserved for the future correction flow. Schema supports future types without changes.
- **Each entry has:** a stable ID (D1, D2... / R1, R2...), a human-readable title (from `SECTION_TITLES`), a type tag, and 1-3 sentences of canonical text.
- **~500 tokens total** for a typical brainstorm.
- **IdeaMemory replaces the transcript in all prompts.** Transcript still exists in state for diagnostics but is not passed to any prompt.
- **Written to disk** alongside the brief as `idea_memory.md`.
- **Travels into the pipeline** via `--idea-memory` CLI flag, included in cached_prefix for all persona calls.

## Changes

### 1. IdeaMemory data model

**File:** `libs/sdlc/src/superagents_sdlc/brainstorm/idea_memory.py` (NEW)

Two dataclasses:

`MemoryEntry`: `id` (str), `title` (str), `type` (str), `text` (str).

`IdeaMemory`: `idea_title` (str), `entries` (list[MemoryEntry]), internal counters.

Methods:
- `add_decision(title, text) -> str` — appends with ID `D{n}`, returns ID
- `add_rejection(title, text) -> str` — appends with ID `R{n}`, returns ID
- `format_for_prompt() -> str` — renders prompt block: `# IdeaMemory: {title}`, `## Locked Decisions (DO NOT OVERRIDE)`, each entry as `### D1: Title [decision]` + text
- `to_markdown() -> str` — alias for `format_for_prompt()`
- `to_state() -> list[dict]` — serialize entries for LangGraph state
- `from_state(idea_title, entries, counts) -> IdeaMemory` — reconstruct from state

### 2. Move SECTION_TITLES to prompts.py

**File:** `libs/sdlc/src/superagents_sdlc/brainstorm/prompts.py` (MODIFY)

Move `_SECTION_TITLES` dict from `nodes.py` to `prompts.py` and rename to `SECTION_TITLES` (public). This avoids circular imports since both `nodes.py` and `idea_memory.py` import from `prompts.py`.

**File:** `libs/sdlc/src/superagents_sdlc/brainstorm/nodes.py` (MODIFY)

Update import: `from superagents_sdlc.brainstorm.prompts import SECTION_TITLES`. Replace all references to `_SECTION_TITLES` with `SECTION_TITLES`.

### 3. State integration

**File:** `libs/sdlc/src/superagents_sdlc/brainstorm/state.py` (MODIFY)

Add two fields to `BrainstormState`:
- `idea_memory: list[dict]` — serialized MemoryEntry dicts
- `idea_memory_counts: dict` — `{"decision": int, "rejection": int}`

**File:** `libs/sdlc/src/superagents_sdlc/brainstorm/nodes.py` (MODIFY)

`explore_context` node initializes: `idea_memory: []`, `idea_memory_counts: {"decision": 0, "rejection": 0}`.

### 4. Decision capture in generate_question

**File:** `libs/sdlc/src/superagents_sdlc/brainstorm/nodes.py` (MODIFY)

In the resume path of `generate_question`, after answers are resolved and transcript is updated:

1. Reconstruct `IdeaMemory` from `state["idea_memory"]` and `state["idea_memory_counts"]`
2. For each answered question: look up human-readable title via `SECTION_TITLES.get(targets_section, targets_section.replace("_", " ").title())`, call `idea_memory.add_decision(title, resolved_answer)`
3. Return updated `idea_memory` and `idea_memory_counts` alongside existing transcript/round_number

No automatic rejections in V1.

### 5. Replace transcript with IdeaMemory in all prompts

**File:** `libs/sdlc/src/superagents_sdlc/brainstorm/confidence.py` (MODIFY)

Replace `_ASSESSMENT_PROMPT`:
- Remove echo-first Step 1/Step 2 structure and critical rules (structural fix replaces prompt workaround)
- Replace `{transcript}` placeholder with `{idea_memory}`
- New framing:

```
## IdeaMemory — Canonical Decisions

The following decisions are FINAL. They were recorded exactly as the user
stated them. You MUST NOT contradict, reinterpret, narrow, extend, or
synthesize beyond what is written here.

{idea_memory}

Rate each section's readiness based ONLY on what IdeaMemory contains.
If IdeaMemory has no entry for a section, rate it "low".
If IdeaMemory has a clear decision for a section, rate it "high".
```

- Evidence field constraint kept: "quote ONLY from IdeaMemory above"

Update `estimate_confidence` function: pass `idea_memory=idea_memory.format_for_prompt()` instead of `transcript=_format_transcript_for_assessment(...)`.

**File:** `libs/sdlc/src/superagents_sdlc/brainstorm/prompts.py` (MODIFY)

Replace `{transcript}` with `{idea_memory}` in all 4 templates:

- `QUESTION_PROMPT`: IdeaMemory block + "Do not ask about topics already decided in IdeaMemory."
- `APPROACHES_PROMPT`: IdeaMemory block + "All approaches must be consistent with IdeaMemory."
- `DESIGN_SECTION_PROMPT`: IdeaMemory block + "This section must reflect IdeaMemory decisions exactly."
- `SYNTHESIZE_PROMPT`: IdeaMemory block + "The brief must incorporate every IdeaMemory entry."

Remove echo-first "list each decision" instructions from all templates (the structural fix replaces them).

**File:** `libs/sdlc/src/superagents_sdlc/brainstorm/nodes.py` (MODIFY)

Each node that formats a prompt: reconstruct IdeaMemory from state, pass `idea_memory=idea_memory.format_for_prompt()` to `.format()`. Remove `_format_transcript_for_assessment` from prompt formatting calls (keep the import for transcript — it's still used for transcript storage, just not prompt injection).

### 6. Write IdeaMemory to disk

**File:** `libs/sdlc/src/superagents_sdlc/cli.py` (MODIFY)

In `_run_brainstorm`, after writing the brief to `output_dir`, also reconstruct IdeaMemory from final state and write `idea_memory.md`:

```python
if args.output_dir:
    # ... existing brief write ...
    memory = IdeaMemory.from_state(
        args.idea,
        result.get("idea_memory", []),
        result.get("idea_memory_counts", {"decision": 0, "rejection": 0}),
    )
    (out / "idea_memory.md").write_text(memory.to_markdown())
```

### 7. Pipeline integration (--idea-memory flag)

**File:** `libs/sdlc/src/superagents_sdlc/cli.py` (MODIFY)

Add `--idea-memory` argument to the shared argument parser:

```python
shared.add_argument(
    "--idea-memory", type=Path, default=None,
    help="Path to IdeaMemory file from brainstorm",
)
```

Read the file content and pass it to the orchestrator as context.

**File:** `libs/sdlc/src/superagents_sdlc/workflows/orchestrator.py` (MODIFY)

In `_build_cached_prefix`, if `idea_memory` key is present in params:

```python
("idea_memory", "IdeaMemory — Locked Decisions"),
```

Add to the existing `parts` loop so it's included in the cached prefix for all persona calls.

## What Does NOT Change

- Transcript data schema — still exists, still updated, not passed to prompts
- `_format_transcript_for_assessment()` function — still exists for transcript storage
- Confidence scoring math
- CLI interrupt handler display logic
- Graph routing logic

## Tests

### IdeaMemory data model (5 tests)
- `test_add_decision` — adds entry, ID is D1
- `test_add_rejection` — adds entry, ID is R1
- `test_format_for_prompt` — 3 entries formatted with IDs, titles, tags, text
- `test_format_for_prompt_empty` — returns "No decisions have been made yet."
- `test_to_state_and_from_state` — round-trip through state serialization

### State integration (2 tests)
- `test_explore_context_initializes_idea_memory` — `idea_memory` is `[]`, `idea_memory_counts` is `{"decision": 0, "rejection": 0}`
- `test_brainstorm_state_field_count` — update existing test for new field count (16 -> 18)

### Decision capture (3 tests)
- `test_question_answer_adds_to_idea_memory` — answer a question, assert `idea_memory` has 1 entry with D1 ID and resolved answer text
- `test_multiple_answers_sequential_ids` — answer 3 questions, assert D1, D2, D3
- `test_decision_title_uses_section_titles` — answer with targets_section="technical_constraints", assert title is "Technical Constraints & Dependencies"

### Prompt integration (4 tests)
- `test_confidence_prompt_contains_idea_memory` — assert "IdeaMemory" and decision text in prompt, assert formatted transcript NOT in prompt
- `test_question_prompt_contains_idea_memory` — same pattern
- `test_approaches_prompt_contains_idea_memory` — same pattern
- `test_section_prompt_contains_idea_memory` — same pattern

### File output (1 test)
- `test_idea_memory_written_to_disk` — after brainstorm with output_dir, `idea_memory.md` exists

### Pipeline integration (1 test)
- `test_cached_prefix_includes_idea_memory` — orchestrator includes IdeaMemory text in cached prefix when `idea_memory` key is provided

### TDD order
1. IdeaMemory data model + 5 tests
2. Move SECTION_TITLES to prompts.py
3. State fields + explore_context initialization + 2 tests
4. Decision capture in generate_question + 3 tests
5. Replace transcript with IdeaMemory in confidence prompt + 1 test
6. Replace transcript in 4 node prompts + 3 tests
7. Write IdeaMemory to disk + 1 test
8. CLI --idea-memory flag + orchestrator wiring + 1 test
9. Full test suite pass

### What NOT to build
- No automatic rejection entries from unselected options (add when correction flow ships)
- No LLM-generated decision summaries (the resolved answer IS the summary)
- No editing of IdeaMemory during brainstorm (immutable once written)
- No IdeaMemory versioning or history
- No changes to transcript data — still exists, just not in prompts
