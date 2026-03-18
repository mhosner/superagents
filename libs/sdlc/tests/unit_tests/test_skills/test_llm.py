"""Tests for LLMClient protocol and StubLLMClient."""

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
