"""LLM abstraction — protocol and test double."""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class LLMClient(Protocol):
    """Minimal protocol for LLM interaction.

    Skills compose their own prompts and parse their own responses.
    The LLM client is a dumb pipe.
    """

    async def generate(self, prompt: str, *, system: str = "") -> str:
        """Generate a response from the LLM.

        Args:
            prompt: User prompt.
            system: Optional system prompt.

        Returns:
            Raw response string.
        """
        ...


class StubLLMClient:
    """Test double that returns canned responses based on prompt substring matching.

    Also tracks all calls for assertion in tests.

    Attributes:
        calls: List of (prompt, system) tuples from all generate() calls.
    """

    def __init__(self, *, responses: dict[str, str], strict: bool = False) -> None:
        """Initialize with a mapping of prompt substrings to responses.

        Args:
            responses: Map of substring → response. When generate() is called,
                returns the value for the first key found as a substring of
                the prompt. Returns empty string if no match.
            strict: If True, raise ValueError when no key matches the prompt.
                If False (default), return empty string on no match.
        """
        self._responses = responses
        self._strict = strict
        self.calls: list[tuple[str, str]] = []

    async def generate(self, prompt: str, *, system: str = "") -> str:
        """Return a canned response matching a prompt substring.

        Args:
            prompt: User prompt to match against.
            system: System prompt (tracked but not matched).

        Returns:
            Matched response, empty string (non-strict), or raises ValueError (strict).
        """
        self.calls.append((prompt, system))
        for key, response in self._responses.items():
            if key in prompt:
                return response
        if self._strict:
            msg = f"No response matched prompt: {prompt[:100]}"
            raise ValueError(msg)
        return ""
