"""Tests for PersonaRegistry."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest

from superagents_sdlc.handoffs.registry import PersonaRegistry

if TYPE_CHECKING:
    from superagents_sdlc.personas.base import BasePersona


def _make_persona(name: str) -> BasePersona:
    """Create a mock persona with the given name."""
    persona = MagicMock()
    persona.name = name
    return persona


def test_register_and_get():
    registry = PersonaRegistry()
    persona = _make_persona("architect")
    registry.register(persona)
    assert registry.get("architect") is persona
    assert registry.list_personas() == ["architect"]


def test_duplicate_register_raises():
    registry = PersonaRegistry()
    persona = _make_persona("pm")
    registry.register(persona)
    with pytest.raises(ValueError, match="pm"):
        registry.register(persona)


def test_get_unknown_raises():
    registry = PersonaRegistry()
    with pytest.raises(KeyError, match="unknown"):
        registry.get("unknown")
