"""Tests for the standalone CLI and AnthropicLLMClient."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from superagents_sdlc.cli import _build_parser, _load_context
from superagents_sdlc.skills.llm import LLMClient


def test_anthropic_client_satisfies_protocol():
    mock_anthropic = MagicMock()
    with patch.dict("sys.modules", {"anthropic": mock_anthropic}):
        from superagents_sdlc.skills.llm import AnthropicLLMClient  # noqa: PLC0415

        client = AnthropicLLMClient(model="claude-sonnet-4-6")
        assert isinstance(client, LLMClient)


def test_load_context_reads_all_files(tmp_path):
    (tmp_path / "product_context.md").write_text("Product info")
    (tmp_path / "goals_context.md").write_text("Goals info")
    (tmp_path / "personas_context.md").write_text("Personas info")

    result = _load_context(str(tmp_path))

    assert result == {
        "product_context": "Product info",
        "goals_context": "Goals info",
        "personas_context": "Personas info",
    }


def test_load_context_skips_missing_files(tmp_path):
    (tmp_path / "product_context.md").write_text("Product only")

    result = _load_context(str(tmp_path))

    assert result == {"product_context": "Product only"}


def test_load_context_none_returns_empty():
    result = _load_context(None)

    assert result == {}


def test_load_context_invalid_dir_raises():
    with pytest.raises(FileNotFoundError):
        _load_context("/nonexistent/path/that/does/not/exist")


def test_parse_idea_to_code():
    parser = _build_parser()
    args = parser.parse_args(
        [
            "idea-to-code",
            "Add dark mode",
            "--output-dir",
            "/tmp/out",
        ]
    )

    assert args.command == "idea-to-code"
    assert args.idea == "Add dark mode"
    assert args.output_dir == "/tmp/out"
    assert args.autonomy_level == 3
    assert args.model == "claude-sonnet-4-6"
    assert args.stub is False
    assert args.json is False
    assert args.context_dir is None


def test_parse_spec_from_prd():
    parser = _build_parser()
    args = parser.parse_args(
        [
            "spec-from-prd",
            "/path/prd.md",
            "--user-stories",
            "/path/stories.md",
            "--output-dir",
            "/tmp/out",
            "--autonomy-level",
            "2",
        ]
    )

    assert args.command == "spec-from-prd"
    assert args.prd_path == "/path/prd.md"
    assert args.user_stories == "/path/stories.md"
    assert args.autonomy_level == 2


def test_parse_plan_from_spec():
    parser = _build_parser()
    args = parser.parse_args(
        [
            "plan-from-spec",
            "--plan",
            "/path/plan.md",
            "--spec",
            "/path/spec.md",
            "--output-dir",
            "/tmp/out",
            "--stub",
        ]
    )

    assert args.command == "plan-from-spec"
    assert args.plan == "/path/plan.md"
    assert args.spec == "/path/spec.md"
    assert args.user_stories is None
    assert args.stub is True


def test_stub_end_to_end(tmp_path):
    output_dir = tmp_path / "output"

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "superagents_sdlc.cli",
            "idea-to-code",
            "Add dark mode",
            "--output-dir",
            str(output_dir),
            "--stub",
        ],
        capture_output=True,
        text=True,
        cwd=str(Path(__file__).resolve().parents[2]),
        timeout=30,
    )

    assert result.returncode == 0, f"stderr: {result.stderr}"
    assert "Certification:" in result.stdout
    assert (output_dir / "pm").is_dir()
    assert (output_dir / "qa").is_dir()


def test_json_output(tmp_path):
    output_dir = tmp_path / "output"

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "superagents_sdlc.cli",
            "idea-to-code",
            "Add dark mode",
            "--output-dir",
            str(output_dir),
            "--stub",
            "--json",
            "--quiet",
        ],
        capture_output=True,
        text=True,
        cwd=str(Path(__file__).resolve().parents[2]),
        timeout=30,
    )

    assert result.returncode == 0, f"stderr: {result.stderr}"
    data = json.loads(result.stdout)
    assert "certification" in data
    assert "artifacts" in data
    assert "pm" in data
    assert "architect" in data
    assert "developer" in data
    assert "qa" in data
    assert len(data["artifacts"]) == 9  # includes routing_manifest


def test_error_exit_code(tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "superagents_sdlc.cli",
            "idea-to-code",
            "Test error",
            "--output-dir",
            str(tmp_path / "output"),
            "--context-dir",
            "/nonexistent/path/that/does/not/exist",
            "--stub",
        ],
        capture_output=True,
        text=True,
        cwd=str(Path(__file__).resolve().parents[2]),
        timeout=30,
    )

    assert result.returncode == 1
    assert "Error" in result.stderr


def test_parse_interactive_flag():
    parser = _build_parser()
    args = parser.parse_args(
        [
            "idea-to-code",
            "Test",
            "--output-dir",
            "/tmp/out",
            "-i",
        ]
    )
    assert args.interactive is True


def test_interactive_quiet_mutually_exclusive():
    parser = _build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(
            [
                "idea-to-code",
                "Test",
                "--output-dir",
                "/tmp/out",
                "-i",
                "--quiet",
            ]
        )


def test_interactive_approve(tmp_path):
    output_dir = tmp_path / "output"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "superagents_sdlc.cli",
            "idea-to-code",
            "Add dark mode",
            "--output-dir",
            str(output_dir),
            "--stub",
            "-i",
        ],
        input="a\n",
        capture_output=True,
        text=True,
        cwd=str(Path(__file__).resolve().parents[2]),
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"
    assert "Approved" in result.stdout
    assert (output_dir / "pipeline_narrative.md").exists()


def test_interactive_revise_then_approve(tmp_path):
    output_dir = tmp_path / "output"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "superagents_sdlc.cli",
            "idea-to-code",
            "Add dark mode",
            "--output-dir",
            str(output_dir),
            "--stub",
            "-i",
        ],
        input="r\nFix the caching layer\n\na\n",
        capture_output=True,
        text=True,
        cwd=str(Path(__file__).resolve().parents[2]),
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"
    narrative = (output_dir / "pipeline_narrative.md").read_text()
    assert "Human Feedback" in narrative
    assert "Fix the caching layer" in narrative


def test_brief_flag_parsed():
    parser = _build_parser()
    args = parser.parse_args([
        "idea-to-code", "Add dark mode",
        "--output-dir", "/tmp/out",
        "--brief", "/path/brief.md",
    ])
    assert args.brief == "/path/brief.md"


def test_codebase_context_flag_on_idea_to_code():
    parser = _build_parser()
    args = parser.parse_args([
        "idea-to-code", "Add dark mode",
        "--output-dir", "/tmp/out",
        "--codebase-context", "/path/context.md",
    ])
    assert args.codebase_context == "/path/context.md"


def test_parse_max_tokens_flag():
    parser = _build_parser()
    args = parser.parse_args([
        "idea-to-code", "Add dark mode",
        "--output-dir", "/tmp/out",
        "--max-tokens", "8192",
    ])
    assert args.max_tokens == 8192


def test_parse_max_tokens_default():
    parser = _build_parser()
    args = parser.parse_args([
        "idea-to-code", "Add dark mode",
        "--output-dir", "/tmp/out",
    ])
    assert args.max_tokens == 16384


def test_streaming_shows_skill_entries(tmp_path):
    """Non-quiet run streams skill-level entries to stdout."""
    output_dir = tmp_path / "output"

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "superagents_sdlc.cli",
            "idea-to-code",
            "Add dark mode",
            "--output-dir",
            str(output_dir),
            "--stub",
        ],
        capture_output=True,
        text=True,
        cwd=str(Path(__file__).resolve().parents[2]),
        timeout=30,
    )

    assert result.returncode == 0, f"stderr: {result.stderr}"
    # Should contain skill-level streaming entries
    assert "prd_generator" in result.stdout
    assert "product_manager" in result.stdout or "→" in result.stdout


def test_streaming_shows_certification(tmp_path):
    """Non-quiet run streams certification to stdout."""
    output_dir = tmp_path / "output"

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "superagents_sdlc.cli",
            "idea-to-code",
            "Add dark mode",
            "--output-dir",
            str(output_dir),
            "--stub",
        ],
        capture_output=True,
        text=True,
        cwd=str(Path(__file__).resolve().parents[2]),
        timeout=30,
    )

    assert result.returncode == 0, f"stderr: {result.stderr}"
    # Should see certification from QA callback streaming (indented)
    assert "Certification: NEEDS WORK" in result.stdout


def test_quiet_suppresses_streaming(tmp_path):
    """--quiet suppresses all narrative streaming to stdout."""
    output_dir = tmp_path / "output"

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "superagents_sdlc.cli",
            "idea-to-code",
            "Add dark mode",
            "--output-dir",
            str(output_dir),
            "--stub",
            "--quiet",
        ],
        capture_output=True,
        text=True,
        cwd=str(Path(__file__).resolve().parents[2]),
        timeout=30,
    )

    assert result.returncode == 0, f"stderr: {result.stderr}"
    # Quiet mode: no skill entries, no phase lines
    assert "prd_generator" not in result.stdout
    assert "phase" not in result.stdout.lower()


def test_no_phase_level_progress_lines(tmp_path):
    """Old 'PM phase... done' lines are replaced by skill-level detail."""
    output_dir = tmp_path / "output"

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "superagents_sdlc.cli",
            "idea-to-code",
            "Add dark mode",
            "--output-dir",
            str(output_dir),
            "--stub",
        ],
        capture_output=True,
        text=True,
        cwd=str(Path(__file__).resolve().parents[2]),
        timeout=30,
    )

    assert result.returncode == 0, f"stderr: {result.stderr}"
    assert "phase... done" not in result.stdout


def test_fast_model_flag_parsed():
    parser = _build_parser()
    args = parser.parse_args([
        "idea-to-code", "Add dark mode",
        "--output-dir", "/tmp/out",
        "--fast-model", "claude-haiku-4-5",
    ])
    assert args.fast_model == "claude-haiku-4-5"


def test_fast_model_default_none():
    parser = _build_parser()
    args = parser.parse_args([
        "idea-to-code", "Add dark mode",
        "--output-dir", "/tmp/out",
    ])
    assert args.fast_model is None


def test_banner_shows_on_non_quiet_run(tmp_path):
    """Non-quiet run shows the ASCII banner with version."""
    output_dir = tmp_path / "output"

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "superagents_sdlc.cli",
            "idea-to-code",
            "Add dark mode",
            "--output-dir",
            str(output_dir),
            "--stub",
        ],
        capture_output=True,
        text=True,
        cwd=str(Path(__file__).resolve().parents[2]),
        timeout=30,
    )

    assert result.returncode == 0, f"stderr: {result.stderr}"
    assert "Not all coding heroes wear capes" in result.stdout
    assert "____" in result.stdout  # part of ASCII art


def test_banner_suppressed_when_quiet(tmp_path):
    """--quiet suppresses the banner."""
    output_dir = tmp_path / "output"

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "superagents_sdlc.cli",
            "idea-to-code",
            "Add dark mode",
            "--output-dir",
            str(output_dir),
            "--stub",
            "--quiet",
        ],
        capture_output=True,
        text=True,
        cwd=str(Path(__file__).resolve().parents[2]),
        timeout=30,
    )

    assert result.returncode == 0, f"stderr: {result.stderr}"
    assert "Not all coding heroes wear capes" not in result.stdout


def test_narrative_includes_skill_entries(tmp_path):
    """Stub pipeline narrative includes skill-level entries from on_skill_complete."""
    output_dir = tmp_path / "output"

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "superagents_sdlc.cli",
            "idea-to-code",
            "Add dark mode",
            "--output-dir",
            str(output_dir),
            "--stub",
            "--quiet",
        ],
        capture_output=True,
        text=True,
        cwd=str(Path(__file__).resolve().parents[2]),
        timeout=30,
    )

    assert result.returncode == 0, f"stderr: {result.stderr}"
    narrative = (output_dir / "pipeline_narrative.md").read_text()
    # Should contain skill-level entries like "**product_manager → prd_generator**"
    assert "→" in narrative
    assert "product_manager" in narrative or "PM" in narrative
    # Should contain QA findings detail
    assert "Certification:" in narrative or "Certification" in narrative


def test_interactive_quit(tmp_path):
    output_dir = tmp_path / "output"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "superagents_sdlc.cli",
            "idea-to-code",
            "Add dark mode",
            "--output-dir",
            str(output_dir),
            "--stub",
            "-i",
        ],
        input="q\n",
        capture_output=True,
        text=True,
        cwd=str(Path(__file__).resolve().parents[2]),
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"
    assert "Quit" in result.stdout or "Certification" in result.stdout
