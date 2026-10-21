"""Unit tests for LLM Gateway corpus-token budgeting and caching."""

import pytest

from veltrix.api.errors import CorpusTokenBudgetExceededError
from veltrix.llm.base import LLMMessage, LLMRequest
from veltrix.llm.gateway import FakeLLMClient, LLMGateway


@pytest.mark.asyncio
async def test_gateway_allows_under_budget() -> None:
    fake_client = FakeLLMClient(canned_response="Answer from evidence.")
    gateway = LLMGateway(client=fake_client, max_corpus_tokens=3000)

    request = LLMRequest(
        messages=[LLMMessage(role="user", content="What is the policy?")],
        corpus_text="Short corpus text well within budget.",
    )

    response = await gateway.complete(request)
    assert response.content == "Answer from evidence."
    assert response.corpus_tokens > 0
    assert response.corpus_tokens <= 3000
    assert len(fake_client.call_history) == 1


@pytest.mark.asyncio
async def test_gateway_rejects_over_budget() -> None:
    fake_client = FakeLLMClient()
    gateway = LLMGateway(client=fake_client, max_corpus_tokens=100)

    # Generate a string with more than 100 tokens
    large_corpus = (
        "This is a sentence containing multiple words that will exceed the test token budget. " * 30
    )
    request = LLMRequest(
        messages=[LLMMessage(role="user", content="Summarize")],
        corpus_text=large_corpus,
    )

    with pytest.raises(CorpusTokenBudgetExceededError) as exc_info:
        await gateway.complete(request)

    assert "exceeds maximum limit" in str(exc_info.value)
    # Ensure client was NEVER called (fail-fast guard)
    assert len(fake_client.call_history) == 0


@pytest.mark.asyncio
async def test_gateway_caching() -> None:
    fake_client = FakeLLMClient(canned_response="Cached response")
    gateway = LLMGateway(client=fake_client, max_corpus_tokens=3000, cache_enabled=True)

    request = LLMRequest(
        messages=[LLMMessage(role="user", content="Question 1")],
        corpus_text="Corpus snippet 1",
    )

    # First call - cache miss
    resp1 = await gateway.complete(request)
    assert resp1.cached is False
    assert len(fake_client.call_history) == 1

    # Second call - cache hit
    resp2 = await gateway.complete(request)
    assert resp2.cached is True
    assert resp2.content == "Cached response"
    # Client should not have been called again
    assert len(fake_client.call_history) == 1
