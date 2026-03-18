"""Persona registry — lookup personas by name."""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class _HasName(Protocol):
    """Structural type for objects with a name attribute."""

    name: str


class PersonaRegistry:
    """Registry for looking up personas by name.

    Stores references to persona instances and provides lookup by name.
    """

    def __init__(self) -> None:
        """Initialize an empty registry."""
        self._personas: dict[str, _HasName] = {}

    def register(self, persona: _HasName) -> None:
        """Register a persona.

        Args:
            persona: Persona instance with a `name` attribute.

        Raises:
            ValueError: If a persona with the same name is already registered.
        """
        if persona.name in self._personas:
            msg = f"Persona already registered: {persona.name}"
            raise ValueError(msg)
        self._personas[persona.name] = persona

    def get(self, name: str) -> _HasName:
        """Look up a persona by name.

        Args:
            name: Persona identifier.

        Returns:
            The registered persona.

        Raises:
            KeyError: If no persona with that name is registered.
        """
        if name not in self._personas:
            msg = f"No persona registered with name: {name}"
            raise KeyError(msg)
        return self._personas[name]

    def list_personas(self) -> list[str]:
        """Return names of all registered personas.

        Returns:
            Sorted list of persona names.
        """
        return sorted(self._personas.keys())
