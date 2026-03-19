"""Policy engine — intercepts handoffs and enforces approval gates."""

from __future__ import annotations

from typing import TYPE_CHECKING

from superagents.telemetry import approval_gate_span

from superagents_sdlc.policy.gates import ApprovalResult

if TYPE_CHECKING:
    from superagents_sdlc.handoffs.contract import PersonaHandoff
    from superagents_sdlc.policy.config import PolicyConfig
    from superagents_sdlc.policy.gates import ApprovalGate

PLANNING_ARTIFACT_TYPES: frozenset[str] = frozenset(
    {
        "prd",
        "tech_spec",
        "user_story",
        "roadmap",
        "backlog",
        "architecture",
        "implementation_plan",
    }
)

APPROVAL_REQUIRED_TYPES: frozenset[str] = frozenset(
    {
        "code",
        "test",
        "migration",
        "compliance_report",
        "validation_report",
    }
)


class PolicyEngine:
    """Evaluates handoffs against autonomy policy and approval gates.

    Determines whether a handoff requires human approval based on the
    autonomy level and artifact type, then delegates to the configured
    gate when approval is needed.
    """

    def __init__(self, *, config: PolicyConfig, gate: ApprovalGate) -> None:
        """Initialize the engine.

        Args:
            config: Autonomy policy configuration.
            gate: Approval gate implementation.
        """
        self.config = config
        self._gate = gate

    async def evaluate_handoff(self, handoff: PersonaHandoff) -> ApprovalResult:
        """Evaluate whether a handoff should proceed.

        Args:
            handoff: The handoff to evaluate.

        Returns:
            The approval decision with outcome and timing.
        """
        level = self.config.level_for(handoff.source_persona)
        gate_name = f"{handoff.source_persona}_to_{handoff.target_persona}"

        with approval_gate_span(gate_name, autonomy_level=level) as span:
            required = self._is_approval_required(level, handoff.artifact_type)

            if required:
                result = self._gate.evaluate(handoff, level)
            else:
                result = ApprovalResult(approved=True, outcome="auto_proceeded")

            span.set_attribute("approval.required", required)
            span.set_attribute("approval.outcome", result.outcome)
            span.set_attribute("gate_duration_ms", result.duration_ms)

        return result

    @staticmethod
    def _is_approval_required(level: int, artifact_type: str) -> bool:
        """Determine if approval is required for a given level and artifact type.

        Args:
            level: Autonomy level (1, 2, or 3).
            artifact_type: The type of artifact being handed off.

        Returns:
            True if human approval is required.
        """
        if level == 1:
            return True
        if level >= 3:  # noqa: PLR2004
            return False
        # Level 2: planning artifacts auto-proceed, everything else requires approval
        return artifact_type not in PLANNING_ARTIFACT_TYPES
