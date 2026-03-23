"""Tests for extract_json LLM response parser."""

import pytest

from superagents_sdlc.skills.json_utils import extract_json


def test_extract_json_plain():
    """Parse plain JSON."""
    assert extract_json('{"a": 1}') == {"a": 1}


def test_extract_json_markdown_fences():
    """Strip ```json fences."""
    raw = '```json\n{"a": 1}\n```'
    assert extract_json(raw) == {"a": 1}


def test_extract_json_prose_before():
    """Find JSON after prose text."""
    raw = 'Here is the result:\n{"a": 1}'
    assert extract_json(raw) == {"a": 1}


def test_extract_json_prose_after():
    """Ignore trailing prose."""
    raw = '{"a": 1}\nHope that helps!'
    assert extract_json(raw) == {"a": 1}


def test_extract_json_trailing_comma_object():
    """Repair trailing comma before closing brace."""
    raw = '{"a": 1, "b": 2,}'
    assert extract_json(raw) == {"a": 1, "b": 2}


def test_extract_json_trailing_comma_array():
    """Repair trailing comma before closing bracket."""
    raw = '{"items": [1, 2, 3,]}'
    assert extract_json(raw) == {"items": [1, 2, 3]}


def test_extract_json_trailing_comma_nested():
    """Repair trailing commas in nested structures."""
    raw = '{"routing": {"pm": [], "arch": [{"id": "RF-1",}],}}'
    assert extract_json(raw) == {"routing": {"pm": [], "arch": [{"id": "RF-1"}]}}


def test_extract_json_fences_with_trailing_comma():
    """Combined: fences wrapping JSON with trailing comma."""
    raw = '```json\n{"a": 1,}\n```'
    assert extract_json(raw) == {"a": 1}


def test_extract_json_array():
    """Parse top-level array."""
    assert extract_json("[1, 2, 3]") == [1, 2, 3]


def test_extract_json_no_json_raises():
    """Raise ValueError when no JSON found."""
    with pytest.raises(ValueError, match="No valid JSON"):
        extract_json("This is just plain text with no JSON.")
