"""CodePlanner — TDD code plan generation skill.

Generates detailed code-level plans with file paths, function signatures,
and test cases following the RED-GREEN-REFACTOR cycle.
"""

from __future__ import annotations

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
- Tasks are ordered by dependency
- File paths are proposals — use realistic paths based on the tech spec
"""


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

        Args:
            context: Execution context with implementation plan and tech spec.

        Returns:
            Artifact pointing to the code plan output file.
        """
        params = context.parameters
        plan = params["implementation_plan"]
        spec = params["tech_spec"]

        prompt_parts = [
            f"## Implementation plan\n{plan}",
            f"## Technical specification\n{spec}",
        ]

        if "user_stories" in params:
            prompt_parts.append(f"## User stories\n{params['user_stories']}")
        if "prd" in params:
            prompt_parts.append(f"## PRD\n{params['prd']}")

        prompt = "\n\n".join(prompt_parts)
        response = await self._llm.generate(prompt, system=_SYSTEM_PROMPT)

        output_path = context.artifact_dir / "code_plan.md"
        output_path.write_text(response)

        return Artifact(
            path=str(output_path),
            artifact_type="code",
            metadata={"spec_source": "implementation_plan"},
        )
