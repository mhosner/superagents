"""Developer persona — TDD code plan generation."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from superagents.telemetry import persona_span

from superagents_sdlc.personas.base import BasePersona
from superagents_sdlc.skills.base import SkillValidationError
from superagents_sdlc.skills.engineering.code_planner import CodePlanner

if TYPE_CHECKING:
    from superagents_sdlc.handoffs.contract import PersonaHandoff
    from superagents_sdlc.handoffs.transport import Transport
    from superagents_sdlc.policy.engine import PolicyEngine
    from superagents_sdlc.skills.base import Artifact, SkillContext
    from superagents_sdlc.skills.llm import LLMClient

logger = logging.getLogger(__name__)

_REQUIRED_CONTEXT = ("implementation_plan", "tech_spec")


class DeveloperPersona(BasePersona):
    """Developer persona producing TDD code plans."""

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
            "code_planner": CodePlanner(llm=llm),
        }
        super().__init__(
            name="developer",
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
            "Developer received handoff from %s: %s",
            handoff.source_persona,
            handoff.artifact_type,
        )

    async def run_plan_from_spec(self, context: SkillContext) -> list[Artifact]:
        """Run the code planning workflow.

        Args:
            context: Execution context with implementation_plan and tech_spec.

        Returns:
            List of one artifact: [code_plan].

        Raises:
            SkillValidationError: If required context keys are missing.
        """
        for key in _REQUIRED_CONTEXT:
            if key not in context.parameters:
                msg = f"Missing required context for developer workflow: {key}"
                raise SkillValidationError(msg)

        level = self.policy_engine.config.level_for(self.name)

        with persona_span(self.name, autonomy_level=level):
            code_plan_artifact = await self.execute_skill("code_planner", context)

        return [code_plan_artifact]

    async def handle_handoff(
        self, handoff: PersonaHandoff, context: SkillContext
    ) -> list[Artifact]:
        """Build context from a handoff and run the code planning workflow.

        Reads the implementation plan from the handoff artifact path and the
        tech spec from the metadata. Optionally loads user_stories and prd
        if paths are present in metadata.

        Args:
            handoff: Incoming handoff with artifact path and metadata.
            context: Execution context (parameters will be populated).

        Returns:
            List of artifacts from the workflow.
        """
        context.parameters["implementation_plan"] = Path(handoff.artifact_path).read_text()

        tech_spec_path = handoff.metadata["tech_spec_path"]
        context.parameters["tech_spec"] = Path(tech_spec_path).read_text()

        for meta_key, param_key in [
            ("user_stories_path", "user_stories"),
            ("prd_path", "prd"),
        ]:
            path_str = handoff.metadata.get(meta_key, "")
            if path_str:
                file_path = Path(path_str)
                if file_path.exists():
                    context.parameters[param_key] = file_path.read_text()

        return await self.run_plan_from_spec(context)
