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
        "--max-tokens",
        type=int,
        default=16384,
        help="Max tokens for LLM responses (default: 16384).",
    )
    shared.add_argument(
        "--fast-model",
        default=None,
        help=(
            "Cheaper model for Architect/Developer/FindingsRouter "
            "(default: uses --model for all)."
        ),
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
    idea_parser.add_argument(
        "--brief",
        default=None,
        help="Path to a design brief file (from brainstorm command).",
    )
    idea_parser.add_argument(
        "--codebase-context",
        default=None,
        help="Path to a file with codebase context.",
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

    # brainstorm
    brainstorm_parser = subparsers.add_parser(
        "brainstorm",
        help="Interactive brainstorming session to build a design brief.",
        parents=[shared],
    )
    brainstorm_parser.add_argument("idea", help="Feature idea or description.")
    brainstorm_parser.add_argument(
        "--codebase-context",
        default=None,
        help="Path to a file with codebase context (e.g., CLAUDE.md).",
    )
    brainstorm_parser.add_argument(
        "--output-dir",
        default=None,
        help="Directory to write the design brief (optional).",
    )

    return parser


class _BrainstormQuit(Exception):
    """Raised when user quits the brainstorm session."""


def _brainstorm_stub_responses() -> dict[str, str]:
    """Canned LLM responses for brainstorm ``--stub`` mode.

    For development testing only — content is generic fixtures.

    Returns:
        Map of prompt substrings to stub responses.
    """
    return {
        # WARNING: key ordering matters — StubLLMClient returns first match.
        # Synthesize must come before section keys since section text appears
        # in synthesize prompt.
        "Synthesize all": "# Design Brief\nStub design brief for testing.",
        # Confidence assessment — must come before question prompt keys
        "rate the readiness": json.dumps({
            "sections": {
                "problem_statement": {"readiness": "high", "evidence": "clear"},
                "users_and_personas": {"readiness": "high", "evidence": "clear"},
                "requirements": {"readiness": "high", "evidence": "clear"},
                "acceptance_criteria": {"readiness": "high", "evidence": "clear"},
                "scope_boundaries": {"readiness": "high", "evidence": "clear"},
                "technical_constraints": {"readiness": "high", "evidence": "clear"},
            },
            "gaps": [],
            "recommendation": "ready",
        }),
        "## Gaps to address": (
            '{"questions": [{"question": "Who are the target users?",'
            ' "options": ["developers", "PMs", "both"],'
            ' "targets_section": "users_and_personas"}]}'
        ),
        "Propose 2-3": (
            '[{"name": "Simple", "description": "Minimal viable approach",'
            ' "tradeoffs": "Less flexible but ships faster"}]'
        ),
        "Problem Statement": "## Problem Statement & Goals\nStub problem statement.",
        "Target Users": "## Target Users & Personas\nStub users section.",
        "Requirements": "## Requirements & User Stories\nStub requirements.",
        "Acceptance Criteria": "## Acceptance Criteria\nStub criteria.",
        "Scope Boundaries": "## Scope Boundaries\nStub scope.",
        "Technical Constraints": "## Technical Constraints\nStub constraints.",
    }


async def _handle_brainstorm_interrupt(payload: dict, *, quiet: bool = False) -> str:
    """Handle a brainstorm interrupt by prompting the user.

    Args:
        payload: Interrupt payload with type and data.
        quiet: If True, suppress output and return defaults.

    Returns:
        User's response string.

    Raises:
        _BrainstormQuit: If user types 'q' or 'quit'.
    """
    interrupt_type = payload["type"]

    if interrupt_type == "questions":
        questions = payload.get("questions", [])
        if not quiet:
            confidence = payload.get("confidence", 0)
            round_num = payload.get("round", 0)
            print(  # noqa: T201
                f"\nRound {round_num} | Confidence: {confidence}% | "
                f"Threshold: 80%"
            )
        answers = []
        for i, q in enumerate(questions, 1):
            if not quiet:
                target = q.get("targets_section", "")
                target_label = f" (targets: {target})" if target else ""
                print(f"\nQuestion {i} of {len(questions)}{target_label}:")  # noqa: T201
                print(f"  {q['question']}")  # noqa: T201
                if q.get("options"):
                    from superagents_sdlc.brainstorm.nodes import _clean_option  # noqa: PLC0415

                    for j, opt in enumerate(q["options"], 1):
                        print(f"    {j}. {_clean_option(opt)}")  # noqa: T201
                print("  (type 'q' to quit)")  # noqa: T201
            response = await _async_input("> ")
            if response.strip().lower() in ("q", "quit"):
                raise _BrainstormQuit
            answers.append(response)
        return answers

    # Legacy single-question format
    if interrupt_type == "question":
        if not quiet:
            print(f"\n{payload['question']}")  # noqa: T201
            if payload.get("options"):
                from superagents_sdlc.brainstorm.nodes import _clean_option  # noqa: PLC0415

                for i, opt in enumerate(payload["options"], 1):
                    print(f"  {i}. {_clean_option(opt)}")  # noqa: T201
            print("  (type 'q' to quit)")  # noqa: T201
        response = await _async_input("> ")
        if response.strip().lower() in ("q", "quit"):
            raise _BrainstormQuit
        return response

    if interrupt_type == "confidence_assessment":
        if not quiet:
            confidence = payload.get("confidence", 0)
            threshold = payload.get("threshold", 80)
            print(f"\nConfidence Assessment: {confidence}% (threshold: {threshold}%)")  # noqa: T201
            for section, info in payload.get("sections", {}).items():
                readiness = info.get("readiness", "?")
                evidence = info.get("evidence", "")
                markers = {"high": "✓", "medium": "~", "low": "✗"}
                marker = markers.get(readiness, "?")
                print(f"  {marker} {section}: {readiness.upper()} — {evidence}")  # noqa: T201
            if payload.get("gaps"):
                print("\nGaps:")  # noqa: T201
                for gap in payload["gaps"]:
                    print(f"  - {gap['section']}: {gap['description']}")  # noqa: T201
            print("\n  (c)ontinue / (d)efer sections / (o)verride / (q)uit")  # noqa: T201
        response = await _async_input("> ")
        if response.strip().lower() in ("q", "quit"):
            raise _BrainstormQuit
        choice = response.strip().lower()
        if choice in ("c", "continue"):
            return "continue"
        if choice in ("o", "override"):
            return "override"
        if choice.startswith("d"):
            if not quiet:
                print("Defer which sections? (comma-separated):")  # noqa: T201
            sections_input = await _async_input("> ")
            if sections_input.strip().lower() in ("q", "quit"):
                raise _BrainstormQuit
            return f"defer {sections_input.strip()}"
        return "continue"

    if interrupt_type == "approaches":
        if not quiet:
            print("\nProposed approaches:")  # noqa: T201
            for approach in payload["approaches"]:
                print(f"\n  {approach['name']}: {approach['description']}")  # noqa: T201
                print(f"    Tradeoffs: {approach['tradeoffs']}")  # noqa: T201
            print("\n  (type 'q' to quit)")  # noqa: T201
        response = await _async_input("Select approach by name> ")
        if response.strip().lower() in ("q", "quit"):
            raise _BrainstormQuit
        return response

    if interrupt_type == "design_section":
        if not quiet:
            print(f"\n--- {payload['title']} ---")  # noqa: T201
            print(payload["content"])  # noqa: T201
            print("\n  approve (a) / edit (paste text) / quit (q)")  # noqa: T201
        response = await _async_input("> ")
        if response.strip().lower() in ("q", "quit"):
            raise _BrainstormQuit
        return "approve" if response.strip().lower() in ("a", "approve") else response

    if interrupt_type == "brief":
        if not quiet:
            print("\n--- Design Brief ---")  # noqa: T201
            print(payload["brief"])  # noqa: T201
            print("\n  approve (a) / revise (type feedback) / quit (q)")  # noqa: T201
        response = await _async_input("> ")
        if response.strip().lower() in ("q", "quit"):
            raise _BrainstormQuit
        return "approve" if response.strip().lower() in ("a", "approve") else response

    # Unknown interrupt type — generic prompt
    response = await _async_input(f"\n[{interrupt_type}]> ")
    if response.strip().lower() in ("q", "quit"):
        raise _BrainstormQuit
    return response


async def _run_brainstorm(args: argparse.Namespace) -> int:
    """Run the brainstorm subgraph interactively.

    Args:
        args: Parsed CLI arguments.

    Returns:
        Exit code (0 success, 1 error).
    """
    from langgraph.types import Command  # noqa: PLC0415

    from superagents_sdlc.brainstorm.graph import build_brainstorm_graph  # noqa: PLC0415

    # Build LLM client
    if args.stub:
        llm: LLMClient = StubLLMClient(responses=_brainstorm_stub_responses())
    else:
        from superagents_sdlc.skills.llm import AnthropicLLMClient  # noqa: PLC0415

        llm = AnthropicLLMClient(model=args.model, max_tokens=args.max_tokens)

    # Load context
    context = _load_context(args.context_dir)
    codebase = ""
    if args.codebase_context:
        codebase = Path(args.codebase_context).read_text()

    # Build and invoke graph
    graph = build_brainstorm_graph(llm)
    config = {"configurable": {"thread_id": "brainstorm-cli"}}

    initial: dict[str, object] = {
        "idea": args.idea,
        "product_context": context.get("product_context", ""),
        "codebase_context": codebase,
        "transcript": [],
        "section_readiness": {},
        "confidence_score": 0,
        "gaps": [],
        "deferred_sections": [],
        "round_number": 0,
        "approaches": [],
        "selected_approach": "",
        "design_sections": [],
        "current_section_idx": 0,
        "brief": "",
        "status": "exploring",
        "brief_revision_count": 0,
    }

    result = await graph.ainvoke(initial, config)

    # Interrupt loop
    try:
        while result.get("__interrupt__"):
            payload = result["__interrupt__"][0].value
            response = await _handle_brainstorm_interrupt(
                payload, quiet=args.quiet
            )
            result = await graph.ainvoke(Command(resume=response), config)
    except _BrainstormQuit:
        if not args.quiet:
            print("\nBrainstorm cancelled.")  # noqa: T201
        return 0

    # Output brief
    brief = result.get("brief", "")
    if not args.quiet:
        print(f"\n{brief}")  # noqa: T201

    if args.output_dir:
        out = Path(args.output_dir)
        out.mkdir(parents=True, exist_ok=True)
        (out / "design_brief.md").write_text(brief)
        if not args.quiet:
            print(f"\nBrief written to {out / 'design_brief.md'}")  # noqa: T201

    return 0


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


def _make_skill_callback(
    *,
    narrative: NarrativeWriter,
    quiet: bool,
    spinner: object | None = None,
) -> callable:
    """Build the on_skill_complete callback for narrative recording and streaming.

    Args:
        narrative: NarrativeWriter instance.
        quiet: Whether to suppress stdout output.
        spinner: Optional Spinner instance for loading animation.

    Returns:
        Callback function for on_skill_complete.
    """
    def on_skill(persona_name: str, skill_name: str, summary: str) -> None:
        narrative.record_skill_execution(persona_name, skill_name, summary)
        if not quiet:
            if spinner is not None:
                spinner.stop()
            from superagents_sdlc.cli_format import print_skill  # noqa: PLC0415

            print_skill(persona_name, skill_name, summary)
            if spinner is not None:
                import random  # noqa: PLC0415

                from superagents_sdlc.cli_spinner import PHRASES  # noqa: PLC0415

                spinner.start(random.choice(PHRASES))  # noqa: S311

    return on_skill


def _make_qa_callback(
    *,
    narrative: NarrativeWriter,
    quiet: bool,
    spinner: object | None = None,
) -> callable:
    """Build the on_qa_complete callback for narrative recording and streaming.

    Args:
        narrative: NarrativeWriter instance.
        quiet: Whether to suppress stdout output.
        spinner: Optional Spinner instance for loading animation.

    Returns:
        Callback function for on_qa_complete.
    """
    def on_qa(certification: str, artifacts: list[Artifact]) -> None:
        # Extract key findings from routing manifest if available
        findings: list[dict] = []
        for a in artifacts:
            if a.artifact_type == "routing_manifest":
                try:
                    manifest = json.loads(Path(a.path).read_text())
                    for items in manifest.get("routing", {}).values():
                        for item in items:
                            findings.append({
                                "id": item.get("id", "?"),
                                "summary": item.get("summary", ""),
                                "severity": "HIGH",
                            })
                except (json.JSONDecodeError, KeyError):
                    pass
        narrative.record_qa_findings(
            total_checks=0,
            pass_count=0,
            fail_count=0,
            partial_count=0,
            key_findings=findings,
            certification=certification,
        )
        if not quiet:
            if spinner is not None:
                spinner.stop()
            from superagents_sdlc.cli_format import print_qa_findings  # noqa: PLC0415

            print_qa_findings(certification=certification, key_findings=findings)
            if spinner is not None:
                import random  # noqa: PLC0415

                from superagents_sdlc.cli_spinner import PHRASES  # noqa: PLC0415

                spinner.start(random.choice(PHRASES))  # noqa: S311

    return on_qa


def _make_routing_callback(
    *,
    narrative: NarrativeWriter,
    quiet: bool,
    spinner: object | None = None,
) -> callable:
    """Build the on_findings_routed callback for narrative recording and streaming.

    Args:
        narrative: NarrativeWriter instance.
        quiet: Whether to suppress stdout output.
        spinner: Optional Spinner instance for loading animation.

    Returns:
        Callback function for on_findings_routed.
    """
    def on_routed(routing: dict, cascade: list[str]) -> None:
        narrative.record_findings_routing(routing, cascade)
        if not quiet:
            if spinner is not None:
                spinner.stop()
            from superagents_sdlc.cli_format import print_routing  # noqa: PLC0415

            print_routing(routing, cascade)
            if spinner is not None:
                import random  # noqa: PLC0415

                from superagents_sdlc.cli_spinner import PHRASES  # noqa: PLC0415

                spinner.start(random.choice(PHRASES))  # noqa: S311

    return on_routed


def _make_retry_callback(
    *,
    narrative: NarrativeWriter,
    quiet: bool,
    spinner: object | None = None,
) -> callable:
    """Build the on_retry_start callback for narrative recording and streaming.

    Args:
        narrative: NarrativeWriter instance.
        quiet: Whether to suppress stdout output.
        spinner: Optional Spinner instance for loading animation.

    Returns:
        Callback function for on_retry_start.
    """
    def on_retry(pre_certification: str, routing: dict) -> None:
        total = sum(len(items) for items in routing.values())
        breakdown = {
            persona: len(items) for persona, items in routing.items()
        }
        narrative.record_retry_start(
            pre_retry_certification=pre_certification,
            finding_count=total,
            persona_breakdown=breakdown,
        )
        if not quiet:
            if spinner is not None:
                spinner.stop()
            from superagents_sdlc.cli_format import print_retry_start  # noqa: PLC0415

            print_retry_start(pre_certification, total)
            if spinner is not None:
                import random  # noqa: PLC0415

                from superagents_sdlc.cli_spinner import PHRASES  # noqa: PLC0415

                spinner.start(random.choice(PHRASES))  # noqa: S311

    return on_retry


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
    if args.command == "brainstorm":
        return await _run_brainstorm(args)

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

    if hasattr(args, "brief") and args.brief:
        context["brief"] = Path(args.brief).read_text()
    if hasattr(args, "codebase_context") and args.codebase_context:
        context["codebase_context"] = Path(args.codebase_context).read_text()

    # Build LLM clients
    fast_llm: LLMClient | None = None
    if args.stub:
        llm: LLMClient = StubLLMClient(responses=_stub_responses())
    else:
        from superagents_sdlc.skills.llm import AnthropicLLMClient  # noqa: PLC0415

        llm = AnthropicLLMClient(model=args.model, max_tokens=args.max_tokens)
        if args.fast_model:
            fast_llm = AnthropicLLMClient(
                model=args.fast_model, max_tokens=args.max_tokens,
            )

    # Build policy engine
    config = PolicyConfig(autonomy_level=args.autonomy_level)
    engine = PolicyEngine(config=config, gate=AutoApprovalGate())

    # Build orchestrator
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    orchestrator = PipelineOrchestrator(
        llm=llm, fast_llm=fast_llm, policy_engine=engine, context=context,
    )

    # Banner and spinner
    if not args.quiet:
        from superagents_sdlc.cli_spinner import Spinner, print_banner  # noqa: PLC0415

        try:
            import importlib.metadata as _meta  # noqa: PLC0415

            version = _meta.version("superagents-sdlc")
        except _meta.PackageNotFoundError:
            version = "dev"
        print_banner(version)
        spinner: Spinner | None = Spinner()
    else:
        spinner = None

    # Set up narrative writer
    narrative = NarrativeWriter(
        output_dir, f'{args.command} "{getattr(args, "idea", "pipeline")}"'
    )
    narrative.start_pass(1, "Initial Run")

    # Build callbacks
    seen_phases: list[str] = []
    retry_state: dict[str, bool] = {"started": False}
    on_phase = _make_phase_callback(
        quiet=args.quiet, narrative=narrative,
        seen_phases=seen_phases, retry_state=retry_state,
    )
    on_skill = _make_skill_callback(narrative=narrative, quiet=args.quiet, spinner=spinner)
    on_qa = _make_qa_callback(narrative=narrative, quiet=args.quiet, spinner=spinner)
    on_routed = _make_routing_callback(narrative=narrative, quiet=args.quiet, spinner=spinner)
    on_retry = _make_retry_callback(narrative=narrative, quiet=args.quiet, spinner=spinner)

    # Start spinner for the first skill
    if spinner is not None:
        import random  # noqa: PLC0415

        from superagents_sdlc.cli_spinner import PHRASES  # noqa: PLC0415

        spinner.start(random.choice(PHRASES))  # noqa: S311

    # Run the appropriate pipeline
    result = await _run_pipeline(
        args, orchestrator, output_dir, on_phase,
        on_skill=on_skill, on_qa=on_qa,
        on_routed=on_routed, on_retry=on_retry,
    )

    # Stop spinner
    if spinner is not None:
        spinner.stop()

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


async def _run_pipeline(  # noqa: PLR0913
    args: argparse.Namespace,
    orchestrator: PipelineOrchestrator,
    output_dir: Path,
    on_phase: callable,
    *,
    on_skill: callable | None = None,
    on_qa: callable | None = None,
    on_routed: callable | None = None,
    on_retry: callable | None = None,
) -> PipelineResult:
    """Dispatch to the appropriate pipeline method.

    Args:
        args: Parsed CLI arguments.
        orchestrator: Pipeline orchestrator.
        output_dir: Artifact output directory.
        on_phase: Phase completion callback.
        on_skill: Skill completion callback.
        on_qa: QA completion callback.
        on_routed: Findings routing callback.
        on_retry: Retry start callback.

    Returns:
        Pipeline result.
    """
    callbacks = {
        "on_phase_complete": on_phase,
        "on_skill_complete": on_skill,
        "on_qa_complete": on_qa,
        "on_findings_routed": on_routed,
        "on_retry_start": on_retry,
    }
    if args.command == "idea-to-code":
        return await orchestrator.run_idea_to_code(
            args.idea,
            artifact_dir=output_dir,
            **callbacks,
        )
    if args.command == "spec-from-prd":
        return await orchestrator.run_spec_from_prd(
            args.prd_path,
            user_stories_path=args.user_stories,
            artifact_dir=output_dir,
            **callbacks,
        )
    # plan-from-spec
    return await orchestrator.run_plan_from_spec(
        implementation_plan_path=args.plan,
        tech_spec_path=args.spec,
        artifact_dir=output_dir,
        user_stories_path=args.user_stories,
        **callbacks,
    )


def main() -> None:
    """CLI entry point."""
    try:
        from dotenv import load_dotenv  # noqa: PLC0415

        load_dotenv()
    except ImportError:
        pass

    parser = _build_parser()
    args = parser.parse_args()

    try:
        code = asyncio.run(_run(args))
    except (FileNotFoundError, ValueError, RuntimeError, TypeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)  # noqa: T201
        sys.exit(1)
    except KeyboardInterrupt:
        sys.exit(130)
    else:
        sys.exit(code)


if __name__ == "__main__":
    main()
