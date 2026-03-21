"""Pipeline orchestrator — named workflow methods for persona sequencing."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from superagents_sdlc.handoffs.registry import PersonaRegistry
from superagents_sdlc.handoffs.transport import InProcessTransport
from superagents_sdlc.personas.architect import ArchitectPersona
from superagents_sdlc.personas.developer import DeveloperPersona
from superagents_sdlc.personas.product_manager import ProductManagerPersona
from superagents_sdlc.personas.qa import QAPersona
from superagents_sdlc.skills.base import SkillContext
from superagents_sdlc.workflows.result import PipelineResult

if TYPE_CHECKING:
    from collections.abc import Callable

    from superagents_sdlc.handoffs.contract import PersonaHandoff
    from superagents_sdlc.personas.base import BasePersona
    from superagents_sdlc.policy.engine import PolicyEngine
    from superagents_sdlc.skills.base import Artifact
    from superagents_sdlc.skills.llm import LLMClient


def _find_artifact(artifacts: list[Artifact], artifact_type: str) -> Artifact:
    """Find an artifact by type in a list.

    Args:
        artifacts: List of artifacts to search.
        artifact_type: Type to find.

    Returns:
        The first matching artifact.

    Raises:
        ValueError: If no artifact of the given type is found.
    """
    for a in artifacts:
        if a.artifact_type == artifact_type:
            return a
    msg = f"No artifact of type '{artifact_type}' found"
    raise ValueError(msg)


def _get_handoff(persona: BasePersona, expected_source: str) -> PersonaHandoff:
    """Get the last received handoff and verify its source.

    Args:
        persona: Persona to read handoff from.
        expected_source: Expected source persona name.

    Returns:
        The last received handoff.

    Raises:
        RuntimeError: If no handoff received or source doesn't match.
    """
    if not persona.received:
        msg = f"{persona.name} has no received handoffs"
        raise RuntimeError(msg)
    handoff = persona.received[-1]
    if handoff.source_persona != expected_source:
        msg = (
            f"Expected handoff from '{expected_source}' to '{persona.name}', "
            f"got from '{handoff.source_persona}'"
        )
        raise RuntimeError(msg)
    return handoff


class PipelineOrchestrator:
    """Orchestrates SDLC persona pipelines with named workflow methods.

    Creates and manages all four personas internally. The caller provides
    an LLM client, a policy engine, and project-level context. Each workflow
    method chains personas in the right order with proper context forwarding.
    """

    def __init__(
        self,
        *,
        llm: LLMClient,
        policy_engine: PolicyEngine,
        context: dict[str, str],
    ) -> None:
        """Initialize with LLM, policy engine, and project context.

        Args:
            llm: LLM client shared by all personas.
            policy_engine: Policy engine for handoff evaluation.
            context: Project-level context files (product_context, etc.).
        """
        self._context = dict(context)
        self._registry = PersonaRegistry()
        self._transport = InProcessTransport(registry=self._registry)

        self._pm = ProductManagerPersona(
            llm=llm, policy_engine=policy_engine, transport=self._transport
        )
        self._architect = ArchitectPersona(
            llm=llm, policy_engine=policy_engine, transport=self._transport
        )
        self._developer = DeveloperPersona(
            llm=llm, policy_engine=policy_engine, transport=self._transport
        )
        self._qa = QAPersona(llm=llm, policy_engine=policy_engine, transport=self._transport)

        self._registry.register(self._pm)
        self._registry.register(self._architect)
        self._registry.register(self._developer)
        self._registry.register(self._qa)

    def _merge_context(self, overrides: dict[str, str] | None = None) -> dict[str, str]:
        """Merge base context with optional call-time overrides.

        Args:
            overrides: Keys to override in the base context.

        Returns:
            Merged context dict.
        """
        return {**self._context, **(overrides or {})}

    async def run_idea_to_code(
        self,
        idea: str,
        *,
        artifact_dir: Path,
        context_overrides: dict[str, str] | None = None,
        on_phase_complete: Callable[[str, list[Artifact]], None] | None = None,
    ) -> PipelineResult:
        """Run full pipeline: PM -> Architect -> Developer -> QA.

        Args:
            idea: Feature idea or description.
            artifact_dir: Root directory for all artifacts.
            context_overrides: Optional overrides for project context.
            on_phase_complete: Optional callback invoked after each phase with
                the phase name and its produced artifacts.

        Returns:
            PipelineResult with all artifacts grouped by persona.
        """
        ctx = self._merge_context(context_overrides)

        # PM phase
        pm_dir = artifact_dir / "pm"
        pm_dir.mkdir(parents=True, exist_ok=True)
        pm_context = SkillContext(artifact_dir=pm_dir, parameters=dict(ctx), trace_id="pipeline")
        pm_artifacts = await self._pm.run_idea_to_sprint(idea, pm_context)
        if on_phase_complete:
            on_phase_complete("pm", pm_artifacts)

        # Find PRD artifact by type (not positional index)
        prd_artifact = _find_artifact(pm_artifacts, "prd")

        # Architect phase — receives handoff from PM via transport
        arch_dir = artifact_dir / "architect"
        arch_dir.mkdir(parents=True, exist_ok=True)
        arch_context = SkillContext(
            artifact_dir=arch_dir,
            parameters={
                "prd": Path(prd_artifact.path).read_text(),
                "prd_path": prd_artifact.path,
                "product_context": ctx.get("product_context", ""),
            },
            trace_id="pipeline",
        )

        arch_handoff = _get_handoff(self._architect, "product_manager")
        arch_artifacts = await self._architect.handle_handoff(arch_handoff, arch_context)
        if on_phase_complete:
            on_phase_complete("architect", arch_artifacts)

        # Developer phase — receives handoff from Architect via transport
        dev_dir = artifact_dir / "developer"
        dev_dir.mkdir(parents=True, exist_ok=True)
        dev_context = SkillContext(artifact_dir=dev_dir, parameters={}, trace_id="pipeline")

        dev_handoff = _get_handoff(self._developer, "architect")
        dev_artifacts = await self._developer.handle_handoff(dev_handoff, dev_context)
        if on_phase_complete:
            on_phase_complete("developer", dev_artifacts)

        # QA phase — receives handoff from Developer via transport
        qa_dir = artifact_dir / "qa"
        qa_dir.mkdir(parents=True, exist_ok=True)
        qa_context = SkillContext(artifact_dir=qa_dir, parameters={}, trace_id="pipeline")

        qa_handoff = _get_handoff(self._qa, "developer")
        qa_artifacts = await self._qa.handle_handoff(qa_handoff, qa_context)
        if on_phase_complete:
            on_phase_complete("qa", qa_artifacts)

        # Build result
        all_artifacts = pm_artifacts + arch_artifacts + dev_artifacts + qa_artifacts
        certification = (
            next(
                (
                    a.metadata.get("certification", "unknown")
                    for a in qa_artifacts
                    if a.artifact_type == "validation_report"
                ),
                "unknown",
            ) if qa_artifacts else "skipped"
        )

        return PipelineResult(
            artifacts=all_artifacts,
            pm=pm_artifacts,
            architect=arch_artifacts,
            developer=dev_artifacts,
            qa=qa_artifacts,
            certification=certification,
        )

    async def run_spec_from_prd(
        self,
        prd_path: str,
        *,
        user_stories_path: str,
        artifact_dir: Path,
        context_overrides: dict[str, str] | None = None,
        on_phase_complete: Callable[[str, list[Artifact]], None] | None = None,
    ) -> PipelineResult:
        """Run pipeline from PRD: Architect -> Developer -> QA.

        Skips PM phase. The caller provides a PRD file and user stories file.
        The user stories file can contain any acceptance criteria, not
        necessarily PM-generated stories.

        Args:
            prd_path: Path to the PRD file.
            user_stories_path: Path to user stories / acceptance criteria file.
            artifact_dir: Root directory for all artifacts.
            context_overrides: Optional overrides for project context.
            on_phase_complete: Optional callback invoked after each phase with
                the phase name and its produced artifacts.

        Returns:
            PipelineResult with PM artifacts empty.
        """
        ctx = self._merge_context(context_overrides)
        prd_content = Path(prd_path).read_text()
        stories_content = Path(user_stories_path).read_text()

        # Architect phase — direct call, no handoff (cold start)
        arch_dir = artifact_dir / "architect"
        arch_dir.mkdir(parents=True, exist_ok=True)
        arch_context = SkillContext(
            artifact_dir=arch_dir,
            parameters={
                **ctx,
                "prd": prd_content,
                "prd_path": prd_path,
                "user_stories": stories_content,
                "user_stories_path": user_stories_path,
            },
            trace_id="pipeline",
        )
        arch_artifacts = await self._architect.run_spec_from_prd(arch_context)
        if on_phase_complete:
            on_phase_complete("architect", arch_artifacts)

        # Developer phase — receives handoff from Architect
        dev_dir = artifact_dir / "developer"
        dev_dir.mkdir(parents=True, exist_ok=True)
        dev_context = SkillContext(artifact_dir=dev_dir, parameters={}, trace_id="pipeline")

        dev_handoff = _get_handoff(self._developer, "architect")
        dev_artifacts = await self._developer.handle_handoff(dev_handoff, dev_context)
        if on_phase_complete:
            on_phase_complete("developer", dev_artifacts)

        # QA phase
        qa_dir = artifact_dir / "qa"
        qa_dir.mkdir(parents=True, exist_ok=True)
        qa_context = SkillContext(artifact_dir=qa_dir, parameters={}, trace_id="pipeline")

        qa_handoff = _get_handoff(self._qa, "developer")
        qa_artifacts = await self._qa.handle_handoff(qa_handoff, qa_context)
        if on_phase_complete:
            on_phase_complete("qa", qa_artifacts)

        all_artifacts = arch_artifacts + dev_artifacts + qa_artifacts
        certification = (
            next(
                (
                    a.metadata.get("certification", "unknown")
                    for a in qa_artifacts
                    if a.artifact_type == "validation_report"
                ),
                "unknown",
            ) if qa_artifacts else "skipped"
        )

        return PipelineResult(
            artifacts=all_artifacts,
            pm=[],
            architect=arch_artifacts,
            developer=dev_artifacts,
            qa=qa_artifacts,
            certification=certification,
        )

    async def run_plan_from_spec(  # noqa: PLR0913
        self,
        *,
        implementation_plan_path: str,
        tech_spec_path: str,
        artifact_dir: Path,
        user_stories_path: str | None = None,
        context_overrides: dict[str, str] | None = None,
        on_phase_complete: Callable[[str, list[Artifact]], None] | None = None,
    ) -> PipelineResult:
        """Run pipeline from spec: Developer -> QA.

        Skips PM and Architect phases. The caller provides implementation
        plan and tech spec files directly.

        Args:
            implementation_plan_path: Path to the implementation plan file.
            tech_spec_path: Path to the tech spec file.
            artifact_dir: Root directory for all artifacts.
            user_stories_path: Optional path to user stories file. If omitted,
                QA pre-flight will fail unless user_stories is in context_overrides.
            context_overrides: Optional overrides for project context.
            on_phase_complete: Optional callback invoked after each phase with
                the phase name and its produced artifacts.

        Returns:
            PipelineResult with PM and Architect artifacts empty.
        """
        ctx = self._merge_context(context_overrides)
        plan_content = Path(implementation_plan_path).read_text()
        spec_content = Path(tech_spec_path).read_text()

        # Build Developer context with content and paths for metadata forwarding
        dev_params: dict[str, str] = {
            **ctx,
            "implementation_plan": plan_content,
            "implementation_plan_path": implementation_plan_path,
            "tech_spec": spec_content,
            "tech_spec_path": tech_spec_path,
        }

        if user_stories_path:
            dev_params["user_stories"] = Path(user_stories_path).read_text()
            dev_params["user_stories_path"] = user_stories_path

        # Developer phase — direct call, no handoff (cold start)
        dev_dir = artifact_dir / "developer"
        dev_dir.mkdir(parents=True, exist_ok=True)
        dev_context = SkillContext(artifact_dir=dev_dir, parameters=dev_params, trace_id="pipeline")
        dev_artifacts = await self._developer.run_plan_from_spec(dev_context)
        if on_phase_complete:
            on_phase_complete("developer", dev_artifacts)

        # QA phase
        qa_dir = artifact_dir / "qa"
        qa_dir.mkdir(parents=True, exist_ok=True)
        qa_context = SkillContext(artifact_dir=qa_dir, parameters={}, trace_id="pipeline")

        qa_handoff = _get_handoff(self._qa, "developer")
        qa_artifacts = await self._qa.handle_handoff(qa_handoff, qa_context)
        if on_phase_complete:
            on_phase_complete("qa", qa_artifacts)

        all_artifacts = dev_artifacts + qa_artifacts
        certification = (
            next(
                (
                    a.metadata.get("certification", "unknown")
                    for a in qa_artifacts
                    if a.artifact_type == "validation_report"
                ),
                "unknown",
            ) if qa_artifacts else "skipped"
        )

        return PipelineResult(
            artifacts=all_artifacts,
            pm=[],
            architect=[],
            developer=dev_artifacts,
            qa=qa_artifacts,
            certification=certification,
        )
