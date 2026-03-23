"""Pipeline orchestrator — named workflow methods for persona sequencing."""

from __future__ import annotations

import json
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
        fast_llm: LLMClient | None = None,
        policy_engine: PolicyEngine,
        context: dict[str, str],
    ) -> None:
        """Initialize with LLM, policy engine, and project context.

        Args:
            llm: Strong LLM for PM and QA reasoning tasks.
            fast_llm: Optional cheaper LLM for Architect.
                Falls back to llm when not provided.
            policy_engine: Policy engine for handoff evaluation.
            context: Project-level context files (product_context, etc.).
        """
        effective_fast = fast_llm or llm
        self._context = dict(context)
        self._retry_context: dict[str, str] = {}
        self._registry = PersonaRegistry()
        self._transport = InProcessTransport(registry=self._registry)

        self._pm = ProductManagerPersona(
            llm=llm, policy_engine=policy_engine, transport=self._transport
        )
        self._architect = ArchitectPersona(
            llm=effective_fast, policy_engine=policy_engine, transport=self._transport
        )
        self._developer = DeveloperPersona(
            llm=llm, policy_engine=policy_engine, transport=self._transport
        )
        self._qa = QAPersona(
            llm=llm, fast_llm=fast_llm, policy_engine=policy_engine,
            transport=self._transport,
        )

        self._registry.register(self._pm)
        self._registry.register(self._architect)
        self._registry.register(self._developer)
        self._registry.register(self._qa)

    def _set_skill_callback(
        self,
        callback: Callable[[str, str, Artifact], None] | None,
    ) -> None:
        """Set the on_skill_complete callback on all personas.

        Args:
            callback: Callback or None to clear.
        """
        for persona in (self._pm, self._architect, self._developer, self._qa):
            persona.on_skill_complete = callback

    def _merge_context(self, overrides: dict[str, str] | None = None) -> dict[str, str]:
        """Merge base context with optional call-time overrides.

        Args:
            overrides: Keys to override in the base context.

        Returns:
            Merged context dict.
        """
        return {**self._context, **(overrides or {})}

    async def run_idea_to_code(  # noqa: PLR0913
        self,
        idea: str,
        *,
        artifact_dir: Path,
        context_overrides: dict[str, str] | None = None,
        on_phase_complete: Callable[[str, list[Artifact]], None] | None = None,
        on_skill_complete: Callable[[str, str, Artifact], None] | None = None,
        on_qa_complete: Callable[[str, list[Artifact]], None] | None = None,
        on_findings_routed: Callable[[dict, list[str]], None] | None = None,
        on_retry_start: Callable[[str, dict], None] | None = None,
    ) -> PipelineResult:
        """Run full pipeline: PM -> Architect -> Developer -> QA.

        Args:
            idea: Feature idea or description.
            artifact_dir: Root directory for all artifacts.
            context_overrides: Optional overrides for project context.
            on_phase_complete: Optional callback after each phase (name, artifacts).
            on_skill_complete: Optional callback after each skill (persona, skill, artifact).
            on_qa_complete: Optional callback after QA (certification, artifacts).
            on_findings_routed: Optional callback after routing (routing dict, cascade list).
            on_retry_start: Optional callback at retry start (pre-certification, routing dict).

        Returns:
            PipelineResult with all artifacts grouped by persona.
        """
        self._retry_context = {}
        ctx = self._merge_context(context_overrides)

        # Wire skill-level callback to all personas
        self._set_skill_callback(on_skill_complete)

        # PM phase
        pm_dir = artifact_dir / "pm"
        pm_dir.mkdir(parents=True, exist_ok=True)
        pm_context = SkillContext(artifact_dir=pm_dir, parameters=dict(ctx), trace_id="pipeline")
        pm_artifacts = await self._pm.run_idea_to_sprint(idea, pm_context)
        if on_phase_complete:
            on_phase_complete("pm", pm_artifacts)

        # Capture user stories for retry context
        stories_artifact = _find_artifact(pm_artifacts, "user_story")
        self._retry_context["user_stories"] = Path(stories_artifact.path).read_text()

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

        if on_qa_complete:
            on_qa_complete(certification, qa_artifacts)

        result = PipelineResult(
            artifacts=all_artifacts,
            pm=pm_artifacts,
            architect=arch_artifacts,
            developer=dev_artifacts,
            qa=qa_artifacts,
            certification=certification,
        )

        # Retry pass if QA found issues
        if certification == "NEEDS WORK":
            result = await self._run_retry_pass(
                result=result,
                artifact_dir=artifact_dir,
                on_phase_complete=on_phase_complete,
                on_qa_complete=on_qa_complete,
                on_findings_routed=on_findings_routed,
                on_retry_start=on_retry_start,
            )

        return result

    async def run_spec_from_prd(  # noqa: PLR0913
        self,
        prd_path: str,
        *,
        user_stories_path: str,
        artifact_dir: Path,
        context_overrides: dict[str, str] | None = None,
        on_phase_complete: Callable[[str, list[Artifact]], None] | None = None,
        on_skill_complete: Callable[[str, str, Artifact], None] | None = None,
        on_qa_complete: Callable[[str, list[Artifact]], None] | None = None,
        on_findings_routed: Callable[[dict, list[str]], None] | None = None,
        on_retry_start: Callable[[str, dict], None] | None = None,
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
        self._retry_context = {}
        self._set_skill_callback(on_skill_complete)
        ctx = self._merge_context(context_overrides)
        prd_content = Path(prd_path).read_text()
        stories_content = Path(user_stories_path).read_text()
        self._retry_context["user_stories"] = stories_content

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

        if on_qa_complete:
            on_qa_complete(certification, qa_artifacts)

        result = PipelineResult(
            artifacts=all_artifacts,
            pm=[],
            architect=arch_artifacts,
            developer=dev_artifacts,
            qa=qa_artifacts,
            certification=certification,
        )

        # Retry pass if QA found issues
        if certification == "NEEDS WORK":
            result = await self._run_retry_pass(
                result=result,
                artifact_dir=artifact_dir,
                on_phase_complete=on_phase_complete,
                on_qa_complete=on_qa_complete,
                on_findings_routed=on_findings_routed,
                on_retry_start=on_retry_start,
            )

        return result

    async def run_plan_from_spec(  # noqa: PLR0913
        self,
        *,
        implementation_plan_path: str,
        tech_spec_path: str,
        artifact_dir: Path,
        user_stories_path: str | None = None,
        context_overrides: dict[str, str] | None = None,
        on_phase_complete: Callable[[str, list[Artifact]], None] | None = None,
        on_skill_complete: Callable[[str, str, Artifact], None] | None = None,
        on_qa_complete: Callable[[str, list[Artifact]], None] | None = None,
        on_findings_routed: Callable[[dict, list[str]], None] | None = None,
        on_retry_start: Callable[[str, dict], None] | None = None,
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
            on_phase_complete: Optional callback after each phase (name, artifacts).
            on_skill_complete: Optional callback after each skill (persona, skill, artifact).
            on_qa_complete: Optional callback after QA (certification, artifacts).
            on_findings_routed: Optional callback after routing (routing dict, cascade list).
            on_retry_start: Optional callback at retry start (pre-certification, routing dict).

        Returns:
            PipelineResult with PM and Architect artifacts empty.
        """
        self._retry_context = {}
        self._set_skill_callback(on_skill_complete)
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
            self._retry_context["user_stories"] = dev_params["user_stories"]

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

        if on_qa_complete:
            on_qa_complete(certification, qa_artifacts)

        result = PipelineResult(
            artifacts=all_artifacts,
            pm=[],
            architect=[],
            developer=dev_artifacts,
            qa=qa_artifacts,
            certification=certification,
        )

        # Retry pass if QA found issues
        if certification == "NEEDS WORK":
            result = await self._run_retry_pass(
                result=result,
                artifact_dir=artifact_dir,
                on_phase_complete=on_phase_complete,
                on_qa_complete=on_qa_complete,
                on_findings_routed=on_findings_routed,
                on_retry_start=on_retry_start,
            )

        return result

    async def run_human_revision(
        self,
        *,
        feedback: str,
        result: PipelineResult,
        artifact_dir: Path,
        on_phase_complete: Callable[[str, list[Artifact]], None] | None = None,
    ) -> PipelineResult:
        """Run a human-directed revision pass.

        Wraps feedback into a pseudo-validation-report, runs FindingsRouter
        to classify it to the responsible persona, then calls _run_retry_pass
        with the routing manifest.

        Note: This method mutates ``result`` in place and returns it.

        Args:
            feedback: Human revision feedback text.
            result: Current pipeline result to revise.
            artifact_dir: Root directory for artifacts.
            on_phase_complete: Optional progress callback.

        Returns:
            Updated PipelineResult after revision pass.
        """
        pseudo_report = (
            "## Required Fixes\n"
            f"- RF-H1: {feedback}\n\n"
            "## Certification\n"
            "NEEDS WORK"
        )

        # Get user stories — try retry context first, then fall back to PM artifacts.
        user_stories = self._retry_context.get("user_stories", "")
        if not user_stories and result.pm:
            for a in result.pm:
                if a.artifact_type == "user_story":
                    path = Path(a.path)
                    if path.exists():
                        user_stories = path.read_text()
                    break

        # Build SkillContext for FindingsRouter
        qa_dir = artifact_dir / "qa"
        qa_dir.mkdir(parents=True, exist_ok=True)
        context = SkillContext(
            artifact_dir=qa_dir,
            parameters={
                "validation_report": pseudo_report,
                "user_stories": user_stories,
            },
            trace_id="pipeline-human-revision",
        )

        # Route the human feedback to the responsible persona(s)
        routing_artifact = await self._qa.execute_skill("findings_router", context)

        # Inject the routing manifest into result.qa so _run_retry_pass can find
        # and read it. After _run_retry_pass re-runs QA, result.qa is overwritten
        # with fresh QA output (which includes a new manifest from the automated
        # QA pass). The injected manifest is consumed then replaced — this is
        # intentional, not dead code.
        result.qa = [
            a for a in result.qa if a.artifact_type != "routing_manifest"
        ] + [routing_artifact]

        return await self._run_retry_pass(
            result=result,
            artifact_dir=artifact_dir,
            on_phase_complete=on_phase_complete,
        )

    # Canonical persona order for cascade logic.
    _PERSONA_ORDER = ("product_manager", "architect", "developer")

    async def _run_retry_pass(  # noqa: C901, PLR0912, PLR0915
        self,
        *,
        result: PipelineResult,
        artifact_dir: Path,
        on_phase_complete: Callable[[str, list[Artifact]], None] | None = None,
        on_qa_complete: Callable[[str, list[Artifact]], None] | None = None,
        on_findings_routed: Callable[[dict, list[str]], None] | None = None,
        on_retry_start: Callable[[str, dict], None] | None = None,
    ) -> PipelineResult:
        """Re-invoke personas tagged in the routing manifest, then re-run QA.

        Reads the routing manifest from the QA artifacts, determines which
        personas need revision (including downstream cascade), injects
        findings into context, and re-runs QA on the revised artifacts.

        Note: This method mutates ``result`` in place and returns it.

        Args:
            result: The initial pipeline result (must have QA artifacts).
            artifact_dir: Root directory for artifacts (same as initial run).
            on_phase_complete: Optional progress callback.
            on_qa_complete: Optional callback after QA re-run.
            on_findings_routed: Optional callback after routing is determined.
            on_retry_start: Optional callback at retry start.

        Returns:
            Updated PipelineResult with retry artifacts overwriting originals.
        """
        # Find routing manifest
        manifest_artifact = None
        for a in result.qa:
            if a.artifact_type == "routing_manifest":
                manifest_artifact = a
                break

        if manifest_artifact is None:
            return result

        manifest = json.loads(Path(manifest_artifact.path).read_text())
        routing = manifest.get("routing", {})

        # Determine which personas have findings
        tagged = {
            persona for persona in self._PERSONA_ORDER
            if routing.get(persona)
        }

        if not tagged:
            return result

        # Determine which personas were in the initial pipeline
        active_personas = set()
        if result.pm:
            active_personas.add("product_manager")
        if result.architect:
            active_personas.add("architect")
        if result.developer:
            active_personas.add("developer")

        # Cascade: if any persona is tagged, all downstream also re-run
        # but only among personas that were active in the initial pipeline
        cascade = set()
        triggered = False
        for persona in self._PERSONA_ORDER:
            if persona in tagged:
                triggered = True
            if triggered and persona in active_personas:
                cascade.add(persona)

        # Build ordered cascade list for callbacks
        cascade_list = [p for p in self._PERSONA_ORDER if p in cascade]

        # Fire narrative callbacks
        if on_findings_routed:
            on_findings_routed(routing, cascade_list)
        if on_retry_start:
            on_retry_start(result.certification, routing)

        # Save pre-retry state
        result.pre_retry_certification = result.certification
        result.retry_attempted = True

        # Collect all artifact contents for revision context.
        def _read_artifact(artifacts: list[Artifact], atype: str) -> str:
            for a in artifacts:
                if a.artifact_type == atype:
                    path = Path(a.path)
                    if path.exists():
                        return path.read_text()
            return ""

        # Re-invoke personas in order.
        # Uses execute_skill() directly instead of persona workflow methods
        # (run_spec_from_prd, run_plan_from_spec) to avoid re-triggering
        # handoffs on retry. The retry pass manages its own context wiring.
        if "product_manager" in cascade:
            pm_dir = artifact_dir / "pm"
            pm_findings = json.dumps(routing.get("product_manager", []))

            # Re-run PRD
            prd_content = _read_artifact(result.pm, "prd")
            pm_context = SkillContext(
                artifact_dir=pm_dir,
                parameters={
                    **self._context,
                    "idea": "Revision pass",
                    "revision_findings": pm_findings,
                    "previous_prd": prd_content,
                },
                trace_id="pipeline-retry",
            )
            pm_prd = await self._pm.execute_skill("prd_generator", pm_context)

            # Re-run user stories
            stories_content = _read_artifact(result.pm, "user_story")
            pm_context.parameters["previous_user_story"] = stories_content
            pm_context.parameters["feature_description"] = Path(pm_prd.path).read_text()
            pm_stories = await self._pm.execute_skill("user_story_writer", pm_context)

            result.pm = [
                _find_artifact(result.pm, "backlog"),
                pm_prd,
                pm_stories,
            ]
            if on_phase_complete:
                on_phase_complete("pm", result.pm)

        if "architect" in cascade:
            arch_dir = artifact_dir / "architect"
            arch_findings = json.dumps(routing.get("architect", []))
            prev_spec = _read_artifact(result.architect, "tech_spec")
            prev_plan = _read_artifact(result.architect, "implementation_plan")

            # Read current upstream artifacts
            prd_content = _read_artifact(result.pm, "prd") if result.pm else ""
            stories_content = _read_artifact(result.pm, "user_story") if result.pm else ""

            arch_context = SkillContext(
                artifact_dir=arch_dir,
                parameters={
                    "prd": prd_content or self._retry_context.get("prd", ""),
                    "user_stories": stories_content or self._retry_context.get("user_stories", ""),
                    "product_context": self._context.get("product_context", ""),
                    "revision_findings": arch_findings,
                    "previous_tech_spec": prev_spec,
                },
                trace_id="pipeline-retry",
            )
            new_spec = await self._architect.execute_skill("tech_spec_writer", arch_context)
            arch_context.parameters["tech_spec"] = Path(new_spec.path).read_text()
            arch_context.parameters["previous_implementation_plan"] = prev_plan
            new_plan = await self._architect.execute_skill("implementation_planner", arch_context)

            result.architect = [new_spec, new_plan]
            if on_phase_complete:
                on_phase_complete("architect", result.architect)

        if "developer" in cascade:
            dev_dir = artifact_dir / "developer"
            dev_findings = json.dumps(routing.get("developer", []))

            prev_code = _read_artifact(result.developer, "code")

            # Read current upstream artifacts
            spec_content = (
                _read_artifact(result.architect, "tech_spec") if result.architect else ""
            )
            plan_content = (
                _read_artifact(result.architect, "implementation_plan")
                if result.architect
                else ""
            )

            dev_context = SkillContext(
                artifact_dir=dev_dir,
                parameters={
                    "implementation_plan": plan_content,
                    "tech_spec": spec_content,
                    "revision_findings": dev_findings,
                    "previous_code": prev_code,
                },
                trace_id="pipeline-retry",
            )

            # Forward user stories for downstream QA
            stories_content = (
                _read_artifact(result.pm, "user_story") if result.pm
                else self._retry_context.get("user_stories", "")
            )
            if stories_content:
                dev_context.parameters["user_stories"] = stories_content

            new_code = await self._developer.execute_skill("code_planner", dev_context)

            result.developer = [new_code]
            if on_phase_complete:
                on_phase_complete("developer", result.developer)

        # Re-run QA on revised artifacts
        qa_dir = artifact_dir / "qa"

        code_content = _read_artifact(result.developer, "code")
        spec_content = (
            _read_artifact(result.architect, "tech_spec") if result.architect else ""
        )
        stories_content = _read_artifact(result.pm, "user_story") if result.pm else ""

        qa_context = SkillContext(
            artifact_dir=qa_dir,
            parameters={
                "code_plan": code_content,
                "tech_spec": spec_content,
                "user_stories": (
                    stories_content
                    or self._retry_context.get("user_stories", "")
                ),
            },
            trace_id="pipeline-retry",
        )

        # Add optional context
        plan_content = (
            _read_artifact(result.architect, "implementation_plan")
            if result.architect
            else ""
        )
        if plan_content:
            qa_context.parameters["implementation_plan"] = plan_content
        prd_content = _read_artifact(result.pm, "prd") if result.pm else ""
        if prd_content:
            qa_context.parameters["prd"] = prd_content

        qa_artifacts = await self._qa.run_validation(qa_context)
        result.qa = qa_artifacts
        if on_phase_complete:
            on_phase_complete("qa", qa_artifacts)

        # Update certification and rebuild artifacts list
        certification = (
            next(
                (
                    a.metadata.get("certification", "unknown")
                    for a in qa_artifacts
                    if a.artifact_type == "validation_report"
                ),
                "unknown",
            ) if qa_artifacts else "unknown"
        )
        result.certification = certification

        if on_qa_complete:
            on_qa_complete(certification, qa_artifacts)

        all_artifacts = result.pm + result.architect + result.developer + result.qa
        result.artifacts = all_artifacts

        return result
