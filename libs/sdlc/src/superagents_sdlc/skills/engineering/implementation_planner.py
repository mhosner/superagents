"""ImplementationPlanner — ordered task breakdown from technical specs.

Breaks technical specs into ordered implementation tasks with file paths,
dependencies, and verification steps aligned with Superpowers methodology.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from superagents_sdlc.skills.base import Artifact, BaseSkill, SkillValidationError

if TYPE_CHECKING:
    from superagents_sdlc.skills.base import SkillContext
    from superagents_sdlc.skills.llm import LLMClient

_SYSTEM_PROMPT = """\
You are a senior software architect breaking a technical spec into an \
ordered implementation plan following the Superpowers methodology.

## Task structure requirements

Each task should be 2-5 minutes of focused work. For each task provide:
- **Description**: What to build or change
- **File paths**: Exact files to create or modify
- **Dependencies**: Which tasks must complete first
- **Verification**: How to prove this task is done (test command, assertion)

## Output structure

1. **Task list** — Ordered by dependency, grouped by component
2. **Critical path** — Which tasks are on the longest dependency chain
3. **Integration points** — Where separately-built components connect
"""


class ImplementationPlanner(BaseSkill):
    """Break technical specs into ordered implementation tasks."""

    def __init__(self, *, llm: LLMClient) -> None:
        """Initialize with an LLM client.

        Args:
            llm: LLM client for generating the implementation plan.
        """
        self._llm = llm
        super().__init__(
            name="implementation_planner",
            description=(
                "Break technical specs into ordered implementation tasks "
                "with file paths, dependencies, and verification steps"
            ),
            required_context=["tech_spec", "user_stories"],
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
        """Generate an implementation plan from the tech spec.

        Args:
            context: Execution context with tech spec and user stories.

        Returns:
            Artifact pointing to the implementation plan output file.
        """
        params = context.parameters
        spec = params["tech_spec"]
        stories = params["user_stories"]

        prompt_parts = [
            f"## Technical specification\n{spec}",
            f"## User stories to implement\n{stories}",
        ]

        if "prd" in params:
            prompt_parts.append(f"## PRD\n{params['prd']}")
        if "product_context" in params:
            prompt_parts.append(f"## Product context\n{params['product_context']}")
        if "codebase_context" in params:
            prompt_parts.append(f"## Codebase Context\n{params['codebase_context']}")

        if "previous_implementation_plan" in params:
            prev = params["previous_implementation_plan"]
            prompt_parts.append(f"## Previous implementation plan\n{prev}")
        if "revision_findings" in params:
            prompt_parts.append(f"## Revision findings\n{params['revision_findings']}")

        prompt = "\n\n".join(prompt_parts)
        response = await self._llm.generate(prompt, system=_SYSTEM_PROMPT)

        output_path = context.artifact_dir / "implementation_plan.md"
        output_path.write_text(response)

        lines = [line.strip() for line in response.splitlines() if line.strip()]
        task_count = sum(1 for line in lines if line and line[0].isdigit())

        return Artifact(
            path=str(output_path),
            artifact_type="implementation_plan",
            metadata={"task_count": str(task_count)},
        )
