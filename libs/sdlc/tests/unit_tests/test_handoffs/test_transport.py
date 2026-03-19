"""Tests for Transport protocol and InProcessTransport."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from superagents_sdlc.handoffs.contract import HandoffResult, PersonaHandoff
from superagents_sdlc.handoffs.registry import PersonaRegistry
from superagents_sdlc.handoffs.transport import InProcessTransport


def _make_handoff() -> PersonaHandoff:
    return PersonaHandoff(
        source_persona="pm",
        target_persona="architect",
        artifact_type="prd",
        artifact_path="/artifacts/prd.md",
        context_summary="test",
        autonomy_level=2,
        requires_approval=False,
        trace_id="trace-1",
        parent_span_id="span-1",
    )


def _make_mock_persona(name: str) -> MagicMock:
    persona = MagicMock()
    persona.name = name
    persona.receive_handoff = AsyncMock()
    return persona


async def test_in_process_sends_to_target():
    persona = _make_mock_persona("architect")
    registry = PersonaRegistry()
    registry.register(persona)
    transport = InProcessTransport(registry=registry)

    await transport.send(_make_handoff())

    persona.receive_handoff.assert_called_once()


async def test_in_process_serializes_round_trip():
    persona = _make_mock_persona("architect")
    registry = PersonaRegistry()
    registry.register(persona)
    transport = InProcessTransport(registry=registry)

    original = _make_handoff()
    await transport.send(original)

    received = persona.receive_handoff.call_args[0][0]
    # Must be equal in value but not the same object (deserialized from JSON)
    assert received == original
    assert received is not original


async def test_in_process_unknown_target_raises():
    registry = PersonaRegistry()
    transport = InProcessTransport(registry=registry)

    with pytest.raises(KeyError):
        await transport.send(_make_handoff())


async def test_transport_returns_handoff_result():
    persona = _make_mock_persona("architect")
    registry = PersonaRegistry()
    registry.register(persona)
    transport = InProcessTransport(registry=registry)

    result = await transport.send(_make_handoff())
    assert isinstance(result, HandoffResult)
    assert result.status == "accepted"
    assert result.target_persona == "architect"
    assert result.trace_id == "trace-1"


def test_transport_can_reach_registered():
    persona = _make_mock_persona("architect")
    registry = PersonaRegistry()
    registry.register(persona)
    transport = InProcessTransport(registry=registry)

    assert transport.can_reach("architect") is True


def test_transport_can_reach_unknown():
    registry = PersonaRegistry()
    transport = InProcessTransport(registry=registry)

    assert transport.can_reach("nonexistent") is False
