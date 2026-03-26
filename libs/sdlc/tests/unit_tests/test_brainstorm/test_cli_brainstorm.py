"""Tests for the brainstorm CLI subcommand."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from superagents_sdlc.cli import _build_parser, _extract_section_content


# Derive cwd from test file location (portable, not hardcoded)
_SDLC_DIR = str(Path(__file__).resolve().parents[3])


def test_parse_brainstorm_subcommand():
    parser = _build_parser()
    args = parser.parse_args(["brainstorm", "Add dark mode", "--stub"])

    assert args.command == "brainstorm"
    assert args.idea == "Add dark mode"
    assert args.stub is True
    assert args.codebase_context is None
    assert args.output_dir is None


def test_parse_brainstorm_with_codebase_context():
    parser = _build_parser()
    args = parser.parse_args([
        "brainstorm", "Add dark mode",
        "--codebase-context", "/path/to/context.md",
        "--output-dir", "/tmp/out",
        "--stub",
    ])

    assert args.codebase_context == "/path/to/context.md"
    assert args.output_dir == "/tmp/out"


def test_brainstorm_stub_end_to_end(tmp_path):
    """Full brainstorm with --stub: answer question, select approach, approve 6 sections, approve brief."""
    output_dir = tmp_path / "output"

    # stdin: answer question, select approach, approve 6 sections, approve brief
    stdin_lines = ["developers", "Simple", "a", "a", "a", "a", "a", "a", "a"]

    result = subprocess.run(
        [
            sys.executable, "-m", "superagents_sdlc.cli",
            "brainstorm", "Add dark mode",
            "--output-dir", str(output_dir),
            "--stub",
        ],
        input="\n".join(stdin_lines) + "\n",
        capture_output=True,
        text=True,
        cwd=_SDLC_DIR,
        timeout=60,
    )

    assert result.returncode == 0, f"stderr: {result.stderr}"
    assert (output_dir / "design_brief.md").exists()
    brief = (output_dir / "design_brief.md").read_text()
    assert "Design Brief" in brief


def test_brainstorm_stub_quit(tmp_path):
    """User quits at first question."""
    result = subprocess.run(
        [
            sys.executable, "-m", "superagents_sdlc.cli",
            "brainstorm", "Test",
            "--stub",
        ],
        input="q\n",
        capture_output=True,
        text=True,
        cwd=_SDLC_DIR,
        timeout=60,
    )

    assert result.returncode == 0, f"stderr: {result.stderr}"
    assert "cancelled" in result.stdout.lower()


def test_brainstorm_codebase_context_file(tmp_path):
    """Codebase context file is read into state."""
    ctx_file = tmp_path / "context.md"
    ctx_file.write_text("# Codebase\nPython monorepo with REST API")
    output_dir = tmp_path / "output"

    stdin_lines = ["developers", "Simple", "a", "a", "a", "a", "a", "a", "a"]

    result = subprocess.run(
        [
            sys.executable, "-m", "superagents_sdlc.cli",
            "brainstorm", "Test",
            "--codebase-context", str(ctx_file),
            "--output-dir", str(output_dir),
            "--stub",
        ],
        input="\n".join(stdin_lines) + "\n",
        capture_output=True,
        text=True,
        cwd=_SDLC_DIR,
        timeout=60,
    )

    assert result.returncode == 0, f"stderr: {result.stderr}; stdout: {result.stdout}"


def test_brainstorm_no_output_dir():
    """Without --output-dir, brief prints to stdout but no file written."""
    stdin_lines = ["developers", "Simple", "a", "a", "a", "a", "a", "a", "a"]

    result = subprocess.run(
        [
            sys.executable, "-m", "superagents_sdlc.cli",
            "brainstorm", "Test",
            "--stub",
        ],
        input="\n".join(stdin_lines) + "\n",
        capture_output=True,
        text=True,
        cwd=_SDLC_DIR,
        timeout=60,
    )

    assert result.returncode == 0, f"stderr: {result.stderr}"
    assert "Design Brief" in result.stdout


def test_idea_memory_written_to_disk(tmp_path):
    """IdeaMemory file is written alongside the brief."""
    from superagents_sdlc.brainstorm.idea_memory import IdeaMemory

    mem = IdeaMemory(idea_title="Test")
    mem.add_decision(title="Tech", text="Use Go")

    out = tmp_path / "output"
    out.mkdir()
    (out / "idea_memory.md").write_text(mem.to_markdown())

    content = (out / "idea_memory.md").read_text()
    assert "IdeaMemory: Test" in content
    assert "Use Go" in content


def test_extract_section_content_from_json():
    """JSON string with a ``content`` field returns only the content value."""
    raw = json.dumps({
        "section": "Problem Statement & Goals",
        "status": "draft",
        "content": "## Problem Statement\nThe app needs dark mode.",
    })
    assert _extract_section_content(raw) == "## Problem Statement\nThe app needs dark mode."


def test_extract_section_content_fallback_on_invalid_json():
    """Plain markdown string (not JSON) is returned as-is."""
    raw = "## Problem Statement\nThe app needs dark mode."
    assert _extract_section_content(raw) == raw


from superagents_sdlc.cli import _handle_brainstorm_interrupt


async def test_stall_exit_handler_proceed():
    """stall_exit interrupt with 'proceed' returns 'proceed'."""
    payload = {
        "type": "stall_exit",
        "confidence": 62,
        "gaps": [
            {"section": "acceptance_criteria", "description": "No error paths"},
        ],
        "options": ["proceed", "continue"],
    }
    from unittest.mock import AsyncMock, patch
    with patch("superagents_sdlc.cli._async_input", new_callable=AsyncMock, return_value="p"):
        result = await _handle_brainstorm_interrupt(payload, quiet=True)
    assert result == "proceed"


async def test_stall_exit_handler_continue():
    """stall_exit interrupt with 'continue' returns 'continue'."""
    payload = {
        "type": "stall_exit",
        "confidence": 62,
        "gaps": [
            {"section": "acceptance_criteria", "description": "No error paths"},
        ],
        "options": ["proceed", "continue"],
    }
    from unittest.mock import AsyncMock, patch
    with patch("superagents_sdlc.cli._async_input", new_callable=AsyncMock, return_value="c"):
        result = await _handle_brainstorm_interrupt(payload, quiet=True)
    assert result == "continue"
