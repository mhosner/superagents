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
    assert tasks[0].checkboxes == 4
    assert tasks[1].checkboxes == 2


def test_extract_tasks_detects_run_command():
    tasks = extract_tasks(_VALID_PLAN)
    assert tasks[0].has_run_command is True
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
