"""Product Manager persona — PRD generation, prioritization, and story writing."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from superagents.telemetry import persona_span

from superagents_sdlc.personas.base import BasePersona
from superagents_sdlc.skills.pm.prd_generator import PrdGenerator
from superagents_sdlc.skills.pm.prioritization_engine import PrioritizationEngine
from superagents_sdlc.skills.pm.user_story_writer import UserStoryWriter

if TYPE_CHECKING:
    from superagents_sdlc.handoffs.contract import PersonaHandoff
    from superagents_sdlc.handoffs.transport import Transport
    from superagents_sdlc.policy.engine import PolicyEngine
    from superagents_sdlc.skills.base import Artifact, SkillContext
    from superagents_sdlc.skills.llm import LLMClient

logger = logging.getLogger(__name__)


class ProductManagerPersona(BasePersona):
    """PM persona wrapping Manna Ray skills for PRD, prioritization, and stories."""

    def __init__(
        self,
        *,
        llm: LLMClient,
        policy_engine: PolicyEngine,
        transport: Transport,
    ) -> None:
        """Initialize with LLM client and infrastructure.

        Creates the three PM skills internally and registers them.

        Args:
            llm: LLM client for skill execution.
            policy_engine: Policy engine for handoff evaluation.
            transport: Transport for delivering handoffs.
        """
        skills = {
            "prd_generator": PrdGenerator(llm=llm),
            "prioritization_engine": PrioritizationEngine(llm=llm),
            "user_story_writer": UserStoryWriter(llm=llm),
        }
        super().__init__(
            name="product_manager",
            skills=skills,
            policy_engine=policy_engine,
            transport=transport,
        )

    async def receive_handoff(self, handoff: PersonaHandoff) -> None:
        """Handle an incoming handoff.

        For Phase 3, logs receipt. No automatic workflow triggering —
        the PM persona is primarily a sender of handoffs.

        Args:
            handoff: The incoming handoff to process.
        """
        logger.info(
            "PM received handoff from %s: %s",
            handoff.source_persona,
            handoff.artifact_type,
        )

    async def run_idea_to_sprint(self, idea: str, context: SkillContext) -> list[Artifact]:
        """Run the idea-to-sprint workflow.

        Linear pipeline: prioritize → PRD → user stories → handoff to architect.

        Prerequisite: context.parameters must contain product_context,
        goals_context, and personas_context. The workflow populates idea,
        items, prd, prd_path, feature_description, and priority_output
        as it chains skills.

        Args:
            idea: The feature idea to process.
            context: Execution context with pre-loaded context file contents.

        Returns:
            List of three artifacts: [prioritization, prd, user_stories].
        """
        level = self.policy_engine.config.level_for(self.name)

        with persona_span(self.name, autonomy_level=level):
            # Step 1: Prioritize
            context.parameters["items"] = idea
            priority_artifact = await self.execute_skill("prioritization_engine", context)
            priority_content = _read_artifact(priority_artifact)
            context.parameters["priority_output"] = priority_content

            # Step 2: Generate PRD
            context.parameters["idea"] = idea
            prd_artifact = await self.execute_skill("prd_generator", context)
            prd_content = _read_artifact(prd_artifact)
            context.parameters["prd"] = prd_content
            context.parameters["prd_path"] = prd_artifact.path

            # Step 3: Write user stories
            context.parameters["feature_description"] = prd_content
            stories_artifact = await self.execute_skill("user_story_writer", context)

            # Step 4: Handoff to architect
            await self.request_handoff(
                target="architect",
                artifact=stories_artifact,
                context_summary="PRD and user stories ready for technical architecture",
            )

        return [priority_artifact, prd_artifact, stories_artifact]


def _read_artifact(artifact: Artifact) -> str:
    """Read artifact content from disk.

    Args:
        artifact: Artifact with a filesystem path.

    Returns:
        File content as string.
    """
    return Path(artifact.path).read_text()
