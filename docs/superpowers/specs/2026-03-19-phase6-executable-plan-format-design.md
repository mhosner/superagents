# Phase 6: Executable Plan Format — Design Spec

**Date:** 2026-03-19

**Goal:** Make the CodePlanner's output directly executable via
`superpowers:executing-plans` by mandating the Superpowers plan format,
with a parser utility to prove the output is machine-consumable and
structured QA input derived from parsed plan data.

**Dependencies:** Phases 1-5 must be complete (147 tests passing).

**Spec author:** Claude (brainstormed with human)

---

## Strategic Context

The pipeline (PM → Architect → Developer → QA) produces plans, not code.
The Developer's CodePlanner generates a `code_plan.md` that describes what
to build, but in free-form markdown that requires a human to interpret and
execute. Phase 6 closes this gap by making the code plan follow the
Superpowers plan format — task headers, checkboxes, run commands — so an
executing agent can follow it mechanically.

The format does the work. No new skills, no new personas, no code generation.
File paths in the plan are *proposed*, not grounded to existing files. The
executing agent (Claude Code running `superpowers:executing-plans`) adapts
to the actual codebase at execution time.

---

## Design Decisions (Final)

### D1: CodePlanner Output Format — Superpowers Plan Structure

The CodePlanner's system prompt is updated to mandate:
- Plan header with Goal/Architecture/Tech Stack
- Preamble noting file paths are proposed, not existing
- `### Task N: [Name]` headers
- `- [ ]` checkboxes for every step
- `Run:` lines for executable commands
- TDD ordering as the default pattern (test first, implement, verify)
- Variable step count per task (not prescriptive 5-step cycle)

The `execute()` method is unchanged — prompt composition, LLM call, write
file, return Artifact. Only the system prompt changes.

### D2: Plan Parser — Minimal Utility for Structured Extraction

A lightweight parser at `skills/engineering/plan_parser.py` with:
- `PlanTask` dataclass: `name`, `checkboxes`, `has_run_command`
- `extract_tasks(plan_text) -> list[PlanTask]`: regex-based extraction
- `summarize_plan(tasks) -> str`: formatted summary string

**Error handling:** Returns empty list on garbage input (no task headers
found). This is intentional — the parser feeds into LLM prompts where
"0 tasks extracted" is a meaningful signal that triggers compliance failure.
A crash would create orphaned persona spans. If Harbor eval later needs
strict parsing, add `strict=True` parameter (same pattern as StubLLMClient).

**Run command detection:** Checks for `"Run:"` substring anywhere in any
line within a task section, not just at line start. The Superpowers format
may place `Run:` on its own line, indented, or inline after a checkbox step.

### D3: SpecComplianceChecker — Structured Preamble + Raw Text

The compliance checker's `execute()` is updated to parse the code plan
before composing the LLM prompt. The prompt now contains:

1. **Structured preamble** (from `summarize_plan`):
   ```
   ## Plan structure analysis
   Tasks extracted: 12
   Tasks with test commands: 8
   Tasks without test commands: 4 (Task 3, Task 7, Task 9, Task 12)
   Total steps: 47
   ```

2. **Raw plan text** (unchanged):
   ```
   ## Code plan
   [full plan markdown]
   ```

3. **User stories, tech spec, etc.** (unchanged)

The LLM gets quantitative data for anchoring ("4 tasks lack test commands")
plus full text for line-by-line analysis. The system prompt is unchanged.

### D4: Preamble Is Documentation, Not Machine Trigger

The plan header includes:
```
> **For agentic workers:** Use superpowers:executing-plans to implement
> this plan task-by-task.
> **Note:** File paths are proposed, not existing. The executing agent
> adapts to the actual codebase.
```

This is human-readable documentation. The `superpowers:executing-plans`
skill is invoked by a human or orchestrating agent who decides to run the
plan — it does not auto-discover plans via text markers.

---

## Module Structure

### New Files

| File | Responsibility |
|------|---------------|
| `src/superagents_sdlc/skills/engineering/plan_parser.py` | PlanTask dataclass, extract_tasks, summarize_plan |
| `tests/unit_tests/test_skills/test_engineering/test_plan_parser.py` | Parser tests |

### Modified Files

| File | Change |
|------|--------|
| `src/superagents_sdlc/skills/engineering/code_planner.py` | Replace `_SYSTEM_PROMPT` with Superpowers plan format |
| `src/superagents_sdlc/skills/qa/spec_compliance_checker.py` | Parse code plan + prepend structured summary in execute() |
| `src/superagents_sdlc/skills/engineering/__init__.py` | Add PlanTask, extract_tasks, summarize_plan re-exports |
| `tests/unit_tests/test_skills/test_engineering/test_code_planner.py` | Update stub response + assertions for new format |
| `tests/unit_tests/test_skills/test_qa/test_spec_compliance_checker.py` | Add structured input tests |

---

## Detailed Behavior

### CodePlanner System Prompt (code_planner.py)

Replace `_SYSTEM_PROMPT` with:

```python
_SYSTEM_PROMPT = """\
You are a senior developer producing an executable TDD implementation plan \
in Superpowers format. The plan must be directly consumable by an executing \
agent via superpowers:executing-plans.

## Required plan structure

Start with this header block:

```markdown
# [Feature] Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement \
this plan task-by-task.
> **Note:** File paths are proposed, not existing. The executing agent \
adapts to the actual codebase.

**Goal:** [one sentence from the tech spec]
**Architecture:** [2-3 sentences from the tech spec]
**Tech Stack:** [from the tech spec]

---
```

## Task format

Each task uses this structure:

```markdown
### Task N: [Component Name]

**Files:**
- Create: `proposed/path/to/file.py`
- Test: `tests/proposed/path/test_file.py`

- [ ] **Step 1: Write the failing test**
[code block with test]

- [ ] **Step 2: Run test to verify it fails**
Run: `pytest tests/path/test_file.py::test_name -v`
Expected: FAIL

- [ ] **Step 3: Write minimal implementation**
[code block with implementation]

- [ ] **Step 4: Run test to verify it passes**
Run: `pytest tests/path/test_file.py::test_name -v`
Expected: PASS
```

## Rules

- Every step gets a `- [ ]` checkbox
- Test commands use `Run:` prefix
- TDD order is the default (test → implement → verify) but tasks may \
vary in step count — config changes, refactors, and integration tasks \
may have fewer or more steps
- Each task should be 2-5 minutes of focused work
- Tasks are ordered by dependency
- File paths are proposals — prefix with `proposed/` or use realistic \
paths based on the tech spec's architecture
"""
```

The `execute()` method is unchanged. Only the system prompt changes.

### Plan Parser (skills/engineering/plan_parser.py)

```python
"""Plan parser — extract structured task data from Superpowers format plans."""

from __future__ import annotations

import re
from dataclasses import dataclass

_TASK_HEADER_RE = re.compile(r"^### Task \d+:\s*(.+)$", re.MULTILINE)
_CHECKBOX_RE = re.compile(r"^- \[[ x]\]", re.MULTILINE)
_RUN_COMMAND_RE = re.compile(r"Run:", re.MULTILINE)


@dataclass
class PlanTask:
    """A single task extracted from a Superpowers format plan.

    Attributes:
        name: Task name from the header (e.g., "Create DarkModeToggle").
        checkboxes: Count of checkbox steps (both unchecked and checked).
        has_run_command: True if any line contains a Run: command.
    """

    name: str
    checkboxes: int
    has_run_command: bool
```

**`extract_tasks(plan_text: str) -> list[PlanTask]`:**

Split on `### Task \d+:` headers. For each section between headers:
- Extract task name from the header match group
- Count `- [ ]` and `- [x]` patterns
- Check for `Run:` anywhere in the section

Return empty list if no headers found (garbage input).

**`summarize_plan(tasks: list[PlanTask]) -> str`:**

Produce a formatted string:
```
## Plan structure analysis
Tasks extracted: {len(tasks)}
Tasks with test commands: {with_run}
Tasks without test commands: {without_run} ({names})
Total steps: {total_checkboxes}
```

When all tasks have run commands, omit the parenthetical list:
```
Tasks without test commands: 0
```

If `tasks` is empty, output:
```
## Plan structure analysis
Tasks extracted: 0
```

**Algorithm note for `extract_tasks`:** Use `re.finditer` on `_TASK_HEADER_RE`
to find header positions and names. Slice `plan_text` between consecutive header
positions to get each task's body. The text before the first header is the plan
preamble — skip it. For each body section, count `_CHECKBOX_RE` matches and
check for `_RUN_COMMAND_RE`.

### SpecComplianceChecker Change (spec_compliance_checker.py)

Add import:
```python
from superagents_sdlc.skills.engineering.plan_parser import extract_tasks, summarize_plan
```

Update `execute()` — before composing prompt_parts, parse and summarize:

```python
    async def execute(self, context: SkillContext) -> Artifact:
        params = context.parameters
        code_plan = params["code_plan"]

        # Parse plan for structured analysis
        tasks = extract_tasks(code_plan)
        summary = summarize_plan(tasks)

        prompt_parts = [
            summary,
            f"## Code plan\n{code_plan}",
            f"## User stories\n{params['user_stories']}",
            f"## Technical specification\n{params['tech_spec']}",
        ]
        # ... rest unchanged (optional params, LLM call, write file)
```

The structured summary appears first in the prompt, followed by the raw
plan text, followed by user stories and tech spec. The system prompt is
unchanged — it already instructs gap analysis and coverage checking.

### Engineering __init__.py Re-exports

Add to `src/superagents_sdlc/skills/engineering/__init__.py`:

```python
from superagents_sdlc.skills.engineering.plan_parser import (
    PlanTask,
    extract_tasks,
    summarize_plan,
)
```

And update `__all__` to include `"PlanTask"`, `"extract_tasks"`,
`"summarize_plan"`.

### CodePlanner Test Fixture Update (test_code_planner.py)

The stub response in `_make_stub()` must produce Superpowers format so
existing tests pass against the new system prompt. Updated response:

```python
def _make_stub() -> StubLLMClient:
    return StubLLMClient(
        responses={
            "## Implementation plan\n": (
                "# Dark Mode Implementation Plan\n\n"
                "> **For agentic workers:** Use superpowers:executing-plans\n"
                "> **Note:** File paths are proposed.\n\n"
                "**Goal:** Add dark mode toggle\n"
                "**Architecture:** React component with CSS variables\n"
                "**Tech Stack:** Python, pytest\n\n"
                "---\n\n"
                "### Task 1: Create DarkModeToggle\n\n"
                "**Files:**\n"
                "- Create: `src/components/toggle.py`\n"
                "- Test: `tests/test_toggle.py`\n\n"
                "- [ ] **Step 1: Write the failing test**\n"
                "```python\n"
                "def test_toggle_switches_theme():\n"
                "    assert toggle() == 'dark'\n"
                "```\n\n"
                "- [ ] **Step 2: Run test**\n"
                "Run: `pytest tests/test_toggle.py -v`\n\n"
                "- [ ] **Step 3: Write implementation**\n"
                "```python\n"
                "def toggle(): return 'dark'\n"
                "```\n\n"
                "- [ ] **Step 4: Verify passes**\n"
                "Run: `pytest tests/test_toggle.py -v`\n"
            ),
        }
    )
```

Existing test assertions (`"Create data model" in prompt`,
`"REST API" in prompt`) still pass because they check the *prompt* sent
to the LLM, not the response. Only the response format changes.

**Note: latent bug fix.** The old stub key `"implementation_plan"` (underscore)
never actually matched the prompt string `"## Implementation plan\n"` (space).
Tests passed only because StubLLMClient returns empty string in non-strict mode
and no test asserted on response content. The new key `"## Implementation plan\n"`
fixes this. The round-trip test (test 8) depends on getting a non-empty response,
so this fix is essential.

---

## Test Plan — 8 New Tests

### test_plan_parser.py (5 tests)

1. `test_extract_tasks_from_valid_plan` — multi-task Superpowers plan →
   returns list of PlanTask with correct names
2. `test_extract_tasks_counts_checkboxes` — `- [ ]` and `- [x]` both
   counted in checkboxes field
3. `test_extract_tasks_detects_run_command` — task with `Run:` anywhere
   in section → `has_run_command=True`; task without → `False`
4. `test_extract_tasks_returns_empty_on_garbage` — random text → `[]`
5. `test_summarize_plan_output` — verify formatted string contains task
   count, "Tasks with test commands", and lists tasks without run commands
   by name

### test_spec_compliance_checker.py (2 new tests)

6. `test_compliance_prompt_includes_plan_summary` — verify prompt contains
   "Tasks extracted:" and "Tasks with test commands:" strings
7. `test_compliance_handles_unparseable_plan` — code_plan is garbage →
   summary shows "Tasks extracted: 0" → checker still runs without crash

### test_code_planner.py (0 new tests, 1 fixture update)

Existing `_make_stub()` response updated to Superpowers format. Existing
test assertions are prompt-side (check what was sent to LLM, not the
response) so they pass without modification.

### Round-trip integration test (1 new test in test_code_planner.py)

8. `test_code_planner_output_parseable_as_plan` — execute CodePlanner →
   read the output file → `extract_tasks()` → assert non-empty list with
   correct task name and `has_run_command=True`

**Total: 8 new tests. Running total: 147 + 8 = 155.**

---

## Implementation Order

1. Plan parser + tests (5 tests) — no dependencies on other changes
2. CodePlanner system prompt + fixture update + round-trip test (1 test)
3. SpecComplianceChecker structured input + tests (2 tests)
4. Engineering __init__.py re-exports + final verification
