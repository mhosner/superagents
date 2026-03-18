"""PrdGenerator — structured PRD generation skill.

Ported from Manna Ray's prd-generator skill. Transforms ideas into structured
PRDs with problem statements, evidence, success criteria, and risk assessment.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from superagents_sdlc.skills.base import Artifact, BaseSkill, SkillValidationError

if TYPE_CHECKING:
    from superagents_sdlc.skills.base import SkillContext
    from superagents_sdlc.skills.llm import LLMClient

_SYSTEM_PROMPT = """\
You are a senior product manager writing a Product Requirements Document (PRD). \
Your PRD must get stakeholder alignment before engineering starts building.

## Required PRD structure

1. **Context summary** — What was pulled from context files
2. **Problem statement** — The user pain point or business opportunity
3. **Evidence** — Mark each data point as [VALIDATED] or [ASSUMED]
4. **Success criteria**
   - Lagging indicators: post-launch outcomes
   - Leading indicators: pre-launch signals that predict success
   - Use PLACEHOLDER for missing metrics rather than fabricating numbers
5. **Dependencies** — Feature, team, and external dependencies + critical path
6. **Proposed solution** — With 2-3 user stories
7. **Non-goals** — Explicitly out of scope
8. **Risks** — Assessed across Value/Usability/Feasibility/Viability (Cagan framework)
9. **Open questions** — With validation experiments
10. **Sign-off checklist**
"""


class PrdGenerator(BaseSkill):
    """Transform ideas into structured PRDs."""

    def __init__(self, *, llm: LLMClient) -> None:
        """Initialize with an LLM client.

        Args:
            llm: LLM client for generating the PRD.
        """
        self._llm = llm
        super().__init__(
            name="prd_generator",
            description=(
                "Transform ideas into structured PRDs with problem statements, "
                "evidence, success criteria, and risk assessment"
            ),
            required_context=["idea", "product_context", "personas_context", "goals_context"],
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
        """Generate a PRD from the idea and context.

        Args:
            context: Execution context with idea and strategic context.

        Returns:
            Artifact pointing to the PRD output file.
        """
        params = context.parameters
        idea = params["idea"]
        product = params["product_context"]
        personas = params["personas_context"]
        goals = params["goals_context"]

        prompt_parts = [
            f"## Idea / feature to spec\n{idea}",
            f"## Product roadmap context\n{product}",
            f"## User persona pain points\n{personas}",
            f"## Active goals\n{goals}",
        ]

        if "company_context" in params:
            prompt_parts.append(f"## Company strategy\n{params['company_context']}")
        if "competitors_context" in params:
            prompt_parts.append(f"## Competitive landscape\n{params['competitors_context']}")
        if "priority_output" in params:
            prompt_parts.append(f"## Priority ranking\n{params['priority_output']}")

        prompt = "\n\n".join(prompt_parts)
        response = await self._llm.generate(prompt, system=_SYSTEM_PROMPT)

        output_path = context.artifact_dir / "prd.md"
        output_path.write_text(response)

        return Artifact(
            path=str(output_path),
            artifact_type="prd",
            metadata={"idea": idea[:100]},
        )
