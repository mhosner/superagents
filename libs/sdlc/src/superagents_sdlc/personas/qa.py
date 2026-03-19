"""QA persona — compliance checking and validation reporting."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from superagents.telemetry import persona_span

from superagents_sdlc.personas.base import BasePersona
from superagents_sdlc.skills.base import SkillValidationError
from superagents_sdlc.skills.qa.spec_compliance_checker import SpecComplianceChecker
from superagents_sdlc.skills.qa.validation_report_generator import (
    ValidationReportGenerator,
)

if TYPE_CHECKING:
    from superagents_sdlc.handoffs.contract import PersonaHandoff
    from superagents_sdlc.handoffs.transport import Transport
    from superagents_sdlc.policy.engine import PolicyEngine
    from superagents_sdlc.skills.base import Artifact, SkillContext
    from superagents_sdlc.skills.llm import LLMClient

logger = logging.getLogger(__name__)

_REQUIRED_CONTEXT = ("code_plan", "user_stories", "tech_spec")


class QAPersona(BasePersona):
    """QA persona performing compliance checking and readiness certification."""

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
            "spec_compliance_checker": SpecComplianceChecker(llm=llm),
            "validation_report_generator": ValidationReportGenerator(llm=llm),
        }
        super().__init__(
            name="qa",
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
            "QA received handoff from %s: %s",
            handoff.source_persona,
            handoff.artifact_type,
        )

    async def run_validation(self, context: SkillContext) -> list[Artifact]:
        """Run the validation workflow.

        Linear pipeline: compliance check -> validation report.

        Args:
            context: Execution context with code_plan, user_stories, tech_spec.

        Returns:
            List of two artifacts: [compliance_report, validation_report].

        Raises:
            SkillValidationError: If required context keys are missing.
        """
        # Pre-flight: fail fast before persona_span opens to avoid orphaned traces.
        # Skills also validate in execute_skill(), but that's inside the span.
        for key in _REQUIRED_CONTEXT:
            if key not in context.parameters:
                msg = f"Missing required context for QA workflow: {key}"
                raise SkillValidationError(msg)

        level = self.policy_engine.config.level_for(self.name)

        with persona_span(self.name, autonomy_level=level):
            # Step 1: Run compliance check
            compliance_artifact = await self.execute_skill("spec_compliance_checker", context)
            compliance_content = Path(compliance_artifact.path).read_text()
            context.parameters["compliance_report"] = compliance_content

            # Step 2: Generate validation report
            validation_artifact = await self.execute_skill("validation_report_generator", context)

        return [compliance_artifact, validation_artifact]

    async def handle_handoff(
        self, handoff: PersonaHandoff, context: SkillContext
    ) -> list[Artifact]:
        """Build context from a handoff and run the validation workflow.

        Reads the code plan from the primary artifact and loads tech spec,
        user stories, and optional context from metadata paths.

        Args:
            handoff: Incoming handoff with artifact path and metadata.
            context: Execution context (parameters will be populated).

        Returns:
            List of artifacts from the workflow.
        """
        # Required: code plan from primary artifact
        context.parameters["code_plan"] = Path(handoff.artifact_path).read_text()

        # Required: tech spec and user stories from metadata
        tech_spec_path = handoff.metadata["tech_spec_path"]
        context.parameters["tech_spec"] = Path(tech_spec_path).read_text()

        user_stories_path = handoff.metadata["user_stories_path"]
        context.parameters["user_stories"] = Path(user_stories_path).read_text()

        # Optional: implementation plan and PRD
        for meta_key, param_key in [
            ("implementation_plan_path", "implementation_plan"),
            ("prd_path", "prd"),
        ]:
            path_str = handoff.metadata.get(meta_key, "")
            if path_str:
                file_path = Path(path_str)
                if file_path.exists():
                    context.parameters[param_key] = file_path.read_text()

        return await self.run_validation(context)
