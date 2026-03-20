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


class AnthropicLLMClient:
    """LLMClient implementation using Anthropic's API.

    Requires the ``anthropic`` package (``pip install superagents-sdlc[anthropic]``).
    Uses ``AsyncAnthropic`` for async-native HTTP calls.

    Attributes:
        model: Anthropic model identifier.
    """

    def __init__(self, *, model: str = "claude-sonnet-4-6", api_key: str | None = None) -> None:
        """Initialize with model and optional API key.

        Args:
            model: Anthropic model to use.
            api_key: API key. Falls back to ``ANTHROPIC_API_KEY`` env var if omitted.

        Raises:
            ImportError: If the ``anthropic`` package is not installed.
        """
        try:
            import anthropic  # noqa: PLC0415
        except ImportError:
            msg = (
                "anthropic package not installed. "
                "Run: pip install superagents-sdlc[anthropic]"
            )
            raise ImportError(msg) from None

        self.model = model
        self._client = anthropic.AsyncAnthropic(api_key=api_key)

    async def generate(self, prompt: str, *, system: str = "") -> str:
        """Generate a response via the Anthropic API.

        Args:
            prompt: User prompt.
            system: Optional system prompt.

        Returns:
            Raw response text.
        """
        kwargs: dict[str, object] = {
            "model": self.model,
            "max_tokens": 4096,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system:
            kwargs["system"] = system
        response = await self._client.messages.create(**kwargs)
        return response.content[0].text
