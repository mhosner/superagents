"""Tests for the standalone CLI and AnthropicLLMClient."""

from __future__ import annotations

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
    args = parser.parse_args([
        "idea-to-code", "Add dark mode",
        "--output-dir", "/tmp/out",
    ])

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
    args = parser.parse_args([
        "spec-from-prd", "/path/prd.md",
        "--user-stories", "/path/stories.md",
        "--output-dir", "/tmp/out",
        "--autonomy-level", "2",
    ])

    assert args.command == "spec-from-prd"
    assert args.prd_path == "/path/prd.md"
    assert args.user_stories == "/path/stories.md"
    assert args.autonomy_level == 2


def test_parse_plan_from_spec():
    parser = _build_parser()
    args = parser.parse_args([
        "plan-from-spec",
        "--plan", "/path/plan.md",
        "--spec", "/path/spec.md",
        "--output-dir", "/tmp/out",
        "--stub",
    ])

    assert args.command == "plan-from-spec"
    assert args.plan == "/path/plan.md"
    assert args.spec == "/path/spec.md"
    assert args.user_stories is None
    assert args.stub is True


import subprocess
import sys
from pathlib import Path


def test_stub_end_to_end(tmp_path):
    output_dir = tmp_path / "output"

    result = subprocess.run(
        [
            sys.executable, "-m", "superagents_sdlc.cli",
            "idea-to-code", "Add dark mode",
            "--output-dir", str(output_dir),
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
