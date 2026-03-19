# Phase 6: Executable Plan Format — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the CodePlanner's output directly executable via superpowers:executing-plans by mandating the Superpowers plan format, with a parser utility and structured QA input.

**Architecture:** Update CodePlanner system prompt, add plan_parser.py utility, update SpecComplianceChecker to prepend structured analysis before raw plan text in LLM prompt.

**Tech Stack:** Python 3.12, Pydantic v2, pytest (asyncio_mode="auto"), ruff, regex

**Spec:** `docs/superpowers/specs/2026-03-19-phase6-executable-plan-format-design.md`

**Working directory:** `libs/sdlc/` (all paths relative to this unless stated otherwise)

**Run tests with:** `.venv/bin/python -m pytest tests/ -v`

**Run lint with:** `.venv/bin/ruff check src/ tests/ && .venv/bin/ruff format --check src/ tests/`

---

## File Map

### New files

| File | Responsibility |
|------|---------------|
| `src/superagents_sdlc/skills/engineering/plan_parser.py` | PlanTask dataclass, extract_tasks(), summarize_plan() |
| `tests/unit_tests/test_skills/test_engineering/test_plan_parser.py` | Parser tests (5) |

### Modified files

| File | Change |
|------|--------|
| `src/superagents_sdlc/skills/engineering/code_planner.py:17-34` | Replace `_SYSTEM_PROMPT` |
| `src/superagents_sdlc/skills/qa/spec_compliance_checker.py:82-104` | Add parse + summarize before prompt composition |
| `src/superagents_sdlc/skills/engineering/__init__.py:1-7` | Add parser re-exports |
| `tests/unit_tests/test_skills/test_engineering/test_code_planner.py:17-26` | Update stub response + add round-trip test |
| `tests/unit_tests/test_skills/test_qa/test_spec_compliance_checker.py` | Add 2 structured input tests |

---

## Task 1: Plan parser utility

**Files:**
- Create: `src/superagents_sdlc/skills/engineering/plan_parser.py`
- Create: `tests/unit_tests/test_skills/test_engineering/test_plan_parser.py`

- [ ] **Step 1: Write the 5 failing tests**

Create `tests/unit_tests/test_skills/test_engineering/test_plan_parser.py`:

```python
"""Tests for plan parser utility."""

from __future__ import annotations

from superagents_sdlc.skills.engineering.plan_parser import (
    PlanTask,
    extract_tasks,
    summarize_plan,
)

_VALID_PLAN = """\
# Dark Mode Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans

**Goal:** Add dark mode
**Tech Stack:** Python, pytest

---

### Task 1: Create toggle component

**Files:**
- Create: `src/toggle.py`

- [ ] **Step 1: Write failing test**
```python
def test_toggle():
    assert toggle() == "dark"
```

- [ ] **Step 2: Run test**
Run: `pytest tests/test_toggle.py -v`

- [ ] **Step 3: Implement**
```python
def toggle():
    return "dark"
```

- [x] **Step 4: Verify**
Run: `pytest tests/test_toggle.py -v`

### Task 2: Add persistence

**Files:**
- Create: `src/persist.py`

- [ ] **Step 1: Write config file**
No test needed for config.

- [ ] **Step 2: Write persistence layer**
"""

_PLAN_NO_COLON = """\
### Task 1 Create toggle

- [ ] **Step 1: Write test**
Run: `pytest -v`
"""


def test_extract_tasks_from_valid_plan():
    tasks = extract_tasks(_VALID_PLAN)
    assert len(tasks) == 2
    assert tasks[0].name == "Create toggle component"
    assert tasks[1].name == "Add persistence"


def test_extract_tasks_counts_checkboxes():
    tasks = extract_tasks(_VALID_PLAN)
    # Task 1: 4 checkboxes (3 unchecked + 1 checked)
    assert tasks[0].checkboxes == 4
    # Task 2: 2 checkboxes
    assert tasks[1].checkboxes == 2


def test_extract_tasks_detects_run_command():
    tasks = extract_tasks(_VALID_PLAN)
    # Task 1 has Run: lines
    assert tasks[0].has_run_command is True
    # Task 2 has no Run: lines
    assert tasks[1].has_run_command is False


def test_extract_tasks_returns_empty_on_garbage():
    assert extract_tasks("just some random text\nno headers here") == []
    assert extract_tasks("") == []


def test_extract_tasks_handles_no_colon():
    tasks = extract_tasks(_PLAN_NO_COLON)
    assert len(tasks) == 1
    assert tasks[0].name == "Create toggle"
    assert tasks[0].has_run_command is True


def test_summarize_plan_output():
    tasks = [
        PlanTask(name="Toggle", checkboxes=4, has_run_command=True),
        PlanTask(name="Persist", checkboxes=2, has_run_command=False),
        PlanTask(name="Config", checkboxes=1, has_run_command=False),
    ]
    summary = summarize_plan(tasks)
    assert "Tasks extracted: 3" in summary
    assert "Tasks with test commands: 1" in summary
    assert "Tasks without test commands: 2" in summary
    assert "Persist" in summary
    assert "Config" in summary
    assert "Total steps: 7" in summary
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit_tests/test_skills/test_engineering/test_plan_parser.py -v`

Expected: FAIL — `ModuleNotFoundError: No module named 'superagents_sdlc.skills.engineering.plan_parser'`

- [ ] **Step 3: Implement plan_parser.py**

Create `src/superagents_sdlc/skills/engineering/plan_parser.py`:

```python
"""Plan parser — extract structured task data from Superpowers format plans."""

from __future__ import annotations

import re
from dataclasses import dataclass

# Colon is optional — defensive against LLM dropping it
_TASK_HEADER_RE = re.compile(r"^### Task \d+:?\s*(.+)$", re.MULTILINE)
_CHECKBOX_RE = re.compile(r"^- \[[ x]\]", re.MULTILINE)
_RUN_COMMAND_RE = re.compile(r"Run:")


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


def extract_tasks(plan_text: str) -> list[PlanTask]:
    """Extract structured task data from a Superpowers format plan.

    Splits on ``### Task N:`` headers and analyzes each section for
    checkboxes and run commands. Returns empty list on garbage input
    (no headers found).

    Args:
        plan_text: Raw plan markdown text.

    Returns:
        List of extracted tasks, or empty list if no valid headers found.
    """
    headers = list(_TASK_HEADER_RE.finditer(plan_text))
    if not headers:
        return []

    tasks: list[PlanTask] = []
    for i, match in enumerate(headers):
        start = match.end()
        end = headers[i + 1].start() if i + 1 < len(headers) else len(plan_text)
        body = plan_text[start:end]

        name = match.group(1).strip() or "Unnamed"
        checkboxes = len(_CHECKBOX_RE.findall(body))
        has_run = bool(_RUN_COMMAND_RE.search(body))

        tasks.append(PlanTask(name=name, checkboxes=checkboxes, has_run_command=has_run))

    return tasks


def summarize_plan(tasks: list[PlanTask]) -> str:
    """Produce a structured summary of plan tasks for LLM prompts.

    Args:
        tasks: List of extracted plan tasks.

    Returns:
        Formatted summary string with task counts and coverage stats.
    """
    if not tasks:
        return "## Plan structure analysis\nTasks extracted: 0"

    with_run = sum(1 for t in tasks if t.has_run_command)
    without_run = len(tasks) - with_run
    total_steps = sum(t.checkboxes for t in tasks)

    lines = [
        "## Plan structure analysis",
        f"Tasks extracted: {len(tasks)}",
        f"Tasks with test commands: {with_run}",
    ]

    if without_run > 0:
        names = ", ".join(t.name for t in tasks if not t.has_run_command)
        lines.append(f"Tasks without test commands: {without_run} ({names})")
    else:
        lines.append("Tasks without test commands: 0")

    lines.append(f"Total steps: {total_steps}")
    return "\n".join(lines)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit_tests/test_skills/test_engineering/test_plan_parser.py -v`

Expected: All 6 pass.

- [ ] **Step 5: Lint and commit**

```bash
.venv/bin/ruff check src/superagents_sdlc/skills/engineering/plan_parser.py tests/unit_tests/test_skills/test_engineering/test_plan_parser.py
git add src/superagents_sdlc/skills/engineering/plan_parser.py tests/unit_tests/test_skills/test_engineering/test_plan_parser.py
git commit -m "feat(sdlc): add plan parser utility for Superpowers format extraction"
```

---

## Task 2: CodePlanner system prompt + test fixture update + round-trip test

**Files:**
- Modify: `src/superagents_sdlc/skills/engineering/code_planner.py:17-34`
- Modify: `tests/unit_tests/test_skills/test_engineering/test_code_planner.py:17-26`

- [ ] **Step 1: Update the stub response in test_code_planner.py**

Replace `_make_stub()` (lines 17-26) with:

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

Note: The old key `"implementation_plan"` (underscore) never matched the prompt
`"## Implementation plan\n"` (space). Tests passed because StubLLMClient returns
empty string in non-strict mode. The new key `"## Implementation plan\n"` fixes
this latent bug. The round-trip test depends on getting a non-empty response.

- [ ] **Step 2: Add the round-trip test**

Add to the end of `tests/unit_tests/test_skills/test_engineering/test_code_planner.py`:

```python
from superagents_sdlc.skills.engineering.plan_parser import extract_tasks


async def test_code_planner_output_parseable_as_plan(tmp_path):
    stub = _make_stub()
    skill = CodePlanner(llm=stub)
    context = _make_context(tmp_path)

    artifact = await skill.execute(context)

    plan_text = (tmp_path / "code_plan.md").read_text()
    tasks = extract_tasks(plan_text)
    assert len(tasks) >= 1
    assert tasks[0].name == "Create DarkModeToggle"
    assert tasks[0].has_run_command is True
    assert tasks[0].checkboxes == 4
```

- [ ] **Step 3: Run existing tests to verify fixture update doesn't break them**

Run: `.venv/bin/python -m pytest tests/unit_tests/test_skills/test_engineering/test_code_planner.py -v`

Expected: All 5 pass (4 existing + 1 new). Existing tests check prompts (what was
sent to LLM), not responses. The fixture only changes the response.

- [ ] **Step 4: Replace the system prompt in code_planner.py**

In `src/superagents_sdlc/skills/engineering/code_planner.py`, replace lines 17-34
(the entire `_SYSTEM_PROMPT` string) with:

```python
_SYSTEM_PROMPT = """\
You are a senior developer producing an executable TDD implementation plan \
in Superpowers format. The plan must be directly consumable by an executing \
agent via superpowers:executing-plans.

## Required plan structure

Start with this header block:

```
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

```
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
- TDD order is the default (test, implement, verify) but tasks may vary in \
step count — config changes, refactors, and integration tasks may have fewer \
or more steps
- Each task should be 2-5 minutes of focused work
- Tasks are ordered by dependency
- File paths are proposals — use realistic paths based on the tech spec
"""
```

- [ ] **Step 5: Run all tests to verify no regressions**

Run: `.venv/bin/python -m pytest tests/unit_tests/test_skills/test_engineering/ -v`

Expected: All tests pass (existing + new). The system prompt change doesn't affect
test behavior — tests verify prompt inputs and artifact metadata, not LLM response
quality.

- [ ] **Step 6: Lint and commit**

```bash
.venv/bin/ruff check src/superagents_sdlc/skills/engineering/code_planner.py tests/unit_tests/test_skills/test_engineering/test_code_planner.py
git add src/superagents_sdlc/skills/engineering/code_planner.py tests/unit_tests/test_skills/test_engineering/test_code_planner.py
git commit -m "feat(sdlc): update CodePlanner to produce Superpowers plan format"
```

---

## Task 3: SpecComplianceChecker structured input

**Files:**
- Modify: `src/superagents_sdlc/skills/qa/spec_compliance_checker.py:1-114`
- Modify: `tests/unit_tests/test_skills/test_qa/test_spec_compliance_checker.py`

- [ ] **Step 1: Write the 2 failing tests**

Add to the end of `tests/unit_tests/test_skills/test_qa/test_spec_compliance_checker.py`:

```python
async def test_compliance_prompt_includes_plan_summary(tmp_path):
    stub = _make_stub()
    skill = SpecComplianceChecker(llm=stub)
    # Use a parseable code plan so the summary has real data
    context = SkillContext(
        artifact_dir=tmp_path,
        parameters={
            "code_plan": (
                "### Task 1: Create toggle\n\n"
                "- [ ] **Step 1: Write test**\n"
                "Run: `pytest -v`\n\n"
                "- [ ] **Step 2: Implement**\n"
            ),
            "user_stories": "As a PM, I want dark mode",
            "tech_spec": "# Tech Spec\nREST API",
        },
        trace_id="trace-1",
    )

    await skill.execute(context)

    prompt = stub.calls[0][0]
    assert "Tasks extracted: 1" in prompt
    assert "Tasks with test commands: 1" in prompt
    assert "Total steps: 2" in prompt
    # Raw plan text is still present after the summary
    assert "### Task 1: Create toggle" in prompt


async def test_compliance_handles_unparseable_plan(tmp_path):
    stub = _make_stub()
    skill = SpecComplianceChecker(llm=stub)
    context = SkillContext(
        artifact_dir=tmp_path,
        parameters={
            "code_plan": "This is not a valid plan at all.",
            "user_stories": "As a PM, I want dark mode",
            "tech_spec": "# Tech Spec\nREST API",
        },
        trace_id="trace-1",
    )

    artifact = await skill.execute(context)

    # Should not crash — parser returns empty list
    assert artifact.artifact_type == "compliance_report"
    prompt = stub.calls[0][0]
    assert "Tasks extracted: 0" in prompt
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit_tests/test_skills/test_qa/test_spec_compliance_checker.py::test_compliance_prompt_includes_plan_summary -v`

Expected: FAIL — `AssertionError: assert "Tasks extracted: 1" in prompt`
(the current code doesn't add a plan summary to the prompt)

- [ ] **Step 3: Update spec_compliance_checker.py**

In `src/superagents_sdlc/skills/qa/spec_compliance_checker.py`:

1. Add import after the existing `from superagents_sdlc.skills.base import ...` line:

```python
from superagents_sdlc.skills.engineering.plan_parser import extract_tasks, summarize_plan
```

2. Replace the `execute()` method body (lines 91-114) with:

```python
    async def execute(self, context: SkillContext) -> Artifact:
        """Run compliance check against the code plan.

        Parses the code plan for structured task data, then composes
        a prompt with both quantitative summary and raw plan text.

        Args:
            context: Execution context with code plan, user stories, and tech spec.

        Returns:
            Artifact pointing to the compliance report.
        """
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

        if "implementation_plan" in params:
            prompt_parts.append(f"## Implementation plan\n{params['implementation_plan']}")
        if "prd" in params:
            prompt_parts.append(f"## PRD\n{params['prd']}")

        prompt = "\n\n".join(prompt_parts)
        response = await self._llm.generate(prompt, system=_SYSTEM_PROMPT)

        output_path = context.artifact_dir / "compliance_report.md"
        output_path.write_text(response)

        return Artifact(
            path=str(output_path),
            artifact_type="compliance_report",
            metadata={"framework": "spec_compliance"},
        )
```

- [ ] **Step 4: Run ALL compliance checker tests**

Run: `.venv/bin/python -m pytest tests/unit_tests/test_skills/test_qa/test_spec_compliance_checker.py -v`

Expected: All 7 pass (5 existing + 2 new). Existing tests still pass because:
- `test_compliance_execute_includes_context_in_prompt` checks for "DarkModeToggle",
  "dark mode", "REST API" — all still in the prompt (raw plan text is preserved)
- `test_compliance_execute_writes_artifact` checks file existence and artifact type —
  unchanged
- The stub key `"## Code plan\n"` still matches because raw plan text follows the
  summary in the prompt

- [ ] **Step 5: Lint and commit**

```bash
.venv/bin/ruff check src/superagents_sdlc/skills/qa/spec_compliance_checker.py tests/unit_tests/test_skills/test_qa/test_spec_compliance_checker.py
git add src/superagents_sdlc/skills/qa/spec_compliance_checker.py tests/unit_tests/test_skills/test_qa/test_spec_compliance_checker.py
git commit -m "feat(sdlc): add structured plan analysis to SpecComplianceChecker"
```

---

## Task 4: Re-exports + final verification

**Files:**
- Modify: `src/superagents_sdlc/skills/engineering/__init__.py`

- [ ] **Step 1: Update engineering __init__.py**

Replace the contents of `src/superagents_sdlc/skills/engineering/__init__.py` with:

```python
"""Engineering skills — technical specification and planning skills."""

from superagents_sdlc.skills.engineering.code_planner import CodePlanner
from superagents_sdlc.skills.engineering.implementation_planner import ImplementationPlanner
from superagents_sdlc.skills.engineering.plan_parser import (
    PlanTask,
    extract_tasks,
    summarize_plan,
)
from superagents_sdlc.skills.engineering.tech_spec_writer import TechSpecWriter

__all__ = [
    "CodePlanner",
    "ImplementationPlanner",
    "PlanTask",
    "TechSpecWriter",
    "extract_tasks",
    "summarize_plan",
]
```

- [ ] **Step 2: Run full SDLC test suite**

Run: `.venv/bin/python -m pytest tests/ -v`

Expected: All 156 tests pass (147 existing + 9 new).

- [ ] **Step 3: Run Phase 1 telemetry tests (regression check)**

Run: `cd ../superagents && .venv/bin/python -m pytest tests/unit_tests/test_telemetry/ -v`

Expected: All 15 pass.

- [ ] **Step 4: Full lint + format check**

Run: `cd /home/matt/coding/superagents/libs/sdlc && .venv/bin/ruff check src/ tests/ && .venv/bin/ruff format --check src/ tests/`

Fix any issues.

- [ ] **Step 5: Commit**

```bash
git add src/superagents_sdlc/skills/engineering/__init__.py
git commit -m "feat(sdlc): add Phase 6 re-exports for plan parser"
```
