"""Base persona — abstract facade for SDLC persona roles."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from opentelemetry import trace
from superagents.telemetry import handoff_span, skill_span

from superagents_sdlc.handoffs.contract import HandoffResult, PersonaHandoff

if TYPE_CHECKING:
    from typing import Any

    from superagents_sdlc.handoffs.transport import Transport
    from superagents_sdlc.policy.engine import PolicyEngine
    from superagents_sdlc.skills.base import Artifact, BaseSkill, SkillContext


class BasePersona(ABC):
    """Abstract base class for SDLC personas.

    Provides concrete `execute_skill` and `request_handoff` methods with
    telemetry integration. Subclasses implement `receive_handoff` to
    handle incoming work.
    """

    def __init__(
        self,
        *,
        name: str,
        skills: dict[str, BaseSkill],
        policy_engine: PolicyEngine,
        transport: Transport,
    ) -> None:
        """Initialize the persona.

        Args:
            name: Persona identifier.
            skills: Map of skill name to skill instance.
            policy_engine: Policy engine for handoff evaluation.
            transport: Transport for delivering handoffs.
        """
        self.name = name
        self.skills = skills
        self.policy_engine = policy_engine
        self.transport = transport

    async def execute_skill(self, skill_name: str, context: SkillContext) -> Artifact:
        """Execute a skill by name with telemetry.

        Looks up the skill, validates, and executes within a skill span.

        Note: Phase 1 span context managers are synchronous @contextmanager.
        Python's contextvars (used by OTel) survive await boundaries within
        the same task, so ``with skill_span(...): await skill.execute(...)``
        correctly parents child spans. This breaks only if a new
        ``asyncio.create_task()`` is spawned inside the with block. Phase 2
        is single-task await chains, so this is safe.

        Args:
            skill_name: Name of the skill to execute.
            context: Execution context for the skill.

        Returns:
            The output artifact.

        Raises:
            KeyError: If the skill is not found.
            SkillValidationError: If validation fails.
        """
        if skill_name not in self.skills:
            msg = f"Unknown skill: {skill_name}"
            raise KeyError(msg)

        skill = self.skills[skill_name]
        with skill_span(skill_name) as span:
            try:
                skill.validate(context)
                return await skill.execute(context)
            except Exception:
                span.set_status(trace.StatusCode.ERROR)
                raise

    async def request_handoff(
        self,
        *,
        target: str,
        artifact: Artifact,
        context_summary: str,
        metadata: dict[str, Any] | None = None,
    ) -> HandoffResult:
        """Request a handoff to another persona.

        Builds the handoff, evaluates it through the policy engine, and
        sends it via the transport if approved.

        Args:
            target: Target persona name.
            artifact: The artifact to hand off.
            context_summary: Compressed context for the receiver.
            metadata: Structured key-value pairs for inter-persona routing.

        Returns:
            The handoff result.
        """
        level = self.policy_engine.config.level_for(self.name)

        with handoff_span(self.name, target, artifact_type=artifact.artifact_type) as span:
            # Extract trace context from the current span
            ctx = span.get_span_context()
            trace_id = format(ctx.trace_id, "032x")
            parent_span_id = format(ctx.span_id, "016x")

            # Build handoff with preliminary values
            handoff = PersonaHandoff(
                source_persona=self.name,
                target_persona=target,
                artifact_type=artifact.artifact_type,
                artifact_path=artifact.path,
                context_summary=context_summary,
                autonomy_level=level,
                requires_approval=False,
                trace_id=trace_id,
                parent_span_id=parent_span_id,
                metadata=metadata or {},
            )

            # Evaluate through policy engine
            approval = await self.policy_engine.evaluate_handoff(handoff)
            handoff.requires_approval = not approval.approved

            if not approval.approved:
                return HandoffResult(
                    status="rejected",
                    target_persona=target,
                    trace_id=trace_id,
                )

            # Send via transport
            return await self.transport.send(handoff)

    @abstractmethod
    async def receive_handoff(self, handoff: PersonaHandoff) -> None:
        """Handle an incoming handoff.

        Each persona type decides what to do with incoming work.

        Args:
            handoff: The incoming handoff to process.
        """
