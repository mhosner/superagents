"""Standalone CLI for superagents-sdlc pipelines."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from superagents_sdlc.skills.llm import LLMClient, StubLLMClient

if TYPE_CHECKING:
    from superagents_sdlc.skills.base import Artifact
    from superagents_sdlc.workflows.narrative import NarrativeWriter
    from superagents_sdlc.workflows.orchestrator import PipelineOrchestrator
    from superagents_sdlc.workflows.result import PipelineResult

# Named context files recognized by the loader.
_CONTEXT_FILES: dict[str, str] = {
    "product_context.md": "product_context",
    "goals_context.md": "goals_context",
    "personas_context.md": "personas_context",
}


def _load_context(context_dir: str | None) -> dict[str, str]:
    """Load context from named markdown files in a directory.

    Args:
        context_dir: Path to the context directory, or None for empty context.

    Returns:
        Dict mapping context keys to file contents.

    Raises:
        FileNotFoundError: If the directory does not exist.
    """
    if context_dir is None:
        return {}

    directory = Path(context_dir)
    if not directory.is_dir():
        msg = f"Context directory not found: {context_dir}"
        raise FileNotFoundError(msg)

    context: dict[str, str] = {}
    for filename, key in _CONTEXT_FILES.items():
        filepath = directory / filename
        if filepath.exists():
            context[key] = filepath.read_text()
    return context


def _build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser.

    Returns:
        Configured ArgumentParser with subcommands.
    """
    # Shared global flags inherited by every subcommand.
    shared = argparse.ArgumentParser(add_help=False)
    shared.add_argument(
        "--context-dir",
        default=None,
        help="Directory with named context .md files (optional).",
    )
    shared.add_argument(
        "--autonomy-level",
        type=int,
        default=3,
        choices=[1, 2, 3],
        help="Policy engine autonomy level (default: 3).",
    )
    shared.add_argument(
        "--model",
        default="claude-sonnet-4-6",
        help="Anthropic model to use (default: claude-sonnet-4-6).",
    )
    verbosity = shared.add_mutually_exclusive_group()
    verbosity.add_argument(
        "--quiet", action="store_true", help="Suppress all output except errors."
    )
    verbosity.add_argument(
        "--interactive",
        "-i",
        action="store_true",
        help="Enable interactive review loop.",
    )
    shared.add_argument(
        "--json",
        action="store_true",
        dest="json",
        help="Dump PipelineResult as JSON to stdout.",
    )
    shared.add_argument(
        "--stub",
        action="store_true",
        help="Use StubLLMClient instead of Anthropic (development testing only).",
    )

    parser = argparse.ArgumentParser(
        prog="superagents-sdlc",
        description="Run SDLC persona pipelines from the command line.",
        parents=[shared],
    )

    # Subcommands — each inherits global flags via parents=[shared].
    subparsers = parser.add_subparsers(dest="command", required=True)

    # idea-to-code
    idea_parser = subparsers.add_parser(
        "idea-to-code",
        help="Run full pipeline: PM -> Arch -> Dev -> QA.",
        parents=[shared],
    )
    idea_parser.add_argument("idea", help="Feature idea or description.")
    idea_parser.add_argument(
        "--output-dir", required=True, help="Root directory for artifact output."
    )

    # spec-from-prd
    spec_parser = subparsers.add_parser(
        "spec-from-prd",
        help="Run from PRD: Arch -> Dev -> QA.",
        parents=[shared],
    )
    spec_parser.add_argument("prd_path", help="Path to PRD file.")
    spec_parser.add_argument("--user-stories", required=True, help="Path to user stories file.")
    spec_parser.add_argument(
        "--output-dir", required=True, help="Root directory for artifact output."
    )

    # plan-from-spec
    plan_parser = subparsers.add_parser(
        "plan-from-spec",
        help="Run from spec: Dev -> QA.",
        parents=[shared],
    )
    plan_parser.add_argument("--plan", required=True, help="Path to implementation plan file.")
    plan_parser.add_argument("--spec", required=True, help="Path to tech spec file.")
    plan_parser.add_argument(
        "--user-stories", default=None, help="Path to user stories file (optional)."
    )
    plan_parser.add_argument(
        "--output-dir", required=True, help="Root directory for artifact output."
    )

    return parser


def _stub_responses() -> dict[str, str]:
    """Canned LLM responses for ``--stub`` mode.

    Produces valid artifacts for all nine skills across four personas.
    For development testing only — content is generic fixtures.

    Returns:
        Map of prompt substrings to stub responses.
    """
    # WARNING: Key ordering matters — StubLLMClient returns the first match.
    # QA keys must come before Architect/Developer keys because QA prompts
    # contain substrings that would collide with Architect/Developer keys.
    return {
        # PM skills
        "## Items to prioritize\n": "## Rankings\n1. Feature - RICE: 42",
        "## Idea / feature to spec\n": "# PRD: Feature\n## Problem\nNone",
        "## Feature description\n": (
            "## Story 1\nAs a user, I want feature\n"
            "### Acceptance Criteria\nGiven X\nWhen Y\nThen Z"
        ),
        # QA skills — must come before Architect/Developer keys
        "## Compliance report\n": (
            "# Validation Report\n## Executive Summary\nDone.\n"
            "## Certification\nNEEDS WORK"
        ),
        "## Plan structure analysis\n": (
            "## Compliance Check\n| Feature | PASS |\n"
            "## Summary\nTotal: 1 | Pass: 1\nOverall: NEEDS WORK"
        ),
        # FindingsRouter — must come before other keys containing "## Validation report"
        "## Validation report\n": json.dumps({
            "certification": "NEEDS WORK",
            "total_findings": 1,
            "routing": {
                "product_manager": [],
                "architect": [{
                    "id": "RF-1",
                    "summary": "Minor spec gap",
                    "detail": "Detail text",
                    "affected_artifact": "tech_spec",
                    "related_requirements": [{"id": "AC-1", "text": "Criterion"}],
                }],
                "developer": [],
            },
        }),
        # Architect skills
        "## PRD\n": "# Tech Spec\n## Architecture\nSimple",
        "## Technical specification\n": "## Tasks\n1. Build it",
        # Developer skills
        "## Implementation plan\n": (
            "### Task 1: Feature\n\n"
            "- [ ] **Step 1: Write test**\nRun: `pytest -v`\n\n"
            "- [ ] **Step 2: Implement**\n"
        ),
    }


def _serialize_result(result: PipelineResult) -> str:
    """Serialize PipelineResult to JSON string.

    Args:
        result: Pipeline result to serialize.

    Returns:
        JSON string with indentation.
    """
    def _dump_artifacts(artifacts: list[Artifact]) -> list[dict[str, object]]:
        return [a.model_dump() for a in artifacts]

    data = {
        "certification": result.certification,
        "artifacts": _dump_artifacts(result.artifacts),
        "pm": _dump_artifacts(result.pm),
        "architect": _dump_artifacts(result.architect),
        "developer": _dump_artifacts(result.developer),
        "qa": _dump_artifacts(result.qa),
    }
    return json.dumps(data, indent=2)


def _make_phase_callback(
    *,
    quiet: bool,
    narrative: NarrativeWriter,
    seen_phases: list[str],
    retry_state: dict[str, bool],
) -> callable:
    """Build the on_phase callback used by pipeline runs.

    Args:
        quiet: Whether to suppress stdout output.
        narrative: NarrativeWriter instance.
        seen_phases: Mutable list tracking phase names already seen.
        retry_state: Mutable dict with a "started" key for retry tracking.

    Returns:
        Callback function for on_phase_complete.
    """
    def on_phase(name: str, artifacts: list[Artifact]) -> None:
        # Detect automated retry: a repeated phase name means retry started
        if name in seen_phases and not retry_state["started"]:
            retry_state["started"] = True
            narrative.start_pass(2, "Automated Retry")
        seen_phases.append(name)

        if not quiet:
            count = len(artifacts)
            label = "artifact" if count == 1 else "artifacts"
            print(f"{name.upper()} phase... done ({count} {label})")  # noqa: T201

        # Extract certification and findings for QA phases
        certification = ""
        findings: list[str] | None = None
        if name == "qa":
            for a in artifacts:
                if a.artifact_type == "validation_report":
                    certification = a.metadata.get("certification", "")
                elif a.artifact_type == "routing_manifest":
                    _extract_findings(a, findings)

        narrative.record_phase(
            name, artifacts, certification=certification, findings_summary=findings
        )

    return on_phase


def _extract_findings(artifact: Artifact, findings: list[str] | None) -> list[str] | None:
    """Extract findings from a routing manifest artifact.

    Args:
        artifact: Routing manifest artifact.
        findings: Existing findings list (mutated in place), or None.

    Returns:
        Updated findings list, or None if extraction failed.
    """
    try:
        manifest = json.loads(Path(artifact.path).read_text())
    except (json.JSONDecodeError, KeyError):
        return findings
    else:
        result = findings if findings is not None else []
        for _persona, items in manifest.get("routing", {}).items():
            for item in items:
                result.append(f"{item['id']}: {item['summary']} [{_persona}]")
        return result


async def _async_input(prompt: str = "") -> str:
    """Read a line from stdin without blocking the event loop.

    Args:
        prompt: Optional prompt string.

    Returns:
        The stripped input line.
    """
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, lambda: input(prompt))


async def _interactive_loop(
    *,
    result: PipelineResult,
    orchestrator: PipelineOrchestrator,
    narrative: NarrativeWriter,
    output_dir: Path,
    on_phase: callable,
) -> None:
    """Run the interactive approve/revise/quit loop.

    Args:
        result: Initial pipeline result.
        orchestrator: Pipeline orchestrator for revisions.
        narrative: NarrativeWriter for recording feedback.
        output_dir: Artifact output directory.
        on_phase: Phase callback for revision runs.
    """
    pass_number = 2 if result.retry_attempted else 1

    while True:
        print(f"\nCertification: {result.certification}")  # noqa: T201
        print(f"\nNarrative: {output_dir}/pipeline_narrative.md")  # noqa: T201
        print(f"Artifacts: {output_dir}/")  # noqa: T201

        choice = (await _async_input("\napprove / revise / quit (a/r/q)> ")).strip().lower()

        if choice in ("a", "approve"):
            narrative.record_final_result(result.certification, pass_number)
            print("Approved. Final artifacts written.")  # noqa: T201
            break
        if choice in ("q", "quit"):
            narrative.record_final_result(result.certification, pass_number)
            print(f"Quit. Certification: {result.certification}")  # noqa: T201
            break
        if choice in ("r", "revise"):
            print("Enter feedback (empty line to finish):")  # noqa: T201
            lines: list[str] = []
            while True:
                line = await _async_input()
                if not line:
                    break
                lines.append(line)
            feedback = "\n".join(lines)

            if feedback:
                narrative.record_human_feedback(feedback)
                pass_number += 1
                narrative.start_pass(pass_number, "Human Revision")
                result = await orchestrator.run_human_revision(
                    feedback=feedback,
                    result=result,
                    artifact_dir=output_dir,
                    on_phase_complete=on_phase,
                )
            else:
                print("No feedback provided. Try again.")  # noqa: T201
        else:
            print("Invalid choice. Enter a, r, or q.")  # noqa: T201


async def _run(args: argparse.Namespace) -> int:
    """Run the pipeline based on parsed arguments.

    Args:
        args: Parsed CLI arguments.

    Returns:
        Exit code (0 success, 1 error).
    """
    from superagents_sdlc.policy.config import PolicyConfig  # noqa: PLC0415
    from superagents_sdlc.policy.engine import PolicyEngine  # noqa: PLC0415
    from superagents_sdlc.policy.gates import AutoApprovalGate  # noqa: PLC0415
    from superagents_sdlc.workflows.narrative import NarrativeWriter  # noqa: PLC0415
    from superagents_sdlc.workflows.orchestrator import PipelineOrchestrator  # noqa: PLC0415

    # Load context; provide empty defaults so PM skills pass validation.
    context = _load_context(args.context_dir)
    context.setdefault("product_context", "")
    context.setdefault("goals_context", "")
    context.setdefault("personas_context", "")

    # Build LLM client
    if args.stub:
        llm: LLMClient = StubLLMClient(responses=_stub_responses())
    else:
        from superagents_sdlc.skills.llm import AnthropicLLMClient  # noqa: PLC0415

        llm = AnthropicLLMClient(model=args.model)

    # Build policy engine
    config = PolicyConfig(autonomy_level=args.autonomy_level)
    engine = PolicyEngine(config=config, gate=AutoApprovalGate())

    # Build orchestrator
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    orchestrator = PipelineOrchestrator(llm=llm, policy_engine=engine, context=context)

    # Set up narrative writer
    narrative = NarrativeWriter(
        output_dir, f'{args.command} "{getattr(args, "idea", "pipeline")}"'
    )
    narrative.start_pass(1, "Initial Run")

    # Build phase callback
    seen_phases: list[str] = []
    retry_state: dict[str, bool] = {"started": False}
    on_phase = _make_phase_callback(
        quiet=args.quiet, narrative=narrative,
        seen_phases=seen_phases, retry_state=retry_state,
    )

    # Run the appropriate pipeline
    result = await _run_pipeline(args, orchestrator, output_dir, on_phase)

    # Interactive review loop or finalize
    if args.interactive:
        await _interactive_loop(
            result=result,
            orchestrator=orchestrator,
            narrative=narrative,
            output_dir=output_dir,
            on_phase=on_phase,
        )
    else:
        pass_number = 2 if result.retry_attempted else 1
        narrative.record_final_result(result.certification, pass_number)

    # Output
    if not args.quiet:
        print(f"\nCertification: {result.certification}")  # noqa: T201
        print(f"Artifacts written to {args.output_dir}")  # noqa: T201

    if args.json:
        print(_serialize_result(result))  # noqa: T201

    return 0


async def _run_pipeline(
    args: argparse.Namespace,
    orchestrator: PipelineOrchestrator,
    output_dir: Path,
    on_phase: callable,
) -> PipelineResult:
    """Dispatch to the appropriate pipeline method.

    Args:
        args: Parsed CLI arguments.
        orchestrator: Pipeline orchestrator.
        output_dir: Artifact output directory.
        on_phase: Phase completion callback.

    Returns:
        Pipeline result.
    """
    if args.command == "idea-to-code":
        return await orchestrator.run_idea_to_code(
            args.idea,
            artifact_dir=output_dir,
            on_phase_complete=on_phase,
        )
    if args.command == "spec-from-prd":
        return await orchestrator.run_spec_from_prd(
            args.prd_path,
            user_stories_path=args.user_stories,
            artifact_dir=output_dir,
            on_phase_complete=on_phase,
        )
    # plan-from-spec
    return await orchestrator.run_plan_from_spec(
        implementation_plan_path=args.plan,
        tech_spec_path=args.spec,
        artifact_dir=output_dir,
        user_stories_path=args.user_stories,
        on_phase_complete=on_phase,
    )


def main() -> None:
    """CLI entry point."""
    parser = _build_parser()
    args = parser.parse_args()

    try:
        code = asyncio.run(_run(args))
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)  # noqa: T201
        sys.exit(1)
    except KeyboardInterrupt:
        sys.exit(130)
    else:
        sys.exit(code)


if __name__ == "__main__":
    main()
