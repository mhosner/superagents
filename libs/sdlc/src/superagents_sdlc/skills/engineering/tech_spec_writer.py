"""TechSpecWriter — technical specification generation skill.

Transforms PRDs and user stories into technical specifications with architecture
decisions, data models, and API designs.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from superagents_sdlc.skills.base import Artifact, BaseSkill, SkillValidationError

if TYPE_CHECKING:
    from superagents_sdlc.skills.base import SkillContext
    from superagents_sdlc.skills.llm import LLMClient

_SYSTEM_PROMPT = """\
You are a senior software architect writing a technical specification. \
Your spec translates product requirements into engineering decisions.

## Required output structure

1. **Architecture overview** — High-level component diagram and interactions
2. **Component boundaries** — What each module owns and what it does not
3. **Data model** — Entities, relationships, key fields
4. **API design** — Endpoints or interfaces, request/response shapes
5. **Infrastructure requirements** — Runtime, storage, networking
6. **Security considerations** — Auth, data protection, input validation
7. **Technical risks** — What could go wrong and mitigation strategies
8. **Open technical questions** — Unknowns that need investigation
"""


class TechSpecWriter(BaseSkill):
    """Transform PRDs and user stories into technical specifications."""

    def __init__(self, *, llm: LLMClient) -> None:
        """Initialize with an LLM client.

        Args:
            llm: LLM client for generating the tech spec.
        """
        self._llm = llm
        super().__init__(
            name="tech_spec_writer",
            description=(
                "Transform PRDs and user stories into technical specifications "
                "with architecture decisions, data models, and API designs"
            ),
            required_context=["prd", "user_stories", "product_context"],
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
        """Generate a tech spec from PRD and user stories.

        Args:
            context: Execution context with PRD and product context.

        Returns:
            Artifact pointing to the tech spec output file.
        """
        params = context.parameters
        prd = params["prd"]
        stories = params["user_stories"]
        product = params["product_context"]

        prompt_parts = [
            f"## PRD\n{prd}",
            f"## User stories\n{stories}",
            f"## Product context\n{product}",
        ]

        if "goals_context" in params:
            prompt_parts.append(f"## Goals\n{params['goals_context']}")
        if "priority_output" in params:
            prompt_parts.append(f"## Priority ranking\n{params['priority_output']}")

        prompt = "\n\n".join(prompt_parts)
        response = await self._llm.generate(prompt, system=_SYSTEM_PROMPT)

        output_path = context.artifact_dir / "tech_spec.md"
        output_path.write_text(response)

        return Artifact(
            path=str(output_path),
            artifact_type="tech_spec",
            metadata={"prd_idea": prd[:100]},
        )
