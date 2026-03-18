"""Handoffs subpackage — A2A-shaped handoff contracts and transport."""

from superagents_sdlc.handoffs.contract import HandoffResult, PersonaHandoff
from superagents_sdlc.handoffs.registry import PersonaRegistry
from superagents_sdlc.handoffs.transport import InProcessTransport, Transport

__all__ = [
    "HandoffResult",
    "InProcessTransport",
    "PersonaHandoff",
    "PersonaRegistry",
    "Transport",
]
