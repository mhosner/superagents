"""Transport protocol and in-process implementation."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from superagents_sdlc.handoffs.contract import HandoffResult, PersonaHandoff

if TYPE_CHECKING:
    from superagents_sdlc.handoffs.registry import PersonaRegistry


class Transport(Protocol):
    """Protocol for handoff transport implementations.

    Registry is NOT a protocol-level parameter. A future A2ATransport uses
    HTTP to reach targets and doesn't need a registry. Each transport
    implementation gets routing dependencies at construction time.
    """

    async def send(self, handoff: PersonaHandoff) -> HandoffResult:
        """Send a handoff to its target persona.

        Args:
            handoff: The handoff to deliver.

        Returns:
            Result indicating acceptance, rejection, or pending status.
        """
        ...


class InProcessTransport:
    """Transport that delivers handoffs in-process via the persona registry.

    Serializes the handoff to JSON and deserializes before delivery to
    simulate wire format, catching serialization bugs early.
    """

    def __init__(self, *, registry: PersonaRegistry) -> None:
        """Initialize with a persona registry.

        Args:
            registry: Registry for looking up target personas.
        """
        self._registry = registry

    async def send(self, handoff: PersonaHandoff) -> HandoffResult:
        """Serialize, deserialize, and deliver the handoff to the target.

        Args:
            handoff: The handoff to deliver.

        Returns:
            Accepted result on success.

        Raises:
            KeyError: If the target persona is not registered.
        """
        # Simulate wire format: serialize then deserialize
        json_bytes = handoff.model_dump_json()
        deserialized = PersonaHandoff.model_validate_json(json_bytes)

        target = self._registry.get(deserialized.target_persona)
        await target.receive_handoff(deserialized)

        return HandoffResult(
            status="accepted",
            target_persona=deserialized.target_persona,
            trace_id=deserialized.trace_id,
        )
