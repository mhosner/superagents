"""UserStoryWriter — sprint-ready INVEST user story generation skill.

Ported from Manna Ray's user-story-writer skill. Turns features into
sprint-ready stories that are Independent, Negotiable, Valuable, Estimable,
Small, and Testable.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from superagents_sdlc.skills.base import Artifact, BaseSkill, SkillValidationError

if TYPE_CHECKING:
    from superagents_sdlc.skills.base import SkillContext
    from superagents_sdlc.skills.llm import LLMClient

_SYSTEM_PROMPT = """\
You are a senior product manager writing sprint-ready user stories.

## User story format
As a [persona], I want to [action], So that [benefit]

## INVEST checklist (validate each story)
- **Independent**: Can be developed and delivered separately
- **Negotiable**: Details can be discussed, not a contract
- **Valuable**: Delivers value to the user or business
- **Estimable**: Team can estimate effort
- **Small**: Fits in a single sprint
- **Testable**: Clear pass/fail criteria

## Acceptance criteria format (BDD)
For each story, provide:
- **Happy path**: Given/When/Then for the primary flow
- **Alternate path**: Given/When/Then for secondary flows
- **Error states**: Given/When/Then for failure cases

## Additional sections
- **Edge cases**: Boundary conditions and unusual inputs
- **Technical notes**: Implementation hints for the dev team
- **Out of scope**: What this story explicitly does NOT cover

Connect "So that" clauses to persona goals and frustrations from the context.
"""


def _extract_persona_name(personas_context: str) -> str:
    """Extract persona name from the first line or heading of context.

    Args:
        personas_context: Raw persona context string.

    Returns:
        Extracted name or "unknown" if parsing fails.
    """
    for line in personas_context.splitlines():
        stripped = line.strip().lstrip("#").strip()
        if stripped:
            return stripped
    return "unknown"


class UserStoryWriter(BaseSkill):
    """Generate sprint-ready INVEST user stories with BDD acceptance criteria."""

    def __init__(self, *, llm: LLMClient) -> None:
        """Initialize with an LLM client.

        Args:
            llm: LLM client for generating user stories.
        """
        self._llm = llm
        super().__init__(
            name="user_story_writer",
            description="Generate sprint-ready INVEST user stories with BDD acceptance criteria",
            required_context=["personas_context", "feature_description"],
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
        """Generate user stories from the feature description and persona context.

        Args:
            context: Execution context with feature and persona details.

        Returns:
            Artifact pointing to the user stories output file.
        """
        params = context.parameters
        feature = params["feature_description"]
        personas = params["personas_context"]

        prompt_parts = [
            f"## Feature description\n{feature}",
            f"## Persona context\n{personas}",
        ]

        if "prd" in params:
            prompt_parts.append(f"## Full PRD\n{params['prd']}")
        if "product_context" in params:
            prompt_parts.append(f"## Product roadmap context\n{params['product_context']}")

        prompt = "\n\n".join(prompt_parts)
        response = await self._llm.generate(prompt, system=_SYSTEM_PROMPT)

        output_path = context.artifact_dir / "user_stories.md"
        output_path.write_text(response)

        persona_name = _extract_persona_name(personas)

        return Artifact(
            path=str(output_path),
            artifact_type="user_story",
            metadata={"persona": persona_name},
        )
