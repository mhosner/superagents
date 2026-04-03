"""Tests for the brainstorm CLI subcommand."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from unittest.mock import AsyncMock, MagicMock, patch

from superagents_sdlc.brainstorm.sidekick import SidekickContext
from superagents_sdlc.cli import (
    _build_parser,
    _build_pipeline_command,
    _build_sidekick_context,
    _extract_section_content,
    _handle_brainstorm_interrupt,
    _prompt_with_help,
    _run_brainstorm,
    _slugify,
)
from superagents_sdlc.skills.llm import StubLLMClient


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
    args = parser.parse_args(
        [
            "brainstorm",
            "Add dark mode",
            "--codebase-context",
            "/path/to/context.md",
            "--output-dir",
            "/tmp/out",
            "--stub",
        ]
    )

    assert args.codebase_context == "/path/to/context.md"
    assert args.output_dir == "/tmp/out"


def test_brainstorm_stub_end_to_end(tmp_path):
    """Full brainstorm with --stub: answer question, select approach, approve 6 sections, approve brief, then done."""
    output_dir = tmp_path / "output"

    # stdin: answer question, select approach, approve 6 sections, approve brief, handoff=done
    stdin_lines = ["developers", "Simple", "a", "a", "a", "a", "a", "a", "a", "d"]

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "superagents_sdlc.cli",
            "brainstorm",
            "Add dark mode",
            "--output-dir",
            str(output_dir),
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
            sys.executable,
            "-m",
            "superagents_sdlc.cli",
            "brainstorm",
            "Test",
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

    stdin_lines = ["developers", "Simple", "a", "a", "a", "a", "a", "a", "a", "d"]

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "superagents_sdlc.cli",
            "brainstorm",
            "Test",
            "--codebase-context",
            str(ctx_file),
            "--output-dir",
            str(output_dir),
            "--stub",
        ],
        input="\n".join(stdin_lines) + "\n",
        capture_output=True,
        text=True,
        cwd=_SDLC_DIR,
        timeout=60,
    )

    assert result.returncode == 0, f"stderr: {result.stderr}; stdout: {result.stdout}"


def test_brainstorm_no_output_dir_uses_default(tmp_path):
    """Without --output-dir, brief is written to superagents-output/{slug}/ in cwd."""
    stdin_lines = ["developers", "Simple", "a", "a", "a", "a", "a", "a", "a", "d"]

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "superagents_sdlc.cli",
            "brainstorm",
            "Test",
            "--stub",
        ],
        input="\n".join(stdin_lines) + "\n",
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
        timeout=60,
    )

    assert result.returncode == 0, f"stderr: {result.stderr}\nstdout: {result.stdout}"
    expected = tmp_path / "superagents-output" / "test"
    assert expected.exists(), f"Expected default output dir {expected} to be created"
    assert (expected / "design_brief.md").exists()


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
    raw = json.dumps(
        {
            "section": "Problem Statement & Goals",
            "status": "draft",
            "content": "## Problem Statement\nThe app needs dark mode.",
        }
    )
    assert _extract_section_content(raw) == "## Problem Statement\nThe app needs dark mode."


def test_extract_section_content_fallback_on_invalid_json():
    """Plain markdown string (not JSON) is returned as-is."""
    raw = "## Problem Statement\nThe app needs dark mode."
    assert _extract_section_content(raw) == raw


async def test_cli_returns_question_metadata_with_answer():
    """CLI returns dict with resolved answer + question metadata."""
    payload = {
        "type": "questions",
        "questions": [
            {
                "question": "How to handle cycles?",
                "options": [
                    "Merge into super-slice",
                    "Emit with circular flag",
                    "Break weakest edge",
                    "Halt with error",
                ],
                "targets_section": "technical_constraints",
            },
        ],
        "round": 1,
        "confidence": 40,
    }
    with patch("superagents_sdlc.cli._async_input", new_callable=AsyncMock, return_value="2"):
        result = await _handle_brainstorm_interrupt(payload, quiet=True)
    assert len(result) == 1
    assert result[0]["answer"] == "Emit with circular flag"
    assert result[0]["targets_section"] == "technical_constraints"
    assert result[0]["question_text"] == "How to handle cycles?"


async def test_cli_freetext_answer_includes_metadata():
    """Free-text answer includes metadata from the question."""
    payload = {
        "type": "questions",
        "questions": [
            {
                "question": "Who are the users?",
                "options": None,
                "targets_section": "users_and_personas",
            },
        ],
        "round": 1,
        "confidence": 40,
    }
    with patch(
        "superagents_sdlc.cli._async_input", new_callable=AsyncMock, return_value="DevOps engineers"
    ):
        result = await _handle_brainstorm_interrupt(payload, quiet=True)
    assert result[0]["answer"] == "DevOps engineers"
    assert result[0]["targets_section"] == "users_and_personas"


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
    with patch("superagents_sdlc.cli._async_input", new_callable=AsyncMock, return_value="c"):
        result = await _handle_brainstorm_interrupt(payload, quiet=True)
    assert result == "continue"


# --- B-05: disk-write before approval tests ---


def test_section_filename_slugification():
    """Section titles produce clean filenames without special chars."""
    assert _slugify("Problem Statement & Goals") == "problem_statement_goals"
    assert _slugify("Technical Constraints / Architecture") == "technical_constraints_architecture"
    assert _slugify("  Leading & Trailing  ") == "leading_trailing"
    assert _slugify("Target Users & Personas") == "target_users_personas"


async def test_design_section_writes_to_disk_before_approval(tmp_path, capsys):
    """design_section interrupt writes file to disk; path shown, content not printed."""
    payload = {
        "type": "design_section",
        "title": "Problem Statement & Goals",
        "content": "## Problem Statement\nThe app needs dark mode.",
    }
    with patch("superagents_sdlc.cli._async_input", new_callable=AsyncMock, return_value="approve"):
        result = await _handle_brainstorm_interrupt(payload, quiet=False, output_dir=tmp_path)

    expected_path = tmp_path / "sections" / "problem_statement_goals.md"
    assert expected_path.exists()
    assert expected_path.read_text() == "## Problem Statement\nThe app needs dark mode."

    captured = capsys.readouterr()
    assert "## Problem Statement" not in captured.out
    assert str(expected_path) in captured.out
    assert result == "approve"


async def test_design_section_edit_writes_back(tmp_path):
    """When user edits a section, the edited text is written back to disk."""
    payload = {
        "type": "design_section",
        "title": "Problem Statement & Goals",
        "content": "## Problem Statement\nOriginal content.",
    }
    with patch(
        "superagents_sdlc.cli._async_input",
        new_callable=AsyncMock,
        return_value="## Problem Statement\nEdited by user.",
    ):
        result = await _handle_brainstorm_interrupt(payload, quiet=True, output_dir=tmp_path)

    expected_path = tmp_path / "sections" / "problem_statement_goals.md"
    assert expected_path.read_text() == "## Problem Statement\nEdited by user."
    assert result == "## Problem Statement\nEdited by user."


async def test_brief_writes_to_disk_before_approval(tmp_path, capsys):
    """brief interrupt writes design_brief.md to disk; path shown, content not printed."""
    payload = {
        "type": "brief",
        "brief": "# Design Brief\nFull brief content here.",
    }
    with patch("superagents_sdlc.cli._async_input", new_callable=AsyncMock, return_value="approve"):
        result = await _handle_brainstorm_interrupt(payload, quiet=False, output_dir=tmp_path)

    brief_path = tmp_path / "design_brief.md"
    assert brief_path.exists()
    assert brief_path.read_text() == "# Design Brief\nFull brief content here."

    captured = capsys.readouterr()
    assert "Full brief content here" not in captured.out
    assert str(brief_path) in captured.out
    assert result == "approve"


async def test_no_output_dir_prints_inline(capsys):
    """Without output_dir, section content and brief are printed inline (current behavior)."""
    section_payload = {
        "type": "design_section",
        "title": "Problem Statement & Goals",
        "content": "## Problem Statement\nThe app needs dark mode.",
    }
    with patch("superagents_sdlc.cli._async_input", new_callable=AsyncMock, return_value="approve"):
        await _handle_brainstorm_interrupt(section_payload, quiet=False, output_dir=None)

    captured = capsys.readouterr()
    assert "## Problem Statement" in captured.out

    brief_payload = {
        "type": "brief",
        "brief": "# Design Brief\nFull brief content here.",
    }
    with patch("superagents_sdlc.cli._async_input", new_callable=AsyncMock, return_value="approve"):
        await _handle_brainstorm_interrupt(brief_payload, quiet=False, output_dir=None)

    captured = capsys.readouterr()
    assert "Full brief content here" in captured.out


async def test_quiet_mode_still_writes_to_disk(tmp_path, capsys):
    """quiet=True suppresses printing but still writes files when output_dir is provided."""
    section_payload = {
        "type": "design_section",
        "title": "Problem Statement & Goals",
        "content": "## Problem Statement\nContent.",
    }
    with patch("superagents_sdlc.cli._async_input", new_callable=AsyncMock, return_value="approve"):
        await _handle_brainstorm_interrupt(section_payload, quiet=True, output_dir=tmp_path)

    assert (tmp_path / "sections" / "problem_statement_goals.md").exists()
    captured = capsys.readouterr()
    assert captured.out == ""


# --- F-09: brainstorm → pipeline handoff tests ---


def _make_args(
    idea: str = "Add dark mode",
    output_dir: str | None = None,
    codebase_context: str | None = None,
    quiet: bool = False,
    verbose: bool = False,
    stub: bool = True,
    interactive: bool = False,
    model: str = "claude-sonnet-4-6",
    max_tokens: int = 16384,
    fast_model: str | None = None,
    context_dir: str | None = None,
) -> argparse.Namespace:
    """Build a minimal argparse.Namespace for _run_brainstorm."""
    return argparse.Namespace(
        idea=idea,
        output_dir=output_dir,
        codebase_context=codebase_context,
        quiet=quiet,
        verbose=verbose,
        stub=stub,
        interactive=interactive,
        model=model,
        max_tokens=max_tokens,
        fast_model=fast_model,
        context_dir=context_dir,
    )


def _make_complete_graph() -> MagicMock:
    """Return a mock graph that immediately returns a complete brainstorm state."""
    mock_graph = MagicMock()
    mock_graph.ainvoke = AsyncMock(
        return_value={
            "status": "complete",
            "brief": "# Design Brief\nTest brief.",
            "idea_memory": [],
            "idea_memory_counts": {"decision": 0, "rejection": 0},
        }
    )
    return mock_graph


def test_default_output_dir_from_idea(tmp_path):
    """No --output-dir defaults to superagents-output/{slug}/ in cwd."""
    stdin_lines = ["developers", "Simple", "a", "a", "a", "a", "a", "a", "a", "d"]

    result = subprocess.run(
        [sys.executable, "-m", "superagents_sdlc.cli", "brainstorm", "Add dark mode", "--stub"],
        input="\n".join(stdin_lines) + "\n",
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
        timeout=60,
    )

    assert result.returncode == 0, f"stderr: {result.stderr}\nstdout: {result.stdout}"
    expected = tmp_path / "superagents-output" / "add_dark_mode"
    assert expected.exists(), f"Expected default output dir {expected} to be created"
    assert (expected / "design_brief.md").exists()


def test_output_dir_overwrite_prompt_yes(tmp_path):
    """When default dir exists with files, 'y' allows overwrite and brainstorm proceeds."""
    default_dir = tmp_path / "superagents-output" / "add_dark_mode"
    default_dir.mkdir(parents=True)
    (default_dir / "existing_file.md").write_text("old content")

    # "y" = overwrite, then brainstorm flow, then "d" = done
    stdin_lines = ["y", "developers", "Simple", "a", "a", "a", "a", "a", "a", "a", "d"]

    result = subprocess.run(
        [sys.executable, "-m", "superagents_sdlc.cli", "brainstorm", "Add dark mode", "--stub"],
        input="\n".join(stdin_lines) + "\n",
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
        timeout=60,
    )

    assert result.returncode == 0, f"stderr: {result.stderr}\nstdout: {result.stdout}"
    assert "already exists" in result.stdout or "Overwrite" in result.stdout
    assert (default_dir / "design_brief.md").exists()


def test_output_dir_overwrite_prompt_no_then_alternative(tmp_path):
    """'n' at overwrite prompt lets user specify an alternative output path."""
    default_dir = tmp_path / "superagents-output" / "add_dark_mode"
    default_dir.mkdir(parents=True)
    (default_dir / "existing_file.md").write_text("old content")

    alt_dir = tmp_path / "my_output"

    stdin_lines = [
        "n",  # decline overwrite
        str(alt_dir),  # alternative path
        "developers",
        "Simple",
        "a",
        "a",
        "a",
        "a",
        "a",
        "a",
        "a",
        "d",  # handoff = done
    ]

    result = subprocess.run(
        [sys.executable, "-m", "superagents_sdlc.cli", "brainstorm", "Add dark mode", "--stub"],
        input="\n".join(stdin_lines) + "\n",
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
        timeout=60,
    )

    assert result.returncode == 0, f"stderr: {result.stderr}\nstdout: {result.stdout}"
    assert (alt_dir / "design_brief.md").exists(), "Brief should be at alternative path"


def test_handoff_prompt_done_exits(tmp_path):
    """'d' at handoff prompt exits without spawning pipeline."""
    output_dir = tmp_path / "output"
    stdin_lines = ["developers", "Simple", "a", "a", "a", "a", "a", "a", "a", "d"]

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "superagents_sdlc.cli",
            "brainstorm",
            "Add dark mode",
            "--stub",
            "--output-dir",
            str(output_dir),
        ],
        input="\n".join(stdin_lines) + "\n",
        capture_output=True,
        text=True,
        cwd=_SDLC_DIR,
        timeout=60,
    )

    assert result.returncode == 0, f"stderr: {result.stderr}"
    assert "(p)ipeline" in result.stdout or "pipeline" in result.stdout.lower()
    assert not (output_dir / "pipeline").exists()


async def test_handoff_prompt_pipeline_spawns_subprocess(tmp_path):
    """'p' at handoff prompt spawns idea-to-code subprocess with correct args."""
    output_dir = tmp_path / "output"
    output_dir.mkdir()

    args = _make_args(idea="Add dark mode", output_dir=str(output_dir), quiet=False)
    mock_proc = MagicMock(returncode=0)

    with (
        patch(
            "superagents_sdlc.brainstorm.graph.build_brainstorm_graph",
            return_value=_make_complete_graph(),
        ),
        patch("subprocess.run", return_value=mock_proc) as mock_run,
        patch("superagents_sdlc.cli._async_input", new_callable=AsyncMock, return_value="p"),
        patch("superagents_sdlc.cli_spinner.print_banner"),
        patch("superagents_sdlc.cli_spinner.Spinner"),
    ):
        exit_code = await _run_brainstorm(args)

    assert exit_code == 0
    mock_run.assert_called_once()
    cmd = mock_run.call_args[0][0]
    assert "idea-to-code" in cmd
    assert "Add dark mode" in cmd
    assert "--brief" in cmd
    assert str(output_dir / "design_brief.md") in cmd
    assert "--idea-memory" in cmd
    assert str(output_dir / "idea_memory.md") in cmd
    assert any(str(output_dir / "pipeline") in arg for arg in cmd)


async def test_handoff_writes_handoff_md(tmp_path):
    """After pipeline run, handoff.md is written with key metadata."""
    output_dir = tmp_path / "output"
    output_dir.mkdir()

    args = _make_args(idea="Add dark mode", output_dir=str(output_dir), quiet=False)
    mock_proc = MagicMock(returncode=0)

    with (
        patch(
            "superagents_sdlc.brainstorm.graph.build_brainstorm_graph",
            return_value=_make_complete_graph(),
        ),
        patch("subprocess.run", return_value=mock_proc),
        patch("superagents_sdlc.cli._async_input", new_callable=AsyncMock, return_value="p"),
        patch("superagents_sdlc.cli_spinner.print_banner"),
        patch("superagents_sdlc.cli_spinner.Spinner"),
    ):
        await _run_brainstorm(args)

    handoff_path = output_dir / "handoff.md"
    assert handoff_path.exists()
    content = handoff_path.read_text()
    assert "Add dark mode" in content
    assert "design_brief.md" in content
    assert "idea_memory.md" in content
    assert "pipeline" in content


def test_quiet_mode_skips_handoff_prompt(tmp_path):
    """quiet=True exits after brief without showing handoff prompt."""
    output_dir = tmp_path / "output"
    # No "d" needed — quiet mode skips handoff prompt
    stdin_lines = ["developers", "Simple", "a", "a", "a", "a", "a", "a", "a"]

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "superagents_sdlc.cli",
            "brainstorm",
            "Add dark mode",
            "--stub",
            "--quiet",
            "--output-dir",
            str(output_dir),
        ],
        input="\n".join(stdin_lines) + "\n",
        capture_output=True,
        text=True,
        cwd=_SDLC_DIR,
        timeout=60,
    )

    assert result.returncode == 0, f"stderr: {result.stderr}"
    assert not (output_dir / "handoff.md").exists()


async def test_codebase_context_forwarded(tmp_path):
    """--codebase-context is forwarded to the pipeline subprocess command."""
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    ctx_file = tmp_path / "context.md"
    ctx_file.write_text("# Context")

    args = _make_args(
        idea="Add dark mode",
        output_dir=str(output_dir),
        codebase_context=str(ctx_file),
        quiet=False,
    )
    mock_proc = MagicMock(returncode=0)

    with (
        patch(
            "superagents_sdlc.brainstorm.graph.build_brainstorm_graph",
            return_value=_make_complete_graph(),
        ),
        patch("subprocess.run", return_value=mock_proc) as mock_run,
        patch("superagents_sdlc.cli._async_input", new_callable=AsyncMock, return_value="p"),
        patch("superagents_sdlc.cli_spinner.print_banner"),
        patch("superagents_sdlc.cli_spinner.Spinner"),
    ):
        await _run_brainstorm(args)

    cmd = mock_run.call_args[0][0]
    assert "--codebase-context" in cmd
    assert str(ctx_file) in cmd


def test_build_pipeline_command_basic(tmp_path):
    """_build_pipeline_command returns expected argument list."""
    args = _make_args(idea="Add dark mode", output_dir=str(tmp_path))
    output_dir = Path(tmp_path)

    cmd = _build_pipeline_command(args, output_dir)

    assert "idea-to-code" in cmd
    assert "Add dark mode" in cmd
    assert "--brief" in cmd
    assert str(output_dir / "design_brief.md") in cmd
    assert "--idea-memory" in cmd
    assert str(output_dir / "idea_memory.md") in cmd
    assert "--output-dir" in cmd
    assert str(output_dir / "pipeline") in cmd


def test_build_pipeline_command_includes_codebase_context(tmp_path):
    """_build_pipeline_command includes --codebase-context when set."""
    args = _make_args(idea="Test", output_dir=str(tmp_path), codebase_context="/path/ctx.md")
    cmd = _build_pipeline_command(args, Path(tmp_path))
    assert "--codebase-context" in cmd
    assert "/path/ctx.md" in cmd


# --- F-06: Auto-continue when confidence is far below threshold ---


async def test_auto_continue_when_far_below_threshold(capsys):
    """Auto-continue when confidence is far below threshold on round > 1."""
    payload = {
        "type": "confidence_assessment",
        "confidence": 45,
        "threshold": 80,
        "round": 2,
        "sections": {},
        "summaries": {},
        "gaps": [{"section": "goals", "description": "Missing success metrics"}],
        "options": ["continue", "defer", "override"],
    }
    mock_input = AsyncMock(return_value="continue")
    with patch("superagents_sdlc.cli._async_input", mock_input):
        result = await _handle_brainstorm_interrupt(payload, quiet=False)

    assert result == "auto_continue"
    mock_input.assert_not_called()
    captured = capsys.readouterr()
    assert "auto-continuing" in captured.out.lower()
    assert "█" in captured.out
    assert "1 area remaining" in captured.out


async def test_no_auto_continue_on_round_1(capsys):
    """Round 1 always shows the full prompt, even when far below threshold."""
    payload = {
        "type": "confidence_assessment",
        "confidence": 45,
        "threshold": 80,
        "round": 1,
        "sections": {},
        "summaries": {},
        "gaps": [{"section": "goals", "description": "Missing success metrics"}],
        "options": ["continue", "defer", "override"],
    }
    mock_input = AsyncMock(return_value="c")
    with patch("superagents_sdlc.cli._async_input", mock_input):
        result = await _handle_brainstorm_interrupt(payload, quiet=False)

    assert result == "continue"
    mock_input.assert_called()


async def test_no_auto_continue_when_close_to_threshold(capsys):
    """When gap <= margin, always prompt the user."""
    payload = {
        "type": "confidence_assessment",
        "confidence": 72,
        "threshold": 80,
        "round": 3,
        "sections": {},
        "summaries": {},
        "gaps": [{"section": "goals", "description": "Minor gap"}],
        "options": ["continue", "defer", "override"],
    }
    mock_input = AsyncMock(return_value="c")
    with patch("superagents_sdlc.cli._async_input", mock_input):
        result = await _handle_brainstorm_interrupt(payload, quiet=False)

    assert result == "continue"
    mock_input.assert_called()


async def test_auto_continue_exact_margin_boundary(capsys):
    """At exactly the margin (gap == 10), user is still prompted (gap > margin, not >=)."""
    payload = {
        "type": "confidence_assessment",
        "confidence": 70,
        "threshold": 80,
        "round": 2,
        "sections": {},
        "summaries": {},
        "gaps": [{"section": "goals", "description": "Some gap"}],
        "options": ["continue", "defer", "override"],
    }
    mock_input = AsyncMock(return_value="c")
    with patch("superagents_sdlc.cli._async_input", mock_input):
        result = await _handle_brainstorm_interrupt(payload, quiet=False)

    assert result == "continue"
    mock_input.assert_called()


async def test_auto_continue_quiet_mode(capsys):
    """quiet=True returns 'continue' without printing when far below threshold."""
    payload = {
        "type": "confidence_assessment",
        "confidence": 45,
        "threshold": 80,
        "round": 2,
        "sections": {},
        "summaries": {},
        "gaps": [{"section": "goals", "description": "Missing success metrics"}],
        "options": ["continue", "defer", "override"],
    }
    mock_input = AsyncMock(return_value="continue")
    with patch("superagents_sdlc.cli._async_input", mock_input):
        result = await _handle_brainstorm_interrupt(payload, quiet=True)

    assert result == "auto_continue"
    captured = capsys.readouterr()
    assert captured.out == ""


# --- F-07: auto-continue returns "auto_continue" ---


async def test_auto_continue_sends_auto_continue_value(capsys):
    """Auto-continue returns 'auto_continue', not 'continue'."""
    payload = {
        "type": "confidence_assessment",
        "confidence": 45,
        "threshold": 80,
        "round": 2,
        "sections": {},
        "summaries": {},
        "gaps": [{"section": "goals", "description": "Missing success metrics"}],
        "options": ["continue", "defer", "override"],
    }
    mock_input = AsyncMock(return_value="continue")
    with patch("superagents_sdlc.cli._async_input", mock_input):
        result = await _handle_brainstorm_interrupt(payload, quiet=False)

    assert result == "auto_continue"
    mock_input.assert_not_called()


def test_brainstorm_creates_manifest(tmp_path):
    """Brainstorm run creates .superagents.json in output dir."""
    stdin_lines = ["developers", "Simple", "a", "a", "a", "a", "a", "a", "a"]
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "superagents_sdlc.cli",
            "brainstorm",
            "Add dark mode",
            "--output-dir",
            str(tmp_path),
            "--stub",
            "--quiet",
        ],
        input="\n".join(stdin_lines) + "\n",
        capture_output=True,
        text=True,
        cwd=_SDLC_DIR,
        timeout=60,
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"
    assert (tmp_path / ".superagents.json").exists()


# -- Progress bar tests --


def test_render_progress_bar_midpoint():
    from superagents_sdlc.cli import _render_progress_bar

    result = _render_progress_bar(40, 80)
    assert "50%" in result
    assert "█" in result
    assert "─" in result
    filled = result.count("█")
    empty = result.count("─")
    assert filled == 10
    assert empty == 10


def test_render_progress_bar_full():
    from superagents_sdlc.cli import _render_progress_bar

    result = _render_progress_bar(80, 80)
    assert "Ready!" in result
    assert "─" not in result


def test_render_progress_bar_zero():
    from superagents_sdlc.cli import _render_progress_bar

    result = _render_progress_bar(0, 80)
    assert "0%" in result
    assert "█" not in result


def test_render_progress_bar_over_threshold():
    from superagents_sdlc.cli import _render_progress_bar

    result = _render_progress_bar(90, 80)
    assert "Ready!" in result
    assert "─" not in result


# -- Confidence drop message tests --


def test_confidence_drop_with_more_gaps():
    from superagents_sdlc.cli import _confidence_drop_message

    result = _confidence_drop_message(delta=-5, current_gaps=4, previous_gaps=2)
    assert "revealed new areas" in result.lower()


def test_confidence_drop_same_gaps():
    from superagents_sdlc.cli import _confidence_drop_message

    result = _confidence_drop_message(delta=-3, current_gaps=2, previous_gaps=2)
    assert "recalibrating" in result.lower()


def test_confidence_drop_positive():
    from superagents_sdlc.cli import _confidence_drop_message

    result = _confidence_drop_message(delta=5, current_gaps=1, previous_gaps=2)
    assert result == ""


# -- prompt_with_help tests --


async def test_help_stub_reprompts():
    from unittest.mock import AsyncMock, patch
    from superagents_sdlc.cli import _prompt_with_help

    mock_input = AsyncMock(side_effect=["?", "1"])
    with patch("superagents_sdlc.cli._async_input", mock_input):
        result = await _prompt_with_help()
    assert result == "1"
    assert mock_input.call_count == 2


async def test_help_stub_multiple_times():
    from unittest.mock import AsyncMock, patch
    from superagents_sdlc.cli import _prompt_with_help

    mock_input = AsyncMock(side_effect=["?", "?", "hello"])
    with patch("superagents_sdlc.cli._async_input", mock_input):
        result = await _prompt_with_help()
    assert result == "hello"
    assert mock_input.call_count == 3


# -- Redesigned interrupt output tests --


async def test_question_shows_progress_bar(capsys):
    """Questions interrupt displays a progress bar instead of raw confidence."""
    payload = {
        "type": "questions",
        "questions": [
            {
                "question": "Who are the users?",
                "options": ["developers", "PMs"],
                "targets_section": "users_and_personas",
            },
        ],
        "round": 1,
        "confidence": 40,
        "threshold": 80,
    }
    with patch("superagents_sdlc.cli._async_input", new_callable=AsyncMock, return_value="1"):
        await _handle_brainstorm_interrupt(payload, quiet=False)
    captured = capsys.readouterr()
    assert "█" in captured.out
    assert "─" in captured.out
    assert "Round" not in captured.out


async def test_question_hides_target_section_by_default(capsys):
    """Target section is hidden when verbose=False."""
    payload = {
        "type": "questions",
        "questions": [
            {
                "question": "Who are the users?",
                "options": None,
                "targets_section": "users_and_personas",
            },
        ],
        "round": 1,
        "confidence": 40,
        "threshold": 80,
    }
    with patch("superagents_sdlc.cli._async_input", new_callable=AsyncMock, return_value="devs"):
        await _handle_brainstorm_interrupt(payload, quiet=False, verbose=False)
    captured = capsys.readouterr()
    assert "targets:" not in captured.out


async def test_question_shows_target_section_verbose(capsys):
    """Target section is shown when verbose=True."""
    payload = {
        "type": "questions",
        "questions": [
            {
                "question": "Who are the users?",
                "options": None,
                "targets_section": "users_and_personas",
            },
        ],
        "round": 1,
        "confidence": 40,
        "threshold": 80,
    }
    with patch("superagents_sdlc.cli._async_input", new_callable=AsyncMock, return_value="devs"):
        await _handle_brainstorm_interrupt(payload, quiet=False, verbose=True)
    captured = capsys.readouterr()
    assert "[targets: users_and_personas]" in captured.out


async def test_confidence_assessment_slim_output(capsys):
    """Default confidence assessment shows progress bar and gap count, not sections."""
    payload = {
        "type": "confidence_assessment",
        "confidence": 40,
        "threshold": 80,
        "round": 1,
        "sections": {
            "problem_statement": {"readiness": "high"},
            "requirements": {"readiness": "medium"},
        },
        "summaries": {
            "problem_statement": "Clear goals",
            "requirements": "Basic features",
        },
        "gaps": [
            {"section": "technical_constraints", "description": "No tech chosen"},
        ],
        "options": ["continue", "defer", "override"],
    }
    with patch("superagents_sdlc.cli._async_input", new_callable=AsyncMock, return_value="c"):
        result = await _handle_brainstorm_interrupt(payload, quiet=False, verbose=False)
    assert result == "continue"
    captured = capsys.readouterr()
    assert "█" in captured.out
    assert "1 area still needs input" in captured.out
    # Slim mode hides section readiness
    assert "Section readiness:" not in captured.out
    assert "c) Continue" in captured.out
    assert "q) Quit" in captured.out


async def test_confidence_assessment_verbose_output(capsys):
    """Verbose confidence assessment shows section readiness and gaps."""
    payload = {
        "type": "confidence_assessment",
        "confidence": 40,
        "threshold": 80,
        "round": 1,
        "sections": {
            "problem_statement": {"readiness": "high"},
            "requirements": {"readiness": "medium"},
            "technical_constraints": {"readiness": "low"},
        },
        "summaries": {
            "problem_statement": "Clear goals",
            "requirements": "Basic features",
            "technical_constraints": "No tech chosen",
        },
        "gaps": [
            {"section": "technical_constraints", "description": "No storage chosen"},
        ],
        "options": ["continue", "defer", "override"],
    }
    with patch("superagents_sdlc.cli._async_input", new_callable=AsyncMock, return_value="c"):
        result = await _handle_brainstorm_interrupt(payload, quiet=False, verbose=True)
    assert result == "continue"
    captured = capsys.readouterr()
    assert "Section readiness:" in captured.out
    assert "✓ problem_statement:" in captured.out
    assert "~ requirements:" in captured.out
    assert "✗ technical_constraints:" in captured.out
    assert "Gaps:" in captured.out
    assert "No storage chosen" in captured.out
    assert "d) Defer sections" in captured.out
    assert "o) Override" in captured.out


async def test_design_section_step_counter(capsys, tmp_path):
    """Design section shows 1-based step counter from payload indices."""
    payload = {
        "type": "design_section",
        "title": "Technical Constraints",
        "content": "## Technical Constraints\nStub.",
        "section_index": 2,
        "section_count": 6,
    }
    with patch("superagents_sdlc.cli._async_input", new_callable=AsyncMock, return_value="a"):
        result = await _handle_brainstorm_interrupt(
            payload,
            quiet=False,
            output_dir=tmp_path,
        )
    assert result == "approve"
    captured = capsys.readouterr()
    assert "section 3 of 6" in captured.out
    assert "Technical Constraints" in captured.out


async def test_stall_exit_friendly_message(capsys):
    """Stall exit shows progress bar and friendly stall message."""
    payload = {
        "type": "stall_exit",
        "confidence": 65,
        "threshold": 80,
        "gaps": [
            {"section": "acceptance_criteria", "description": "No error paths"},
        ],
        "options": ["proceed", "continue"],
    }
    with patch("superagents_sdlc.cli._async_input", new_callable=AsyncMock, return_value="p"):
        result = await _handle_brainstorm_interrupt(payload, quiet=False)
    assert result == "proceed"
    captured = capsys.readouterr()
    assert "█" in captured.out
    assert "stalled" in captured.out.lower()
    assert "1 area still needs input" in captured.out
    assert "Move on to design" in captured.out


async def test_defer_override_hidden_by_default(capsys):
    """Defer and override options are hidden in slim (non-verbose) mode."""
    payload = {
        "type": "confidence_assessment",
        "confidence": 50,
        "threshold": 80,
        "round": 1,
        "sections": {},
        "summaries": {},
        "gaps": [{"section": "goals", "description": "Gap"}],
        "options": ["continue", "defer", "override"],
    }
    with patch("superagents_sdlc.cli._async_input", new_callable=AsyncMock, return_value="c"):
        await _handle_brainstorm_interrupt(payload, quiet=False, verbose=False)
    captured = capsys.readouterr()
    assert "d) Defer" not in captured.out
    assert "o) Override" not in captured.out


async def test_defer_override_visible_verbose(capsys):
    """Defer and override options are shown in verbose mode."""
    payload = {
        "type": "confidence_assessment",
        "confidence": 50,
        "threshold": 80,
        "round": 1,
        "sections": {},
        "summaries": {},
        "gaps": [{"section": "goals", "description": "Gap"}],
        "options": ["continue", "defer", "override"],
    }
    with patch("superagents_sdlc.cli._async_input", new_callable=AsyncMock, return_value="c"):
        await _handle_brainstorm_interrupt(payload, quiet=False, verbose=True)
    captured = capsys.readouterr()
    assert "d) Defer sections" in captured.out
    assert "o) Override" in captured.out


def test_verbose_flag_parsed():
    """--verbose flag is parsed on the brainstorm subcommand."""
    parser = _build_parser()
    args = parser.parse_args(["brainstorm", "Test idea", "--verbose", "--stub"])
    assert args.verbose is True

    args_short = parser.parse_args(["brainstorm", "Test idea", "-v", "--stub"])
    assert args_short.verbose is True

    args_default = parser.parse_args(["brainstorm", "Test idea", "--stub"])
    assert args_default.verbose is False


# --- Sidekick callout skill tests ---


async def test_help_menu_shown_on_question_mark():
    """? at a question prompt shows the sidekick sub-menu."""
    ctx = SidekickContext(
        idea="App",
        question_text="Q?",
        options=["A", "B"],
        targets_section="",
        decisions_so_far="",
        selected_approach="",
        product_context="",
    )
    llm = StubLLMClient(responses={})
    mock_input = AsyncMock(side_effect=["?", "b", "A"])
    with patch("superagents_sdlc.cli._async_input", mock_input):
        result = await _prompt_with_help("> ", sidekick_context=ctx, llm=llm)
    assert result == "A"


async def test_help_runs_skill_and_reprompts():
    """Selecting a skill runs it and then re-prompts for the real answer."""
    ctx = SidekickContext(
        idea="App",
        question_text="Storage?",
        options=["PostgreSQL", "SQLite"],
        targets_section="",
        decisions_so_far="",
        selected_approach="",
        product_context="",
    )
    llm = StubLLMClient(responses={"Analyze the pros and cons": "### PostgreSQL\n**Pros:** Great"})
    mock_input = AsyncMock(side_effect=["?", "1", "PostgreSQL"])
    with patch("superagents_sdlc.cli._async_input", mock_input):
        result = await _prompt_with_help("> ", sidekick_context=ctx, llm=llm)
    assert result == "PostgreSQL"
    assert len(llm.calls) == 1


async def test_help_without_context_shows_fallback():
    """? without sidekick context shows fallback message."""
    mock_input = AsyncMock(side_effect=["?", "answer"])
    with patch("superagents_sdlc.cli._async_input", mock_input):
        result = await _prompt_with_help("> ")
    assert result == "answer"


async def test_build_sidekick_context_questions():
    """_build_sidekick_context extracts question data from payload."""
    payload = {
        "type": "questions",
        "questions": [
            {
                "question": "Who are the users?",
                "options": ["devs", "PMs"],
                "targets_section": "users_and_personas",
            },
        ],
    }
    ctx = _build_sidekick_context(payload, idea="Dark mode")
    assert ctx.idea == "Dark mode"
    assert ctx.question_text == "Who are the users?"
    assert ctx.options == ["devs", "PMs"]
    assert ctx.targets_section == "users_and_personas"


async def test_build_sidekick_context_approaches():
    """_build_sidekick_context extracts approach names as options."""
    payload = {
        "type": "approaches",
        "approaches": [
            {"name": "Simple", "description": "desc", "tradeoffs": "t"},
            {"name": "Complex", "description": "desc", "tradeoffs": "t"},
        ],
    }
    ctx = _build_sidekick_context(payload, idea="Feature")
    assert ctx.options == ["Simple", "Complex"]


async def test_build_sidekick_context_with_state():
    """_build_sidekick_context uses brainstorm_state for approach and context."""
    payload = {
        "type": "questions",
        "questions": [
            {"question": "Q?", "options": ["A"], "targets_section": ""},
        ],
    }
    ctx = _build_sidekick_context(
        payload,
        idea="Feature",
        brainstorm_state={
            "selected_approach": "Microservices",
            "product_context": "SaaS platform",
        },
    )
    assert ctx.selected_approach == "Microservices"
    assert ctx.product_context == "SaaS platform"


# -- Guided new brainstorm codebase context tests --


async def test_guided_new_brainstorm_with_codebase_context(tmp_path):
    from unittest.mock import AsyncMock, patch

    from superagents_sdlc.cli import _guided_new_brainstorm

    ctx_file = tmp_path / "CLAUDE.md"
    ctx_file.write_text("# Codebase")

    mock_input = AsyncMock(side_effect=["My idea", str(ctx_file)])
    captured_args = []

    async def fake_run_brainstorm(args):
        captured_args.append(args)
        return 0

    with (
        patch("superagents_sdlc.cli._async_input", mock_input),
        patch("superagents_sdlc.cli._run_brainstorm", fake_run_brainstorm),
    ):
        await _guided_new_brainstorm({"model": "m", "fast_model": None, "max_tokens": "16384"})

    assert len(captured_args) == 1
    assert captured_args[0].codebase_context == str(ctx_file)


async def test_guided_new_brainstorm_skip_codebase_context():
    from unittest.mock import AsyncMock, patch

    from superagents_sdlc.cli import _guided_new_brainstorm

    mock_input = AsyncMock(side_effect=["My idea", ""])
    captured_args = []

    async def fake_run_brainstorm(args):
        captured_args.append(args)
        return 0

    with (
        patch("superagents_sdlc.cli._async_input", mock_input),
        patch("superagents_sdlc.cli._run_brainstorm", fake_run_brainstorm),
    ):
        await _guided_new_brainstorm({"model": "m", "fast_model": None, "max_tokens": "16384"})

    assert len(captured_args) == 1
    assert captured_args[0].codebase_context is None


async def test_guided_new_brainstorm_invalid_path_retries(tmp_path):
    from unittest.mock import AsyncMock, patch

    from superagents_sdlc.cli import _guided_new_brainstorm

    valid_file = tmp_path / "CLAUDE.md"
    valid_file.write_text("# Codebase")

    mock_input = AsyncMock(side_effect=["My idea", "/nonexistent/path.md", str(valid_file)])
    captured_args = []

    async def fake_run_brainstorm(args):
        captured_args.append(args)
        return 0

    with (
        patch("superagents_sdlc.cli._async_input", mock_input),
        patch("superagents_sdlc.cli._run_brainstorm", fake_run_brainstorm),
    ):
        await _guided_new_brainstorm({"model": "m", "fast_model": None, "max_tokens": "16384"})

    assert len(captured_args) == 1
    assert captured_args[0].codebase_context == str(valid_file)


async def test_guided_new_brainstorm_invalid_path_then_skip():
    from unittest.mock import AsyncMock, patch

    from superagents_sdlc.cli import _guided_new_brainstorm

    mock_input = AsyncMock(side_effect=["My idea", "/nonexistent/path.md", ""])
    captured_args = []

    async def fake_run_brainstorm(args):
        captured_args.append(args)
        return 0

    with (
        patch("superagents_sdlc.cli._async_input", mock_input),
        patch("superagents_sdlc.cli._run_brainstorm", fake_run_brainstorm),
    ):
        await _guided_new_brainstorm({"model": "m", "fast_model": None, "max_tokens": "16384"})

    assert len(captured_args) == 1
    assert captured_args[0].codebase_context is None
