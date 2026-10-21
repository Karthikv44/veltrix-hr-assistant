"""LLM Gateway enforcing context budget, logging, caching, and timeouts (Decorator pattern)."""

import asyncio
import time
from typing import Any

from veltrix.api.errors import CorpusTokenBudgetExceededError, LLMError
from veltrix.core.logging import get_logger
from veltrix.core.tokens import count_tokens
from veltrix.llm.base import LLMClient, LLMRequest, LLMResponse
from veltrix.llm.cache import LLMCache

logger = get_logger("gateway")


class LLMGateway:
    """Gateway wrapping LLM providers with corpus token limits, logging, caching, and timeouts.

    Enforces Non-Negotiable #4:
    No LLM call may contain more than 3,000 tokens of corpus text (tiktoken cl100k_base).
    """

    def __init__(
        self,
        client: LLMClient,
        max_corpus_tokens: int = 3000,
        timeout_seconds: float = 25.0,
        cache_enabled: bool = True,
    ) -> None:
        self.client = client
        self.max_corpus_tokens = max_corpus_tokens
        self.timeout_seconds = timeout_seconds
        self.cache = LLMCache(enabled=cache_enabled)

    async def complete(self, request: LLMRequest) -> LLMResponse:
        """Process an LLM request through safety guards, caching, and monitoring.

        Args:
            request: The LLMRequest containing prompt messages and corpus text.

        Returns:
            LLMResponse from the cache or provider.

        Raises:
            CorpusTokenBudgetExceededError: If corpus_tokens exceeds 3,000.
            LLMError: If execution times out or provider fails.
        """
        # 1. Enforce corpus token budget
        corpus_tokens = count_tokens(request.corpus_text)
        if corpus_tokens > self.max_corpus_tokens:
            logger.error(
                "corpus_token_budget_exceeded",
                corpus_tokens=corpus_tokens,
                max_allowed=self.max_corpus_tokens,
            )
            raise CorpusTokenBudgetExceededError(
                f"Corpus token count ({corpus_tokens}) exceeds maximum limit ({self.max_corpus_tokens})."
            )

        # 2. Check cache
        cached_response = self.cache.get(request)
        if cached_response is not None:
            logger.info(
                "llm_cache_hit",
                corpus_tokens=corpus_tokens,
                cached=True,
            )
            return cached_response

        # 3. Execute with timeout
        start_time = time.perf_counter()
        try:
            response = await asyncio.wait_for(
                self.client.complete(request),
                timeout=self.timeout_seconds,
            )
        except TimeoutError as e:
            logger.error(
                "llm_call_timeout",
                timeout=self.timeout_seconds,
                corpus_tokens=corpus_tokens,
            )
            raise LLMError(f"LLM request timed out after {self.timeout_seconds}s") from e
        except Exception as e:
            logger.error(
                "llm_call_failed",
                error=str(e),
                corpus_tokens=corpus_tokens,
            )
            raise LLMError(f"LLM call failed: {e}") from e

        duration_ms = (time.perf_counter() - start_time) * 1000.0
        response.latency_ms = duration_ms
        response.corpus_tokens = corpus_tokens

        # 4. Mandatory log of corpus_tokens for every LLM call
        logger.info(
            "llm_call_completed",
            corpus_tokens=corpus_tokens,
            prompt_tokens=response.prompt_tokens,
            completion_tokens=response.completion_tokens,
            latency_ms=round(duration_ms, 2),
            cached=False,
        )

        # 5. Store in cache
        self.cache.set(request, response)
        return response


class FakeLLMClient:
    """Deterministic fake LLM client for tests."""

    def __init__(self, canned_response: str = "Test response", parsed_payload: Any = None) -> None:
        self.canned_response = canned_response
        self.parsed_payload = parsed_payload
        self.call_history: list[LLMRequest] = []

    async def complete(self, request: LLMRequest) -> LLMResponse:
        self.call_history.append(request)
        corpus_tokens = count_tokens(request.corpus_text)
        return LLMResponse(
            content=self.canned_response,
            parsed=self.parsed_payload,
            corpus_tokens=corpus_tokens,
            prompt_tokens=10,
            completion_tokens=5,
            latency_ms=1.0,
        )
