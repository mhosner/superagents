"""Standalone CLI for superagents-sdlc pipelines."""

from __future__ import annotations

import argparse
from pathlib import Path

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
