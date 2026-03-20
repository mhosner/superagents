"""Pipeline result — structured output from workflow execution."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from superagents_sdlc.skills.base import Artifact


@dataclass
class PipelineResult:
    """Result of a pipeline workflow execution.

    Groups artifacts by persona and promotes the QA certification to
    a top-level field for easy access by CLI and evaluation harnesses.

    Attributes:
        artifacts: All artifacts in pipeline order.
        pm: PM persona artifacts (empty if skipped).
        architect: Architect persona artifacts (empty if skipped).
        developer: Developer persona artifacts (empty if skipped).
        qa: QA persona artifacts (empty if skipped).
        certification: QA certification or "skipped" if QA didn't run.
    """

    artifacts: list[Artifact] = field(default_factory=list)
    pm: list[Artifact] = field(default_factory=list)
    architect: list[Artifact] = field(default_factory=list)
    developer: list[Artifact] = field(default_factory=list)
    qa: list[Artifact] = field(default_factory=list)
    certification: str = "skipped"
