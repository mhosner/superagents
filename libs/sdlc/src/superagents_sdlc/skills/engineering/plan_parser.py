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
