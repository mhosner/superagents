"""CodePlanner — TDD code plan generation skill.

Generates detailed code-level plans with file paths, function signatures,
and test cases following the RED-GREEN-REFACTOR cycle.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from superagents_sdlc.skills.base import Artifact, BaseSkill, SkillValidationError

if TYPE_CHECKING:
    from superagents_sdlc.skills.base import SkillContext
    from superagents_sdlc.skills.llm import LLMClient

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
- Create one task per distinct component, endpoint, or module in the spec — never \
bundle multiple components into a single task
- Tasks are ordered by dependency
- File paths are proposals — use realistic paths based on the tech spec
"""


_REVISION_SYSTEM_PROMPT = """\
You are a senior developer revising an existing TDD implementation plan \
based on QA findings. You are EDITING an existing plan, NOT writing a new one.

## CRITICAL INSTRUCTION

Your input includes:
1. The previous code plan (the base document)
2. QA findings listing specific gaps

Your output must:
- PRESERVE every existing task from the previous plan that was NOT flagged \
by QA. Copy them through unchanged — same task numbers, same content, same \
verification steps.
- ADD new tasks to address each QA finding. Insert them at the correct \
position in the dependency order.
- MODIFY existing tasks only if a finding specifically says the task is \
incorrect or incomplete. In that case, keep the task number and update only \
the flagged part.
- MAINTAIN the same format: ### Task N: [Name], checkboxes, Run: commands, \
TDD order.
- NUMBER new tasks to continue from the last existing task number. If the \
previous plan had Tasks 1-12, new tasks start at Task 13.

## What NOT to do

- Do NOT rewrite tasks that QA did not flag.
- Do NOT renumber existing tasks.
- Do NOT change file paths, function signatures, or test commands in \
unflagged tasks.
- Do NOT drop tasks from the previous plan. Every previous task must appear \
in your output.
- Do NOT produce a "summary of changes" — produce the complete revised plan.

## Format

Output the COMPLETE plan — all preserved tasks plus all new/modified \
tasks — in the same Superpowers format as the original. The output must \
be a single, self-contained plan document that an executing agent can \
follow top to bottom.
"""


_PHASE_SYSTEM_PROMPT = """\
You are a senior developer creating a TDD implementation plan for ONE PHASE \
of a larger project. You are generating tasks for Phase {phase_number} of \
{total_phases}.

## Context

The phases before this one have already been planned — their tasks are \
provided below as context. You may reference functions, types, and test \
fixtures created in prior phases.

## Rules

- Generate tasks ONLY for the current phase's scope
- Continue task numbering from where the prior phase left off
- Reference prior phase artifacts by name when building on them
- Follow the same TDD format: failing test → implementation → passing verification
- Each task must have a ### Task N: heading, checkboxes, and Run: commands
- Each task should be 2-5 minutes of focused work
"""


def _extract_phases(impl_plan: str) -> list[str]:
    """Split an implementation plan into phases by header markers.

    Looks for ``## Phase N`` or ``### Phase N`` patterns. If no phase
    headers are found, returns the entire plan as a single phase.

    Args:
        impl_plan: Raw implementation plan text.

    Returns:
        List of phase strings, one per phase.
    """
    splits = re.split(r"(?=^#{2,3}\s+Phase\s+\d)", impl_plan, flags=re.MULTILINE)
    phases = [s.strip() for s in splits if s.strip()]
    return phases if len(phases) > 1 else [impl_plan]


class CodePlanner(BaseSkill):
    """Generate detailed TDD code plans."""

    def __init__(self, *, llm: LLMClient) -> None:
        """Initialize with an LLM client.

        Args:
            llm: LLM client for generating the code plan.
        """
        self._llm = llm
        super().__init__(
            name="code_planner",
            description=(
                "Generate detailed TDD code plans with file paths, "
                "function signatures, and test cases"
            ),
            required_context=["implementation_plan", "tech_spec"],
        )

    def validate(self, context: SkillContext) -> None:
        """Check that required context parameters are present.

        Args:
            context: Execution context to validate.

        Raises:
            SkillValidationError: If a required parameter is missing.
        """
        for key in self.required_context:
            if key not in context.parameters:
                msg = f"Missing required context parameter: {key}"
                raise SkillValidationError(msg)

    async def execute(self, context: SkillContext) -> Artifact:
        """Generate a TDD code plan from the implementation plan and tech spec.

        When the implementation plan contains multiple ``## Phase N`` sections,
        generates one plan per phase and concatenates them. Single-phase plans
        use a single LLM call.

        Args:
            context: Execution context with implementation plan and tech spec.

        Returns:
            Artifact pointing to the code plan output file.
        """
        params = context.parameters
        plan = params["implementation_plan"]
        phases = _extract_phases(plan)
        is_revision = "revision_findings" in params

        if len(phases) > 1 and is_revision and "previous_code" in params:
            response = await self._revise_phased(context, phases)
        elif len(phases) > 1 and not is_revision:
            response = await self._generate_phased(context, phases)
        else:
            response = await self._generate_single(context)

        output_path = context.artifact_dir / "code_plan.md"
        output_path.write_text(response)

        summary = (
            f"Generated {len(phases)}-phase TDD code plan."
            if len(phases) > 1
            else "Generated TDD code plan."
        )
        return Artifact(
            path=str(output_path),
            artifact_type="code",
            metadata={"spec_source": "implementation_plan", "summary": summary},
        )

    async def _generate_single(self, context: SkillContext) -> str:
        """Generate a single code plan (original behavior).

        Args:
            context: Execution context.

        Returns:
            Raw LLM response.
        """
        params = context.parameters
        plan = params["implementation_plan"]
        spec = params["tech_spec"]
        is_revision = "revision_findings" in params
        system = _REVISION_SYSTEM_PROMPT if is_revision else _SYSTEM_PROMPT

        prompt_parts = [
            f"## Implementation plan\n{plan}",
            f"## Technical specification\n{spec}",
        ]

        if "user_stories" in params:
            prompt_parts.append(f"## User stories\n{params['user_stories']}")
        if "prd" in params:
            prompt_parts.append(f"## PRD\n{params['prd']}")
        if "codebase_context" in params:
            prompt_parts.append(f"## Codebase Context\n{params['codebase_context']}")

        if is_revision and "previous_code" in params:
            prompt_parts.insert(
                0,
                f"## PREVIOUS PLAN (preserve all unflagged tasks)\n{params['previous_code']}",
            )
            prompt_parts.append(
                f"## QA FINDINGS (add tasks to address each)\n{params['revision_findings']}",
            )
        else:
            if "previous_code" in params:
                prompt_parts.append(f"## Previous code plan\n{params['previous_code']}")
            if "revision_findings" in params:
                prompt_parts.append(f"## Revision findings\n{params['revision_findings']}")

        prompt = "\n\n".join(prompt_parts)
        return await self._llm.generate(
            prompt, system=system, cached_prefix=context.cached_prefix,
        )

    async def _generate_phased(
        self, context: SkillContext, phases: list[str],
    ) -> str:
        """Generate a code plan one phase at a time.

        Each phase call includes the prior phases' output so later tasks
        can reference earlier functions and test fixtures.

        Args:
            context: Execution context.
            phases: List of phase strings from the implementation plan.

        Returns:
            Concatenated plan text.
        """
        params = context.parameters
        spec = params["tech_spec"]
        accumulated = ""

        for i, phase in enumerate(phases):
            prompt_parts = [
                f"## Current phase\n{phase}",
                f"## Technical specification\n{spec}",
            ]
            if "user_stories" in params:
                prompt_parts.append(f"## User stories\n{params['user_stories']}")
            if accumulated:
                prompt_parts.append(f"## Prior phases output\n{accumulated}")

            prompt = "\n\n".join(prompt_parts)
            phase_response = await self._llm.generate(
                prompt,
                system=_PHASE_SYSTEM_PROMPT.format(
                    phase_number=i + 1, total_phases=len(phases),
                ),
                cached_prefix=context.cached_prefix,
            )
            accumulated = f"{accumulated}\n\n{phase_response}".strip()

        return accumulated

    async def _revise_phased(
        self, context: SkillContext, phases: list[str],
    ) -> str:
        """Revise only the phases containing flagged tasks.

        Splits the previous code plan output by ``### Task`` headers to
        determine which tasks belong to which phase. Phases with flagged
        tasks are regenerated; unflagged phases are preserved verbatim.

        Args:
            context: Execution context with revision_findings and previous_code.
            phases: List of phase strings from the implementation plan.

        Returns:
            Concatenated revised plan text.
        """
        params = context.parameters
        findings = params["revision_findings"]
        previous = params["previous_code"]

        # Determine which task numbers are flagged
        flagged = set()
        for match in re.finditer(r"Task\s+(\d+)", findings):
            flagged.add(int(match.group(1)))

        # Split previous output into task blocks and map to phase indices
        task_blocks = re.split(r"(?=^### Task\s+\d+)", previous, flags=re.MULTILINE)
        task_blocks = [b for b in task_blocks if b.strip()]

        # Assign tasks to phases based on position
        tasks_per_phase = max(1, len(task_blocks) // len(phases))
        phase_tasks: dict[int, list[str]] = {}
        phase_flagged: dict[int, bool] = {}
        for idx, block in enumerate(task_blocks):
            phase_idx = min(idx // tasks_per_phase, len(phases) - 1)
            phase_tasks.setdefault(phase_idx, []).append(block)
            task_match = re.search(r"### Task\s+(\d+)", block)
            if task_match and int(task_match.group(1)) in flagged:
                phase_flagged[phase_idx] = True

        # Build output — preserve unflagged, regenerate flagged
        parts = []
        for i, phase in enumerate(phases):
            if phase_flagged.get(i):
                phase_content = "".join(phase_tasks.get(i, []))
                prompt_parts = [
                    f"## PREVIOUS PHASE (revise flagged tasks)\n{phase_content}",
                    f"## Current phase spec\n{phase}",
                    f"## Technical specification\n{params['tech_spec']}",
                    f"## QA FINDINGS\n{findings}",
                ]
                if parts:
                    prompt_parts.append(f"## Prior phases\n{''.join(parts)}")
                prompt = "\n\n".join(prompt_parts)
                revised = await self._llm.generate(
                    prompt,
                    system=_REVISION_SYSTEM_PROMPT,
                    cached_prefix=context.cached_prefix,
                )
                parts.append(revised)
            else:
                parts.append("".join(phase_tasks.get(i, [])))

        return "\n\n".join(p.strip() for p in parts if p.strip())
