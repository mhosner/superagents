"""Architect persona — technical specification and implementation planning."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from superagents.telemetry import persona_span

from superagents_sdlc.personas.base import BasePersona
from superagents_sdlc.skills.base import SkillValidationError
from superagents_sdlc.skills.engineering.implementation_planner import ImplementationPlanner
from superagents_sdlc.skills.engineering.tech_spec_writer import TechSpecWriter

if TYPE_CHECKING:
    from superagents_sdlc.handoffs.contract import PersonaHandoff
    from superagents_sdlc.handoffs.transport import Transport
    from superagents_sdlc.policy.engine import PolicyEngine
    from superagents_sdlc.skills.base import Artifact, SkillContext
    from superagents_sdlc.skills.llm import LLMClient

logger = logging.getLogger(__name__)

_REQUIRED_CONTEXT = ("prd", "user_stories", "product_context")


class ArchitectPersona(BasePersona):
    """Architect persona producing tech specs and implementation plans."""

    def __init__(
        self,
        *,
        llm: LLMClient,
        policy_engine: PolicyEngine,
        transport: Transport,
    ) -> None:
        """Initialize with LLM client and infrastructure.

        Args:
            llm: LLM client for skill execution.
            policy_engine: Policy engine for handoff evaluation.
            transport: Transport for delivering handoffs.
        """
        skills = {
            "tech_spec_writer": TechSpecWriter(llm=llm),
            "implementation_planner": ImplementationPlanner(llm=llm),
        }
        super().__init__(
            name="architect",
            skills=skills,
            policy_engine=policy_engine,
            transport=transport,
        )
        self.received: list[PersonaHandoff] = []

    async def receive_handoff(self, handoff: PersonaHandoff) -> None:
        """Store and log incoming handoff.

        Args:
            handoff: The incoming handoff to store.
        """
        self.received.append(handoff)
        logger.info(
            "Architect received handoff from %s: %s",
            handoff.source_persona,
            handoff.artifact_type,
        )

    async def run_spec_from_prd(self, context: SkillContext) -> list[Artifact]:
        """Run the spec-from-PRD workflow.

        Linear pipeline: tech spec → implementation plan → handoff to developer.

        Args:
            context: Execution context with prd, user_stories, product_context.

        Returns:
            List of two artifacts: [tech_spec, implementation_plan].

        Raises:
            SkillValidationError: If required context keys are missing.
        """
        for key in _REQUIRED_CONTEXT:
            if key not in context.parameters:
                msg = f"Missing required context for architect workflow: {key}"
                raise SkillValidationError(msg)

        level = self.policy_engine.config.level_for(self.name)

        with persona_span(self.name, autonomy_level=level):
            tech_spec_artifact = await self.execute_skill("tech_spec_writer", context)
            tech_spec_content = Path(tech_spec_artifact.path).read_text()
            context.parameters["tech_spec"] = tech_spec_content

            plan_artifact = await self.execute_skill("implementation_planner", context)

            await self.request_handoff(
                target="developer",
                artifact=plan_artifact,
                context_summary="Tech spec and implementation plan ready for code planning",
                metadata={
                    "tech_spec_path": tech_spec_artifact.path,
                    "user_stories_path": context.parameters.get("user_stories_path", ""),
                    "prd_path": context.parameters.get("prd_path", ""),
                },
            )

        return [tech_spec_artifact, plan_artifact]

    async def handle_handoff(
        self, handoff: PersonaHandoff, context: SkillContext
    ) -> list[Artifact]:
        """Build context from a handoff and run the spec workflow.

        Precondition: context.parameters must already contain "prd" and
        "product_context". The handoff artifact provides user_stories.

        Args:
            handoff: Incoming handoff with artifact path.
            context: Execution context with base context pre-loaded.

        Returns:
            List of artifacts from the workflow.
        """
        context.parameters["user_stories"] = Path(handoff.artifact_path).read_text()
        return await self.run_spec_from_prd(context)
