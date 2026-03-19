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
You are a senior developer planning a TDD implementation. For each task \
from the implementation plan, produce a detailed code-level plan.

## Per-task structure

For each task:
- **File paths**: Exact files to create or modify (with full paths)
- **Function/class signatures**: With type hints
- **RED**: Test cases to write first (test name, assertion, expected behavior)
- **GREEN**: Minimum implementation to make tests pass
- **REFACTOR**: Cleanup opportunities after green

## Output structure

1. **Ordered task breakdown** — In dependency order
2. **Integration test outline** — How to verify components work together
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
