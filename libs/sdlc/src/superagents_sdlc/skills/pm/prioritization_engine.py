"""PrioritizationEngine — RICE-based backlog prioritization skill.

Ported from Manna Ray's prioritization-engine skill. Ranks competing features
using RICE scoring (Reach x Impact x Confidence / Effort) with strategic overrides.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from superagents_sdlc.skills.base import Artifact, BaseSkill, SkillValidationError

if TYPE_CHECKING:
    from superagents_sdlc.skills.base import SkillContext
    from superagents_sdlc.skills.llm import LLMClient

_SYSTEM_PROMPT = """\
You are a senior product manager performing backlog prioritization using the \
RICE framework (Reach x Impact x Confidence / Effort).

For each item, score these dimensions:
- **Reach**: How many users/accounts will this impact per quarter?
- **Impact**: How much will this move the needle? \
(3=massive, 2=high, 1=medium, 0.5=low, 0.25=minimal)
- **Confidence**: How sure are we about Reach and Impact estimates? (100%/80%/50%)
- **Effort**: Person-months to ship.

Goal alignment: Items that directly advance the stated goals receive an Impact boost.

## Required output structure

1. **Rankings table** — Rank, Item, RICE Score, Reach, Impact, Confidence, Effort
2. **Detailed breakdown** — Per item: scoring rationale with cited context sources
3. **Value/Effort matrix** — 2x2 categorization
4. **Sensitivity analysis** — How rankings shift if key assumptions change
5. **Recommendations** — Categorize each item: Do Now / Do Next / Quick Win / Defer / Deprioritize
"""


class PrioritizationEngine(BaseSkill):
    """Rank features using RICE scoring with strategic context."""

    def __init__(self, *, llm: LLMClient) -> None:
        """Initialize with an LLM client.

        Args:
            llm: LLM client for generating prioritization analysis.
        """
        self._llm = llm
        super().__init__(
            name="prioritization_engine",
            description=(
                "Defend your roadmap with RICE scoring that shows stakeholders "
                "exactly why features ranked the way they did"
            ),
            required_context=["items", "product_context", "goals_context"],
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
        """Prioritize items using RICE scoring via the LLM.

        Args:
            context: Execution context with items and strategic context.

        Returns:
            Artifact pointing to the prioritization output file.
        """
        params = context.parameters
        items = params["items"]
        goals = params["goals_context"]
        product = params["product_context"]

        prompt_parts = [
            f"## Items to prioritize\n{items}",
            f"## Active goals and revenue targets\n{goals}",
            f"## Product roadmap and known priorities\n{product}",
        ]

        # Optional context enhances scoring quality
        if "company_context" in params:
            prompt_parts.append(f"## Strategic priorities\n{params['company_context']}")
        if "personas_context" in params:
            prompt_parts.append(f"## Persona pain points\n{params['personas_context']}")
        if "competitors_context" in params:
            prompt_parts.append(f"## Competitive factors\n{params['competitors_context']}")
        if "brief" in params:
            prompt_parts.append(f"## Design Brief\n{params['brief']}")

        prompt = "\n\n".join(prompt_parts)
        response = await self._llm.generate(prompt, system=_SYSTEM_PROMPT)

        output_path = context.artifact_dir / "prioritization.md"
        output_path.write_text(response)

        # Count items heuristically from the input
        lines = [line.strip() for line in str(items).splitlines() if line.strip()]
        item_count = len(lines)

        return Artifact(
            path=str(output_path),
            artifact_type="backlog",
            metadata={"item_count": str(item_count), "framework": "RICE"},
        )
