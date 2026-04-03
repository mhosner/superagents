"""Standalone CLI for superagents-sdlc pipelines."""

from __future__ import annotations

import argparse
import asyncio
import datetime
import json
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from superagents_sdlc.skills.llm import LLMClient, StubLLMClient

if TYPE_CHECKING:
    from superagents_sdlc.brainstorm.sidekick import SidekickContext
    from superagents_sdlc.skills.base import Artifact
    from superagents_sdlc.workflows.narrative import NarrativeWriter
    from superagents_sdlc.workflows.orchestrator import PipelineOrchestrator
    from superagents_sdlc.workflows.result import PipelineResult

# Auto-continue when confidence is more than this many points below threshold.
AUTO_CONTINUE_MARGIN = 10


def _render_progress_bar(confidence: int, threshold: int, width: int = 20) -> str:
    """Render a normalized progress bar.

    Normalizes the confidence score so that ``threshold`` appears as 100%.
    The user never sees the raw score or threshold.

    Args:
        confidence: Current confidence score.
        threshold: Target threshold (maps to 100% visually).
        width: Bar width in characters.

    Returns:
        Formatted progress bar string like ``[████████────────────] 50%``.
    """
    ratio = 0.0 if threshold <= 0 else confidence / threshold
    ratio = max(0.0, min(1.0, ratio))
    filled = round(ratio * width)
    empty = width - filled
    bar = "█" * filled + "─" * empty
    if ratio >= 1.0:
        return f"[{bar}] Ready!"
    pct = round(ratio * 100)
    return f"[{bar}] {pct}%"


def _confidence_drop_message(
    delta: int,
    current_gaps: int,
    previous_gaps: int,
) -> str:
    """Generate a contextual message when confidence drops.

    Args:
        delta: Confidence change from previous assessment.
        current_gaps: Number of gaps after this assessment.
        previous_gaps: Number of gaps before this assessment.

    Returns:
        Reassuring one-liner, or empty string if delta >= 0.
    """
    if delta >= 0:
        return ""
    if current_gaps > previous_gaps:
        return "↓ Your answer revealed new areas to explore — that's progress"
    return "↓ Recalibrating based on your input"


async def _prompt_with_help(
    prompt: str = "> ",
    *,
    sidekick_context: SidekickContext | None = None,
    llm: LLMClient | None = None,
) -> str:
    """Prompt for input, handling ``?`` help requests with sidekick skills.

    When the user types ``?``, shows a sub-menu of thinking tools. If
    sidekick context and LLM are available, runs the selected skill and
    displays the result. Otherwise shows a fallback message.

    Args:
        prompt: Prompt string to display.
        sidekick_context: Context for sidekick skills.
        llm: LLM client for sidekick skill calls.

    Returns:
        The user's non-help input.
    """
    while True:
        response = await _async_input(prompt)
        if response.strip() != "?":
            return response

        # Handle ? input
        if sidekick_context is None or llm is None:
            print("  Help options aren't available for this prompt.")  # noqa: T201
            continue

        from superagents_sdlc.brainstorm.sidekick import SKILLS, run_sidekick_skill  # noqa: PLC0415

        print("\n  How can I help?\n")  # noqa: T201
        for skill in SKILLS:
            print(f"  {skill.key}) {skill.name} — {skill.description}")  # noqa: T201
        print("  b) Back\n")  # noqa: T201

        choice = await _async_input("  > ")
        if choice.strip().lower() in ("b", "back"):
            continue

        # Find matching skill
        selected = None
        for skill in SKILLS:
            if choice.strip() == skill.key:
                selected = skill
                break

        if selected is None:
            print("  Invalid choice.")  # noqa: T201
            continue

        # Run the skill
        print(f"\n  ─── {selected.name} {'─' * (37 - len(selected.name))}\n")  # noqa: T201
        result = await run_sidekick_skill(selected, sidekick_context, llm)
        print(f"  {result}\n")  # noqa: T201
        print(f"  {'─' * 42}\n")  # noqa: T201
        print("  Now, what's your answer?")  # noqa: T201


class _SpinnerLLMClient:
    """LLMClient wrapper that shows a spinner during generate() calls.

    Starts the spinner with a random superhero phrase before each call
    and stops it when the call completes (or raises).

    Args:
        inner: The actual LLM client to delegate to.
        spinner: Spinner instance from `cli_spinner`.
    """

    def __init__(self, inner: LLMClient, spinner: object) -> None:
        self._inner = inner
        self._spinner = spinner

    async def generate(
        self,
        prompt: str,
        *,
        system: str = "",
        cached_prefix: str | None = None,
    ) -> str:
        """Delegate to inner LLM with spinner active during the call.

        Args:
            prompt: User prompt.
            system: Optional system prompt.
            cached_prefix: Optional stable context to cache.

        Returns:
            Raw response string from the inner LLM.
        """
        import random  # noqa: PLC0415

        from superagents_sdlc.cli_spinner import PHRASES  # noqa: PLC0415

        self._spinner.start(random.choice(PHRASES))  # noqa: S311
        try:
            return await self._inner.generate(
                prompt,
                system=system,
                cached_prefix=cached_prefix,
            )
        finally:
            self._spinner.stop()


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
            "Cheaper model for Architect/Developer/FindingsRouter (default: uses --model for all)."
        ),
    )
    shared.add_argument(
        "--stub",
        action="store_true",
        help="Use StubLLMClient instead of Anthropic (development testing only).",
    )
    shared.add_argument(
        "--idea-memory",
        type=Path,
        default=None,
        help="Path to IdeaMemory file from brainstorm.",
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
    brainstorm_parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        default=False,
        help="Show detailed section readiness and gap information.",
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
        "Readiness ratings": json.dumps(
            {
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
            }
        ),
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


def _slugify(title: str) -> str:
    """Convert a section title to a safe filename stem.

    Lowercases the title and replaces any sequence of non-alphanumeric
    characters with a single underscore, then strips leading/trailing
    underscores.

    Args:
        title: Human-readable section title (e.g. "Problem Statement & Goals").

    Returns:
        Filename stem without extension (e.g. "problem_statement_goals").
    """
    import re  # noqa: PLC0415

    slug = title.lower()
    slug = re.sub(r"[^a-z0-9]+", "_", slug)
    return slug.strip("_")


def _extract_section_content(raw: str) -> str:
    """Extract content from a JSON-wrapped design section response.

    If the response is a JSON object with a ``content`` field, return just
    the content. Otherwise return the raw string unchanged.

    Args:
        raw: Raw LLM response, possibly JSON-wrapped.

    Returns:
        Extracted markdown content or the original string.
    """
    try:
        parsed = json.loads(raw)
        return parsed.get("content", raw)
    except (json.JSONDecodeError, TypeError):
        return raw


def _build_pipeline_command(args: argparse.Namespace, output_dir: Path) -> list[str]:
    """Build the idea-to-code pipeline subprocess command.

    Args:
        args: Parsed CLI arguments from the brainstorm run.
        output_dir: Brainstorm output directory.

    Returns:
        Command list suitable for ``subprocess.run``.
    """
    cmd = [
        "uv",
        "run",
        "superagents-sdlc",
        "idea-to-code",
        args.idea,
        "--brief",
        str(output_dir / "design_brief.md"),
        "--idea-memory",
        str(output_dir / "idea_memory.md"),
        "--output-dir",
        str(output_dir / "pipeline"),
    ]
    if args.codebase_context:
        cmd.extend(["--codebase-context", args.codebase_context])
    if getattr(args, "model", None):
        cmd.extend(["--model", args.model])
    if getattr(args, "fast_model", None):
        cmd.extend(["--fast-model", args.fast_model])
    if getattr(args, "max_tokens", None):
        cmd.extend(["--max-tokens", str(args.max_tokens)])
    if getattr(args, "interactive", False):
        cmd.append("--interactive")
    return cmd


def _build_sidekick_context(
    payload: dict,
    *,
    idea: str,
    brainstorm_state: dict | None = None,
) -> SidekickContext:
    """Build sidekick context from an interrupt payload.

    Args:
        payload: Interrupt payload dict.
        idea: The brainstorm idea string.
        brainstorm_state: Current graph state snapshot.

    Returns:
        SidekickContext for sidekick skill execution.
    """
    from superagents_sdlc.brainstorm.sidekick import SidekickContext  # noqa: PLC0415

    state = brainstorm_state or {}
    interrupt_type = payload.get("type", "")

    # Extract question and options based on interrupt type
    if interrupt_type == "questions":
        questions = payload.get("questions", [])
        if questions:
            q = questions[0]  # Use first question for context
            question_text = q.get("question", "")
            options = q.get("options")
            targets_section = q.get("targets_section", "")
        else:
            question_text = ""
            options = None
            targets_section = ""
    elif interrupt_type == "approaches":
        question_text = "Which implementation approach should we use?"
        approaches = payload.get("approaches", [])
        options = [a.get("name", "") for a in approaches]
        targets_section = ""
    elif interrupt_type == "confidence_assessment":
        question_text = "Should we continue exploring or move on?"
        options = ["Continue exploring", "Override and proceed", "Defer some sections"]
        targets_section = ""
    elif interrupt_type in ("design_section", "brief"):
        question_text = f"Review: {payload.get('title', 'section')}"
        options = ["Approve", "Edit"]
        targets_section = ""
    elif interrupt_type == "stall_exit":
        question_text = "Progress has stalled. Should we move on to design or keep exploring?"
        options = ["Move on to design", "Keep exploring"]
        targets_section = ""
    else:
        question_text = ""
        options = None
        targets_section = ""

    # Extract decisions from IdeaMemory if available
    decisions_so_far = ""
    if state.get("idea_memory"):
        from superagents_sdlc.brainstorm.idea_memory import IdeaMemory  # noqa: PLC0415

        memory = IdeaMemory.from_state(
            idea,
            state.get("idea_memory", []),
            state.get("idea_memory_counts", {"decision": 0, "rejection": 0}),
        )
        decisions_so_far = memory.format_for_prompt()

    return SidekickContext(
        idea=idea,
        question_text=question_text,
        options=options,
        targets_section=targets_section,
        decisions_so_far=decisions_so_far,
        selected_approach=state.get("selected_approach", ""),
        product_context=state.get("product_context", ""),
    )


async def _handle_brainstorm_interrupt(
    payload: dict,
    *,
    quiet: bool = False,
    verbose: bool = False,
    output_dir: Path | None = None,
    llm: LLMClient | None = None,
    idea: str = "",
    brainstorm_state: dict | None = None,
) -> str:
    """Handle a brainstorm interrupt by prompting the user.

    Args:
        payload: Interrupt payload with type and data.
        quiet: If True, suppress output and return defaults.
        verbose: If True, show detailed section readiness and gap info.
        output_dir: Directory to write artifacts to disk before approval.
            When provided, design sections and briefs are written to disk
            and only the file path is shown (not the full content).
        llm: LLM client for sidekick skill calls. Passed through to
            ``_prompt_with_help`` so the ``?`` menu can run skills.
        idea: The brainstorm idea string, used to build sidekick context.
        brainstorm_state: Current graph state snapshot for sidekick context.

    Returns:
        User's response string.

    Raises:
        _BrainstormQuit: If user types 'q' or 'quit'.
    """
    interrupt_type = payload["type"]

    # Build sidekick context for ? menu (skip in quiet mode)
    sidekick_ctx = (
        _build_sidekick_context(
            payload,
            idea=idea,
            brainstorm_state=brainstorm_state,
        )
        if not quiet
        else None
    )

    if interrupt_type == "questions":
        questions = payload.get("questions", [])
        if not quiet:
            confidence = payload.get("confidence", 0)
            threshold = payload.get("threshold", 80)
            print(f"\n{_render_progress_bar(confidence, threshold)}")  # noqa: T201
        answers = []
        for i, q in enumerate(questions, 1):
            # Build per-question sidekick context
            q_ctx = (
                _build_sidekick_context(
                    {"type": "questions", "questions": [q]},
                    idea=idea,
                    brainstorm_state=brainstorm_state,
                )
                if not quiet
                else None
            )
            if not quiet:
                target = q.get("targets_section", "")
                if verbose and target:
                    print(f"  [targets: {target}]")  # noqa: T201
                if len(questions) > 1:
                    print(f"\n  Question {i} of {len(questions)}:")  # noqa: T201
                print(f"\n  {q['question']}\n")  # noqa: T201
                if q.get("options"):
                    from superagents_sdlc.brainstorm.nodes import _clean_option  # noqa: PLC0415

                    for j, opt in enumerate(q["options"], 1):
                        print(f"  {j}) {_clean_option(opt)}")  # noqa: T201
                    print(  # noqa: T201
                        f"  {len(q['options']) + 1}) Type your own answer"
                    )
                    print(  # noqa: T201
                        "\n  Pick a number or type your answer   ?) Help   q) Quit"
                    )
                else:
                    print("  Type your answer   ?) Help   q) Quit")  # noqa: T201
            response = await _prompt_with_help("> ", sidekick_context=q_ctx, llm=llm)
            if response.strip().lower() in ("q", "quit"):
                raise _BrainstormQuit
            # Return resolved answer + question metadata from the
            # interrupt payload.  The generate_question node re-executes
            # its LLM call on resume which may reorder options or target
            # a different section.  Returning the full metadata makes
            # the answer independent of the re-executed output.
            raw_opts = q.get("options")
            if raw_opts:
                from superagents_sdlc.brainstorm.nodes import _clean_option, _resolve_answer  # noqa: PLC0415

                cleaned = [_clean_option(o) for o in raw_opts]
                response = _resolve_answer(response, cleaned)
            answers.append(
                {
                    "answer": response,
                    "targets_section": q.get("targets_section", ""),
                    "question_text": q.get("question", ""),
                }
            )
        return answers

    # Legacy single-question format
    if interrupt_type == "question":
        if not quiet:
            print(f"\n{payload['question']}")  # noqa: T201
            if payload.get("options"):
                from superagents_sdlc.brainstorm.nodes import _clean_option  # noqa: PLC0415

                for i, opt in enumerate(payload["options"], 1):
                    print(f"  {i}) {_clean_option(opt)}")  # noqa: T201
            print("  Type your answer   ?) Help   q) Quit")  # noqa: T201
        response = await _prompt_with_help("> ", sidekick_context=sidekick_ctx, llm=llm)
        if response.strip().lower() in ("q", "quit"):
            raise _BrainstormQuit
        return response

    if interrupt_type == "confidence_assessment":
        confidence = payload.get("confidence", 0)
        threshold = payload.get("threshold", 80)
        gaps = payload.get("gaps", [])
        round_num = payload.get("round", 0)

        # Auto-continue: skip prompt when far below threshold, but always
        # pause on round 1 so the user gets their first look.
        gap_to_threshold = threshold - confidence
        if gap_to_threshold > AUTO_CONTINUE_MARGIN and round_num > 1:
            if not quiet:
                bar = _render_progress_bar(confidence, threshold)
                count = len(gaps)
                label = "area" if count == 1 else "areas"
                print(  # noqa: T201
                    f"\n  {bar} — auto-continuing ({count} {label} remaining)"
                )
            return "auto_continue"

        if not quiet:
            print(f"\n{_render_progress_bar(confidence, threshold)}")  # noqa: T201
            delta = payload.get("confidence_delta", 0)
            previous_gaps = payload.get(
                "previous_gap_count",
                len(gaps),
            )
            drop_msg = _confidence_drop_message(
                delta,
                len(gaps),
                previous_gaps,
            )
            if drop_msg:
                print(f"{drop_msg}")  # noqa: T201
            count = len(gaps)
            verb = "needs" if count == 1 else "need"
            label = "area" if count == 1 else "areas"
            print(f"\n  {count} {label} still {verb} input")  # noqa: T201

            if verbose:
                summaries = payload.get("summaries", {})
                sections = payload.get("sections", {})
                if sections:
                    print("\n  Section readiness:")  # noqa: T201
                    markers = {"high": "✓", "medium": "~", "low": "✗"}
                    for section, info in sections.items():
                        readiness = info.get("readiness", "?")
                        marker = markers.get(readiness, "?")
                        summary = summaries.get(section, "")
                        print(  # noqa: T201
                            f"    {marker} {section}: {readiness.upper()} — {summary}"
                        )
                if gaps:
                    print("\n  Gaps:")  # noqa: T201
                    for g in gaps:
                        print(  # noqa: T201
                            f"    - {g['section']}: {g['description']}"
                        )

            if verbose:
                print(  # noqa: T201
                    "\n  c) Continue   d) Defer sections   o) Override   q) Quit   ?) Help"
                )
            else:
                print("\n  c) Continue   q) Quit   ?) Help")  # noqa: T201
        response = await _prompt_with_help("> ", sidekick_context=sidekick_ctx, llm=llm)
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
            sections_input = await _prompt_with_help("> ", sidekick_context=sidekick_ctx, llm=llm)
            if sections_input.strip().lower() in ("q", "quit"):
                raise _BrainstormQuit
            return f"defer {sections_input.strip()}"
        return "continue"

    if interrupt_type == "approaches":
        if not quiet:
            print("\n  Choosing an approach\n")  # noqa: T201
            for i, approach in enumerate(payload["approaches"], 1):
                print(  # noqa: T201
                    f"  {i}) {approach['name']} — {approach['description']}"
                )
                print(  # noqa: T201
                    f"     Tradeoffs: {approach['tradeoffs']}"
                )
            print("\n  Pick a number   ?) Help   q) Quit")  # noqa: T201
        response = await _prompt_with_help("> ", sidekick_context=sidekick_ctx, llm=llm)
        if response.strip().lower() in ("q", "quit"):
            raise _BrainstormQuit
        return response

    if interrupt_type == "design_section":
        content = _extract_section_content(payload["content"])
        section_index = payload.get("section_index", 0)
        section_count = payload.get("section_count", 0)
        step_label = ""
        if section_count > 0:
            step_label = f"section {section_index + 1} of {section_count} — "
        if output_dir is not None:
            sections_dir = output_dir / "sections"
            sections_dir.mkdir(parents=True, exist_ok=True)
            section_path = sections_dir / f"{_slugify(payload['title'])}.md"
            section_path.write_text(content)
            if not quiet:
                print(  # noqa: T201
                    f"\n  Design: {step_label}{payload['title']}\n"
                )
                print(f"  \U0001f4c4 Saved to: {section_path}")  # noqa: T201
                print(  # noqa: T201
                    "\n  a) Approve   e) Edit   ?) Help   q) Quit"
                )
        elif not quiet:
            print(  # noqa: T201
                f"\n  Design: {step_label}{payload['title']}\n"
            )
            print(content)  # noqa: T201
            print(  # noqa: T201
                "\n  a) Approve   e) Edit   ?) Help   q) Quit"
            )
        response = await _prompt_with_help("> ", sidekick_context=sidekick_ctx, llm=llm)
        if response.strip().lower() in ("q", "quit"):
            raise _BrainstormQuit
        if response.strip().lower() in ("a", "approve"):
            return "approve"
        # User provided edited text — write back to disk if output_dir set
        if output_dir is not None:
            section_path.write_text(response)
        return response

    if interrupt_type == "brief":
        if output_dir is not None:
            brief_path = output_dir / "design_brief.md"
            brief_path.parent.mkdir(parents=True, exist_ok=True)
            brief_path.write_text(payload["brief"])
            if not quiet:
                print("\n  Final review: design brief\n")  # noqa: T201
                print(f"  \U0001f4c4 Saved to: {brief_path}")  # noqa: T201
                print(  # noqa: T201
                    "\n  a) Approve   e) Edit   ?) Help   q) Quit"
                )
        elif not quiet:
            print("\n  Final review: design brief\n")  # noqa: T201
            print(payload["brief"])  # noqa: T201
            print(  # noqa: T201
                "\n  a) Approve   e) Edit   ?) Help   q) Quit"
            )
        response = await _prompt_with_help("> ", sidekick_context=sidekick_ctx, llm=llm)
        if response.strip().lower() in ("q", "quit"):
            raise _BrainstormQuit
        return "approve" if response.strip().lower() in ("a", "approve") else response

    if interrupt_type == "stall_exit":
        if not quiet:
            confidence = payload.get("confidence", 0)
            threshold = payload.get("threshold", 80)
            gaps = payload.get("gaps", [])
            print(f"\n{_render_progress_bar(confidence, threshold)}")  # noqa: T201
            print(  # noqa: T201
                "  Progress has stalled — confidence hasn't changed in recent rounds"
            )
            count = len(gaps)
            verb = "needs" if count == 1 else "need"
            label = "area" if count == 1 else "areas"
            print(f"\n  {count} {label} still {verb} input")  # noqa: T201
            if verbose and gaps:
                print("\n  Gaps:")  # noqa: T201
                for g in gaps:
                    print(  # noqa: T201
                        f"    - {g['section']}: {g['description']}"
                    )
            print(  # noqa: T201
                "\n  p) Move on to design   c) Keep exploring   ?) Help   q) Quit"
            )
        response = await _prompt_with_help("> ", sidekick_context=sidekick_ctx, llm=llm)
        if response.strip().lower() in ("q", "quit"):
            raise _BrainstormQuit
        choice = response.strip().lower()
        if choice in ("p", "proceed"):
            return "proceed"
        return "continue"

    # Unknown interrupt type — generic prompt
    response = await _prompt_with_help("> ", sidekick_context=sidekick_ctx, llm=llm)
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

    # Resolve output directory — default to ./superagents-output/{slug}/
    if args.output_dir:
        output_dir = Path(args.output_dir)
    else:
        output_dir = Path("superagents-output") / _slugify(args.idea)

    # Overwrite check: prompt if dir exists and contains files
    while output_dir.exists() and any(output_dir.iterdir()):
        if not args.quiet:
            print(f"\n⚠️  Output directory {output_dir} already exists. Overwrite? (y/n)")  # noqa: T201
        response = await _async_input("> ")
        if response.strip().lower() in ("q", "quit"):
            return 0
        if response.strip().lower() in ("y", "yes"):
            break
        # User said no — ask for alternative path
        if not args.quiet:
            print("Enter alternative output path>")  # noqa: T201
        alt = await _async_input("> ")
        if alt.strip().lower() in ("q", "quit"):
            return 0
        output_dir = Path(alt.strip())

    from superagents_sdlc.manifest import create_manifest, update_manifest  # noqa: PLC0415

    create_manifest(
        output_dir,
        idea=args.idea,
        model=args.model,
        fast_model=getattr(args, "fast_model", None),
    )

    # Build LLM client
    if args.stub:
        llm: LLMClient = StubLLMClient(responses=_brainstorm_stub_responses())
    else:
        from superagents_sdlc.skills.llm import AnthropicLLMClient  # noqa: PLC0415

        llm = AnthropicLLMClient(model=args.model, max_tokens=args.max_tokens)

    raw_llm = llm  # Preserve unwrapped LLM for sidekick calls

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
        llm = _SpinnerLLMClient(llm, spinner)
    else:
        spinner = None

    # Load context
    if spinner is not None:
        import random  # noqa: PLC0415

        from superagents_sdlc.cli_spinner import PHRASES  # noqa: PLC0415

        spinner.start(random.choice(PHRASES))  # noqa: S311

    context = _load_context(args.context_dir)
    codebase = ""
    if args.codebase_context:
        codebase = Path(args.codebase_context).read_text()

    # Build and invoke graph
    graph = build_brainstorm_graph(llm)

    if spinner is not None:
        spinner.stop()
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
                payload,
                quiet=args.quiet,
                verbose=getattr(args, "verbose", False),
                output_dir=output_dir,
                llm=raw_llm,
                idea=args.idea,
                brainstorm_state=dict(result) if isinstance(result, dict) else None,
            )
            result = await graph.ainvoke(Command(resume=response), config)
    except _BrainstormQuit:
        if not args.quiet:
            print("\nBrainstorm cancelled.")  # noqa: T201
        return 0

    # Write brief and IdeaMemory (idempotent safety net — also written during interrupts)
    brief = result.get("brief", "")
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "design_brief.md").write_text(brief)
    if not args.quiet:
        print(f"\nBrief written to {output_dir / 'design_brief.md'}")  # noqa: T201

    from superagents_sdlc.brainstorm.idea_memory import IdeaMemory  # noqa: PLC0415

    memory = IdeaMemory.from_state(
        args.idea,
        result.get("idea_memory", []),
        result.get("idea_memory_counts", {"decision": 0, "rejection": 0}),
    )
    (output_dir / "idea_memory.md").write_text(memory.to_markdown())
    if not args.quiet:
        print(f"IdeaMemory written to {output_dir / 'idea_memory.md'}")  # noqa: T201

    from superagents_sdlc.brainstorm.narrative import render_narrative_markdown  # noqa: PLC0415

    narrative_md = render_narrative_markdown(
        result.get("narrative_entries", []),
        args.idea,
    )
    (output_dir / "brainstorm_narrative.md").write_text(narrative_md)
    if not args.quiet:
        print(f"Narrative written to {output_dir / 'brainstorm_narrative.md'}")  # noqa: T201

    update_manifest(
        output_dir,
        state="brief_ready",
        artifacts={
            "brief": "design_brief.md",
            "idea_memory": "idea_memory.md",
            "narrative": "brainstorm_narrative.md",
        },
    )

    # Handoff prompt — skipped in quiet mode
    if args.quiet:
        return 0

    # Drain any buffered stdin before the handoff prompt. The brainstorm's
    # interrupt loop may leave trailing newlines in the buffer from
    # _handle_brainstorm_interrupt calls, which _async_input would consume
    # instead of waiting for fresh user input.
    import select  # noqa: PLC0415

    while select.select([sys.stdin], [], [], 0)[0]:
        sys.stdin.readline()

    print("\n  (p)ipeline — send brief to idea-to-code pipeline")  # noqa: T201
    print("  (d)one — exit")  # noqa: T201
    try:
        choice = (await _async_input("\n> ")).strip().lower()
    except EOFError:
        choice = "d"

    # Re-prompt once on empty input (accidental Enter or residual buffer)
    if not choice:
        try:
            choice = (await _async_input("  Please enter (p) or (d): ")).strip().lower()
        except EOFError:
            choice = "d"

    if choice not in ("p", "pipeline"):
        return 0

    update_manifest(output_dir, state="pipeline_running", artifacts={"pipeline_dir": "pipeline/"})

    # Launch pipeline subprocess
    cmd = _build_pipeline_command(args, output_dir)
    print(f"\nLaunching pipeline: {' '.join(cmd)}")  # noqa: T201
    proc = subprocess.run(cmd, check=False)  # noqa: S603
    print(f"\nPipeline complete (exit code {proc.returncode}). Artifacts: {output_dir}/pipeline/")  # noqa: T201

    # Write handoff record
    timestamp = datetime.datetime.now().isoformat()
    cmd_str = " ".join(cmd)
    handoff_content = (
        f"# Brainstorm → Pipeline Handoff\n\n"
        f"- **Idea:** {args.idea}\n"
        f"- **Handoff time:** {timestamp}\n"
        f"- **Brief:** {output_dir}/design_brief.md\n"
        f"- **IdeaMemory:** {output_dir}/idea_memory.md\n"
        f"- **Codebase context:** {args.codebase_context or 'None'}\n"
        f"- **Pipeline output:** {output_dir}/pipeline/\n"
        f"- **Pipeline command:** {cmd_str}\n"
        f"- **Pipeline exit code:** {proc.returncode}\n"
    )
    (output_dir / "handoff.md").write_text(handoff_content)

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
            "# Validation Report\n## Executive Summary\nDone.\n## Certification\nNEEDS WORK"
        ),
        "## Plan structure analysis\n": (
            "## Compliance Check\n| Feature | PASS |\n"
            "## Summary\nTotal: 1 | Pass: 1\nOverall: NEEDS WORK"
        ),
        # FindingsRouter — must come before other keys containing "## Validation report"
        "## Validation report\n": json.dumps(
            {
                "certification": "NEEDS WORK",
                "total_findings": 1,
                "routing": {
                    "product_manager": [],
                    "architect": [
                        {
                            "id": "RF-1",
                            "summary": "Minor spec gap",
                            "detail": "Detail text",
                            "affected_artifact": "tech_spec",
                            "related_requirements": [{"id": "AC-1", "text": "Criterion"}],
                        }
                    ],
                    "developer": [],
                },
            }
        ),
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
        # Extract compliance counts from compliance_report metadata
        total_checks = 0
        pass_count = 0
        fail_count = 0
        partial_count = 0
        for a in artifacts:
            if a.artifact_type == "compliance_report":
                total_checks = int(a.metadata.get("total_checks", 0))
                pass_count = int(a.metadata.get("pass_count", 0))
                fail_count = int(a.metadata.get("fail_count", 0))
                partial_count = int(a.metadata.get("partial_count", 0))
                break

        # Extract key findings from routing manifest if available
        findings: list[dict] = []
        for a in artifacts:
            if a.artifact_type == "routing_manifest":
                try:
                    manifest = json.loads(Path(a.path).read_text())
                    for items in manifest.get("routing", {}).values():
                        for item in items:
                            findings.append(
                                {
                                    "id": item.get("id", "?"),
                                    "summary": item.get("summary", ""),
                                    "severity": "HIGH",
                                }
                            )
                except (json.JSONDecodeError, KeyError):
                    pass
        narrative.record_qa_findings(
            total_checks=total_checks,
            pass_count=pass_count,
            fail_count=fail_count,
            partial_count=partial_count,
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
        breakdown = {persona: len(items) for persona, items in routing.items()}
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
    if getattr(args, "idea_memory", None):
        context["idea_memory"] = args.idea_memory.read_text()

    # Build LLM clients
    fast_llm: LLMClient | None = None
    if args.stub:
        llm: LLMClient = StubLLMClient(responses=_stub_responses())
    else:
        from superagents_sdlc.skills.llm import AnthropicLLMClient  # noqa: PLC0415

        llm = AnthropicLLMClient(model=args.model, max_tokens=args.max_tokens)
        if args.fast_model:
            fast_llm = AnthropicLLMClient(
                model=args.fast_model,
                max_tokens=args.max_tokens,
            )

    # Build policy engine
    config = PolicyConfig(autonomy_level=args.autonomy_level)
    engine = PolicyEngine(config=config, gate=AutoApprovalGate())

    # Build orchestrator
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    orchestrator = PipelineOrchestrator(
        llm=llm,
        fast_llm=fast_llm,
        policy_engine=engine,
        context=context,
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
    narrative = NarrativeWriter(output_dir, f'{args.command} "{getattr(args, "idea", "pipeline")}"')
    narrative.start_pass(1, "Initial Run")

    # Build callbacks
    seen_phases: list[str] = []
    retry_state: dict[str, bool] = {"started": False}
    on_phase = _make_phase_callback(
        quiet=args.quiet,
        narrative=narrative,
        seen_phases=seen_phases,
        retry_state=retry_state,
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
        args,
        orchestrator,
        output_dir,
        on_phase,
        on_skill=on_skill,
        on_qa=on_qa,
        on_routed=on_routed,
        on_retry=on_retry,
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

    # Update manifest if output dir has one
    from superagents_sdlc.manifest import update_manifest as _update_manifest  # noqa: PLC0415

    pipeline_state = (
        "pipeline_complete" if result.certification == "READY" else "pipeline_needs_work"
    )
    _update_manifest(
        output_dir,
        state=pipeline_state,
        pipeline={
            "certification": result.certification,
            "retry_attempted": result.retry_attempted,
        },
    )

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


async def _guided_flow() -> int:  # noqa: C901, PLR0912
    """Interactive guided startup flow.

    Returns:
        Exit code (0 success, 1 error).
    """
    from superagents_sdlc.manifest import (  # noqa: PLC0415
        _state_display,
        _time_ago,
        discover_sessions,
    )

    # Banner
    try:
        import importlib.metadata as _meta  # noqa: PLC0415

        version = _meta.version("superagents-sdlc")
    except Exception:  # noqa: BLE001
        version = "dev"

    from superagents_sdlc.cli_spinner import print_banner  # noqa: PLC0415

    print_banner(version)

    # Settings — session-scoped defaults
    settings: dict[str, str | None] = {
        "model": "claude-sonnet-4-6",
        "fast_model": None,
        "output_root": "superagents-output",
        "max_tokens": "16384",
    }

    while True:
        # Discover recent sessions
        sessions = discover_sessions(
            Path(settings["output_root"] or "superagents-output"),
        )

        if sessions:
            print("\nRecent sessions:")  # noqa: T201
            for i, s in enumerate(sessions[:5], 1):
                time_str = _time_ago(s.get("updated_at", ""))
                state_str = _state_display(s.get("state", ""))
                idea_short = s.get("idea", "untitled")[:40]
                print(f"  {i}) {idea_short} ({time_str}) — {state_str}")  # noqa: T201
            print()  # noqa: T201
        else:
            print("\n  Ready to design something? Let's start with your idea.\n")  # noqa: T201

        print("  n) Start a new brainstorm")  # noqa: T201
        print("  s) Settings")  # noqa: T201
        print("  q) Quit")  # noqa: T201

        try:
            choice = (await _async_input("\n> ")).strip().lower()
        except (EOFError, KeyboardInterrupt):
            return 0

        if choice in ("q", "quit"):
            return 0

        if choice == "s":
            await _guided_settings(settings)
            continue

        if choice == "n":
            code = await _guided_new_brainstorm(settings)
            if code != 0:
                return code
            continue

        # Check if it's a session number
        if choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(sessions):
                code = await _guided_resume_session(sessions[idx], settings)
                if code != 0:
                    return code
                continue

        print("  Invalid choice. Try again.")  # noqa: T201


async def _guided_settings(settings: dict[str, str | None]) -> None:
    """Interactive settings sub-menu.

    Args:
        settings: Mutable settings dict to update in place.
    """
    while True:
        fast_display = settings["fast_model"] or "(same as model)"
        print("\nSettings:")  # noqa: T201
        print(f"  Model: {settings['model']}")  # noqa: T201
        print(f"  Fast model: {fast_display}")  # noqa: T201
        print(f"  Output root: {settings['output_root']}")  # noqa: T201
        print()  # noqa: T201
        print("  1) Change model")  # noqa: T201
        print("  2) Change fast model")  # noqa: T201
        print("  3) Change output root")  # noqa: T201
        print("  b) Back")  # noqa: T201

        try:
            choice = (await _async_input("\n> ")).strip().lower()
        except (EOFError, KeyboardInterrupt):
            return

        if choice in ("b", "back"):
            return
        if choice == "1":
            model = (await _async_input("  Model name: ")).strip()
            if model:
                settings["model"] = model
        elif choice == "2":
            fast = (await _async_input("  Fast model name (empty for same as model): ")).strip()
            settings["fast_model"] = fast or None
        elif choice == "3":
            root = (await _async_input("  Output root directory: ")).strip()
            if root:
                settings["output_root"] = root


async def _guided_new_brainstorm(settings: dict[str, str | None]) -> int:
    """Start a new brainstorm from the guided menu.

    Args:
        settings: Current session settings.

    Returns:
        Exit code.
    """
    print("\nWhat's your idea? Describe it in a sentence or two.")  # noqa: T201
    print("(This will guide the brainstorm — you can refine as we go.)\n")  # noqa: T201

    try:
        idea = (await _async_input("> ")).strip()
    except (EOFError, KeyboardInterrupt):
        return 0

    if not idea:
        print("  No idea entered.")  # noqa: T201
        return 0

    # Optional codebase context file
    codebase_context = None
    print("  Codebase context file? (path to CLAUDE.md or similar, Enter to skip)")  # noqa: T201
    while True:
        try:
            ctx_path = (await _async_input("> ")).strip()
        except (EOFError, KeyboardInterrupt):
            return 0

        if not ctx_path:
            break
        if Path(ctx_path).exists():
            codebase_context = ctx_path
            break
        print(f"  File not found: {ctx_path}")  # noqa: T201
        print("  Try again, or Enter to skip.")  # noqa: T201

    # Construct args namespace with defaults
    args = argparse.Namespace(
        command="brainstorm",
        idea=idea,
        output_dir=None,  # _run_brainstorm will use default: superagents-output/{slug}
        context_dir=None,
        codebase_context=codebase_context,
        model=settings["model"],
        fast_model=settings["fast_model"],
        max_tokens=int(settings["max_tokens"] or "16384"),
        stub=False,
        quiet=False,
        verbose=False,
        json=False,
        interactive=False,
    )

    return await _run_brainstorm(args)


async def _guided_resume_session(  # noqa: C901, PLR0911, PLR0912
    session: dict[str, object],
    settings: dict[str, str | None],
) -> int:
    """Resume a previous session based on its manifest state.

    Args:
        session: Manifest dict with output_dir key.
        settings: Current session settings.

    Returns:
        Exit code.
    """
    from superagents_sdlc.manifest import _state_display  # noqa: PLC0415

    output_dir = Path(str(session["output_dir"]))
    state = str(session.get("state", ""))
    idea = str(session.get("idea", "untitled"))
    state_str = _state_display(state)

    print(f"\n  Session: {idea}")  # noqa: T201
    print(f"  State: {state_str}")  # noqa: T201
    print(f"  Directory: {output_dir}\n")  # noqa: T201

    if state == "brainstorming":
        print("  This brainstorm didn't finish. Start fresh with the same idea? (y/n)")  # noqa: T201
        try:
            choice = (await _async_input("  > ")).strip().lower()
        except (EOFError, KeyboardInterrupt):
            return 0
        if choice in ("y", "yes"):
            args = argparse.Namespace(
                command="brainstorm",
                idea=idea,
                output_dir=str(output_dir),
                context_dir=None,
                codebase_context=None,
                model=settings["model"],
                fast_model=settings["fast_model"],
                max_tokens=int(settings["max_tokens"] or "16384"),
                stub=False,
                quiet=False,
                verbose=False,
                json=False,
                interactive=False,
            )
            return await _run_brainstorm(args)

    elif state == "brief_ready":
        print("  1) Send to pipeline")  # noqa: T201
        print("  2) View brief")  # noqa: T201
        print("  3) Start over")  # noqa: T201
        try:
            choice = (await _async_input("  > ")).strip()
        except (EOFError, KeyboardInterrupt):
            return 0

        if choice == "1":
            # Build pipeline command from manifest
            model = str(session.get("model", settings["model"]))
            fast_model = session.get("fast_model", settings["fast_model"])
            cmd = [
                "uv",
                "run",
                "superagents-sdlc",
                "idea-to-code",
                idea,
                "--brief",
                str(output_dir / "design_brief.md"),
                "--output-dir",
                str(output_dir / "pipeline"),
                "--interactive",
            ]
            if (output_dir / "idea_memory.md").exists():
                cmd.extend(["--idea-memory", str(output_dir / "idea_memory.md")])
            if model:
                cmd.extend(["--model", model])
            if fast_model:
                cmd.extend(["--fast-model", str(fast_model)])
            print(f"\n  Launching pipeline: {' '.join(cmd)}")  # noqa: T201
            proc = subprocess.run(cmd, check=False)  # noqa: S603
            print(f"\n  Pipeline complete (exit code {proc.returncode}).")  # noqa: T201

        elif choice == "2":
            brief_path = output_dir / "design_brief.md"
            if brief_path.exists():
                print(f"\n  Brief: {brief_path}")  # noqa: T201
            else:
                print("  Brief file not found.")  # noqa: T201

        elif choice == "3":
            args = argparse.Namespace(
                command="brainstorm",
                idea=idea,
                output_dir=str(output_dir),
                context_dir=None,
                codebase_context=None,
                model=settings["model"],
                fast_model=settings["fast_model"],
                max_tokens=int(settings["max_tokens"] or "16384"),
                stub=False,
                quiet=False,
                verbose=False,
                json=False,
                interactive=False,
            )
            return await _run_brainstorm(args)

    elif state == "pipeline_complete":
        cert = str(session.get("pipeline", {}).get("certification", "unknown"))
        print(f"  Pipeline finished — {cert}.")  # noqa: T201
        print("  1) View artifacts")  # noqa: T201
        print("  2) Start a new brainstorm")  # noqa: T201
        try:
            choice = (await _async_input("  > ")).strip()
        except (EOFError, KeyboardInterrupt):
            return 0

        if choice == "1":
            pipeline_dir = output_dir / "pipeline"
            print(f"\n  Artifacts: {pipeline_dir}")  # noqa: T201
        # choice == "2" falls through to return 0, which loops back to main menu

    elif state == "pipeline_needs_work":
        cert = str(session.get("pipeline", {}).get("certification", "NEEDS WORK"))
        print(f"  Pipeline finished — {cert}.")  # noqa: T201
        print("  1) View findings")  # noqa: T201
        print("  2) Re-run pipeline")  # noqa: T201
        print("  3) Start a new brainstorm")  # noqa: T201
        try:
            choice = (await _async_input("  > ")).strip()
        except (EOFError, KeyboardInterrupt):
            return 0

        if choice == "1":
            report = output_dir / "pipeline" / "qa" / "validation_report.md"
            print(f"\n  Findings: {report}")  # noqa: T201
        elif choice == "2":
            model = str(session.get("model", settings["model"]))
            fast_model = session.get("fast_model", settings["fast_model"])
            cmd = [
                "uv",
                "run",
                "superagents-sdlc",
                "idea-to-code",
                idea,
                "--brief",
                str(output_dir / "design_brief.md"),
                "--output-dir",
                str(output_dir / "pipeline"),
                "--interactive",
            ]
            if (output_dir / "idea_memory.md").exists():
                cmd.extend(["--idea-memory", str(output_dir / "idea_memory.md")])
            if model:
                cmd.extend(["--model", model])
            if fast_model:
                cmd.extend(["--fast-model", str(fast_model)])
            print(f"\n  Launching pipeline: {' '.join(cmd)}")  # noqa: T201
            proc = subprocess.run(cmd, check=False)  # noqa: S603
            print(f"\n  Pipeline complete (exit code {proc.returncode}).")  # noqa: T201

    return 0


def guided_main() -> None:
    """Zero-config guided CLI entry point.

    Presents an interactive menu for starting new brainstorms,
    resuming previous sessions, and launching pipelines. Power-user
    flags are available via the ``superagents-sdlc`` command instead.
    """
    try:
        from dotenv import load_dotenv  # noqa: PLC0415

        load_dotenv()
    except ImportError:
        pass

    try:
        code = asyncio.run(_guided_flow())
    except (FileNotFoundError, ValueError, RuntimeError, TypeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)  # noqa: T201
        sys.exit(1)
    except KeyboardInterrupt:
        sys.exit(130)
    else:
        sys.exit(code)


if __name__ == "__main__":
    main()
