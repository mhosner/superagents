"""Policy configuration — autonomy levels and overrides."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import yaml
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from pathlib import Path


class PolicyConfig(BaseModel):
    """Autonomy policy configuration.

    Attributes:
        autonomy_level: Global autonomy level (1=assist, 2=hybrid, 3=auto).
        overrides: Per-persona autonomy level overrides.
    """

    autonomy_level: int = Field(default=1, ge=1, le=3)
    overrides: dict[str, int] = Field(default_factory=dict)

    @classmethod
    def from_yaml(cls, path: Path) -> PolicyConfig:
        """Load configuration from a YAML file.

        Args:
            path: Path to the YAML configuration file.

        Returns:
            Validated policy configuration.

        Raises:
            pydantic.ValidationError: If the YAML content is invalid.
        """
        with open(path) as f:  # noqa: PTH123
            data = yaml.safe_load(f)
        return cls.model_validate(data)

    @classmethod
    def from_env(cls) -> PolicyConfig:
        """Load configuration from environment variables.

        Reads ``SUPERAGENTS_AUTONOMY_LEVEL``. Falls back to Level 1 if unset.

        Returns:
            Policy configuration from environment.
        """
        level = int(os.environ.get("SUPERAGENTS_AUTONOMY_LEVEL", "1"))
        return cls(autonomy_level=level)

    def level_for(self, persona: str) -> int:
        """Get the autonomy level for a persona.

        Checks overrides first, falls back to the global level.

        Args:
            persona: Persona identifier.

        Returns:
            The effective autonomy level.
        """
        return self.overrides.get(persona, self.autonomy_level)
