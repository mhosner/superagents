"""Tests for the standalone CLI and AnthropicLLMClient."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from superagents_sdlc.cli import _load_context
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
