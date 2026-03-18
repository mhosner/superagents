"""Skill contract — BaseSkill ABC, SkillContext, Artifact, and SkillValidationError."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

from pydantic import BaseModel


class SkillValidationError(Exception):
    """Raised when skill preconditions fail during validation."""


@dataclass
class SkillContext:
    """Execution context passed to skills.

    Internal to skill execution — does not cross serialization boundaries.

    Attributes:
        artifact_dir: Directory for writing output artifacts.
        parameters: Skill-specific parameters.
        trace_id: OpenTelemetry trace identifier for correlation.
    """

    artifact_dir: Path
    parameters: dict[str, Any] = field(default_factory=dict)
    trace_id: str = ""


class Artifact(BaseModel):
    """Output artifact produced by a skill.

    Uses `str` for `path` (not `Path`) so it JSON-serializes cleanly,
    consistent with `PersonaHandoff`.

    Attributes:
        path: Filesystem path to the artifact.
        artifact_type: Classification of the artifact (e.g., "prd", "code").
        metadata: Additional key-value metadata.
    """

    path: str
    artifact_type: str
    metadata: dict[str, str] = {}


class BaseSkill(ABC):
    """Abstract base class for SDLC skills.

    Subclasses call ``super().__init__()`` with their values and implement
    the async `execute` method.
    """

    def __init__(
        self,
        name: str,
        description: str,
        required_context: list[str] | None = None,
    ) -> None:
        """Initialize the skill.

        Args:
            name: Skill identifier.
            description: Human-readable description.
            required_context: Context keys required by this skill.
        """
        self.name = name
        self.description = description
        self.required_context: list[str] = required_context if required_context is not None else []

    def validate(self, context: SkillContext) -> None:  # noqa: B027
        """Check preconditions before execution.

        Default is a no-op. Subclasses override to enforce requirements.

        Args:
            context: The execution context to validate.

        Raises:
            SkillValidationError: When preconditions are not met.
        """

    @abstractmethod
    async def execute(self, context: SkillContext) -> Artifact:
        """Execute the skill and return an artifact.

        Args:
            context: The execution context.

        Returns:
            The output artifact.
        """
