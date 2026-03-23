"""Tests for LLMClient protocol and StubLLMClient."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from superagents_sdlc.skills.llm import LLMClient, StubLLMClient


async def test_stub_llm_returns_matched_response():
    stub = StubLLMClient(responses={"prd": "generated PRD"})
    result = await stub.generate("Please write a prd for feature X")
    assert result == "generated PRD"


async def test_stub_llm_returns_default_for_no_match():
    stub = StubLLMClient(responses={"prd": "generated PRD"})
    result = await stub.generate("unrelated prompt")
    assert result == ""


async def test_stub_llm_tracks_calls():
    stub = StubLLMClient(responses={})
    await stub.generate("hello", system="be helpful")
    assert stub.calls == [("hello", "be helpful")]


def test_llm_protocol_compliance():
    stub = StubLLMClient(responses={})
    assert isinstance(stub, LLMClient)


async def test_stub_llm_strict_raises_on_no_match():
    stub = StubLLMClient(responses={"prd": "generated PRD"}, strict=True)
    with pytest.raises(ValueError, match="No response matched prompt"):
        await stub.generate("unrelated prompt")


async def test_stub_llm_strict_still_matches_normally():
    stub = StubLLMClient(responses={"prd": "generated PRD"}, strict=True)
    result = await stub.generate("Please write a prd for feature X")
    assert result == "generated PRD"


def test_anthropic_client_default_max_tokens():
    """AnthropicLLMClient defaults to 16384 max_tokens."""
    mock_anthropic = MagicMock()
    with patch.dict("sys.modules", {"anthropic": mock_anthropic}):
        from superagents_sdlc.skills.llm import AnthropicLLMClient  # noqa: PLC0415

        client = AnthropicLLMClient(model="claude-sonnet-4-6")
        assert client._max_tokens == 16384


def test_anthropic_client_custom_max_tokens():
    """AnthropicLLMClient accepts a custom max_tokens value."""
    mock_anthropic = MagicMock()
    with patch.dict("sys.modules", {"anthropic": mock_anthropic}):
        from superagents_sdlc.skills.llm import AnthropicLLMClient  # noqa: PLC0415

        client = AnthropicLLMClient(model="claude-sonnet-4-6", max_tokens=8192)
        assert client._max_tokens == 8192


async def test_anthropic_client_uses_streaming_above_threshold():
    """AnthropicLLMClient uses streaming API when max_tokens > 16384."""
    mock_anthropic = MagicMock()

    # Build a mock stream context manager
    mock_message = MagicMock()
    mock_message.content = [MagicMock(text="streamed response")]
    mock_stream = MagicMock()
    mock_stream.__aenter__ = AsyncMock(return_value=mock_stream)
    mock_stream.__aexit__ = AsyncMock(return_value=False)
    mock_stream.get_final_message = AsyncMock(return_value=mock_message)

    with patch.dict("sys.modules", {"anthropic": mock_anthropic}):
        from superagents_sdlc.skills.llm import AnthropicLLMClient  # noqa: PLC0415

        client = AnthropicLLMClient(model="claude-sonnet-4-6", max_tokens=32768)
        client._client.messages.stream = MagicMock(return_value=mock_stream)
        client._client.messages.create = AsyncMock()

        result = await client.generate("test prompt", system="be helpful")

        assert result == "streamed response"
        client._client.messages.stream.assert_called_once()
        client._client.messages.create.assert_not_called()


async def test_anthropic_client_uses_create_below_threshold():
    """AnthropicLLMClient uses messages.create() when max_tokens <= 16384."""
    mock_anthropic = MagicMock()

    mock_response = MagicMock()
    mock_response.content = [MagicMock(text="direct response")]

    with patch.dict("sys.modules", {"anthropic": mock_anthropic}):
        from superagents_sdlc.skills.llm import AnthropicLLMClient  # noqa: PLC0415

        client = AnthropicLLMClient(model="claude-sonnet-4-6", max_tokens=16384)
        client._client.messages.create = AsyncMock(return_value=mock_response)

        result = await client.generate("test prompt")

        assert result == "direct response"
        client._client.messages.create.assert_called_once()


async def test_anthropic_client_retries_on_rate_limit():
    """AnthropicLLMClient retries with backoff on RateLimitError."""
    mock_anthropic = MagicMock()

    # Create a real-looking RateLimitError
    rate_limit_error = type("RateLimitError", (Exception,), {})()
    mock_anthropic.RateLimitError = type(rate_limit_error)

    mock_response = MagicMock()
    mock_response.content = [MagicMock(text="success after retry")]

    with patch.dict("sys.modules", {"anthropic": mock_anthropic}):
        from superagents_sdlc.skills.llm import AnthropicLLMClient  # noqa: PLC0415

        client = AnthropicLLMClient(model="claude-sonnet-4-6", max_tokens=8192)
        # First call raises rate limit, second succeeds
        client._client.messages.create = AsyncMock(
            side_effect=[rate_limit_error, mock_response]
        )

        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            result = await client.generate("test prompt")

        assert result == "success after retry"
        assert client._client.messages.create.call_count == 2
        mock_sleep.assert_called_once()


async def test_anthropic_client_raises_after_max_retries():
    """AnthropicLLMClient raises after exhausting retries on RateLimitError."""
    mock_anthropic = MagicMock()

    rate_limit_error = type("RateLimitError", (Exception,), {})()
    mock_anthropic.RateLimitError = type(rate_limit_error)

    with patch.dict("sys.modules", {"anthropic": mock_anthropic}):
        from superagents_sdlc.skills.llm import AnthropicLLMClient  # noqa: PLC0415

        client = AnthropicLLMClient(model="claude-sonnet-4-6", max_tokens=8192)
        # All calls raise rate limit
        client._client.messages.create = AsyncMock(
            side_effect=type(rate_limit_error)("rate limited")
        )

        with patch("asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(type(rate_limit_error)):
                await client.generate("test prompt")

        # Should have tried multiple times
        assert client._client.messages.create.call_count >= 3


async def test_stub_client_ignores_cached_prefix():
    """StubLLMClient works the same with or without cached_prefix."""
    stub = StubLLMClient(responses={"hello": "world"})
    result = await stub.generate("hello", cached_prefix="stable context")
    assert result == "world"
    assert stub.calls == [("hello", "")]


async def test_anthropic_client_cached_prefix_sends_cache_control():
    """AnthropicLLMClient sends cache_control breakpoint when cached_prefix is provided."""
    mock_anthropic = MagicMock()

    mock_response = MagicMock()
    mock_response.content = [MagicMock(text="cached response")]

    with patch.dict("sys.modules", {"anthropic": mock_anthropic}):
        from superagents_sdlc.skills.llm import AnthropicLLMClient  # noqa: PLC0415

        client = AnthropicLLMClient(model="claude-sonnet-4-6", max_tokens=8192)
        client._client.messages.create = AsyncMock(return_value=mock_response)

        result = await client.generate(
            "variable content", system="sys", cached_prefix="stable context"
        )

        assert result == "cached response"
        call_kwargs = client._client.messages.create.call_args[1]
        messages = call_kwargs["messages"]
        # First message has cache_control on the cached prefix
        assert messages[0]["role"] == "user"
        assert messages[0]["content"][0]["cache_control"] == {"type": "ephemeral"}
        assert messages[0]["content"][0]["text"] == "stable context"
        # Assistant turn bridges the cached and variable content
        assert messages[1]["role"] == "assistant"
        # Variable content in the third message
        assert messages[2]["role"] == "user"
        assert messages[2]["content"] == "variable content"


async def test_anthropic_client_no_cached_prefix_sends_simple_message():
    """Without cached_prefix, AnthropicLLMClient sends a single user message."""
    mock_anthropic = MagicMock()

    mock_response = MagicMock()
    mock_response.content = [MagicMock(text="simple response")]

    with patch.dict("sys.modules", {"anthropic": mock_anthropic}):
        from superagents_sdlc.skills.llm import AnthropicLLMClient  # noqa: PLC0415

        client = AnthropicLLMClient(model="claude-sonnet-4-6", max_tokens=8192)
        client._client.messages.create = AsyncMock(return_value=mock_response)

        result = await client.generate("just a prompt")

        assert result == "simple response"
        call_kwargs = client._client.messages.create.call_args[1]
        messages = call_kwargs["messages"]
        assert len(messages) == 1
        assert messages[0] == {"role": "user", "content": "just a prompt"}
