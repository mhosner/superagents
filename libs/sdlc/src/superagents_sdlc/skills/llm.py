"""LLM abstraction — protocol and test double."""

from __future__ import annotations

import asyncio
import logging
from typing import Protocol, runtime_checkable

logger = logging.getLogger(__name__)

_MAX_RETRIES = 5
_BASE_DELAY = 2.0


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

    def __init__(
        self,
        *,
        model: str = "claude-sonnet-4-6",
        api_key: str | None = None,
        max_tokens: int = 16384,
    ) -> None:
        """Initialize with model and optional API key.

        Args:
            model: Anthropic model to use.
            api_key: API key. Falls back to ``ANTHROPIC_API_KEY`` env var if omitted.
            max_tokens: Maximum tokens for API responses (default 16384).

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
        self._max_tokens = max_tokens
        self._client = anthropic.AsyncAnthropic(api_key=api_key)
        self._rate_limit_error = anthropic.RateLimitError

    async def generate(self, prompt: str, *, system: str = "") -> str:
        """Generate a response via the Anthropic API.

        Retries up to ``_MAX_RETRIES`` times on rate-limit errors with
        exponential backoff.

        Args:
            prompt: User prompt.
            system: Optional system prompt.

        Returns:
            Raw response text.

        Raises:
            anthropic.RateLimitError: If retries are exhausted.
        """
        kwargs: dict[str, object] = {
            "model": self.model,
            "max_tokens": self._max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system:
            kwargs["system"] = system

        for attempt in range(_MAX_RETRIES):
            try:
                if self._max_tokens > 16384:  # noqa: PLR2004
                    async with self._client.messages.stream(**kwargs) as stream:
                        response = await stream.get_final_message()
                else:
                    response = await self._client.messages.create(**kwargs)
                return response.content[0].text
            except self._rate_limit_error:
                if attempt == _MAX_RETRIES - 1:
                    raise
                delay = _BASE_DELAY * (2 ** attempt)
                logger.warning(
                    "Rate limited (attempt %d/%d), retrying in %.1fs",
                    attempt + 1, _MAX_RETRIES, delay,
                )
                await asyncio.sleep(delay)
        msg = "unreachable"
        raise RuntimeError(msg)
