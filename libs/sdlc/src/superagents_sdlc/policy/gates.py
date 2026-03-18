"""Approval gates — Protocol and implementations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from superagents_sdlc.handoffs.contract import PersonaHandoff


@dataclass
class ApprovalResult:
    """Result of an approval gate evaluation.

    Attributes:
        approved: Whether the handoff was approved.
        outcome: Description — "auto_proceeded", "approved", "rejected", or "awaiting_approval".
        duration_ms: Time taken for the gate decision in milliseconds.
    """

    approved: bool
    outcome: str
    duration_ms: int = 0


class ApprovalGate(Protocol):
    """Protocol for approval gate implementations."""

    def evaluate(self, handoff: PersonaHandoff, level: int) -> ApprovalResult:
        """Evaluate whether a handoff should proceed.

        Args:
            handoff: The handoff to evaluate.
            level: Current autonomy level.

        Returns:
            The approval decision.
        """
        ...


class AutoApprovalGate:
    """Gate that always approves — used for Level 2/3 auto-proceed."""

    def evaluate(
        self,
        handoff: PersonaHandoff,  # noqa: ARG002
        level: int,  # noqa: ARG002
    ) -> ApprovalResult:
        """Always approve.

        Args:
            handoff: The handoff to evaluate.
            level: Current autonomy level.

        Returns:
            Approved result with "auto_proceeded" outcome.
        """
        return ApprovalResult(approved=True, outcome="auto_proceeded", duration_ms=0)


class MockApprovalGate:
    """Configurable test double for approval gates.

    Args:
        should_approve: Whether to approve or reject.
    """

    def __init__(self, *, should_approve: bool = True) -> None:
        """Initialize the mock gate.

        Args:
            should_approve: If True, approves; if False, rejects.
        """
        self._should_approve = should_approve

    def evaluate(
        self,
        handoff: PersonaHandoff,  # noqa: ARG002
        level: int,  # noqa: ARG002
    ) -> ApprovalResult:
        """Return configured approval or rejection.

        Args:
            handoff: The handoff to evaluate.
            level: Current autonomy level.

        Returns:
            Approval result based on configuration.
        """
        if self._should_approve:
            return ApprovalResult(approved=True, outcome="approved")
        return ApprovalResult(approved=False, outcome="rejected")
