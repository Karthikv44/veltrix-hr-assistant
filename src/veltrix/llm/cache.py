"""In-memory cache for deterministic LLM response retrieval."""

import hashlib
import json
from typing import Any

from veltrix.llm.base import LLMRequest, LLMResponse


class LLMCache:
    """Thread-safe in-memory cache keyed by a SHA-256 digest of request inputs."""

    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled
        self._cache: dict[str, LLMResponse] = {}

    def _make_key(self, request: LLMRequest) -> str:
        data: dict[str, Any] = {
            "messages": [{"role": m.role, "content": m.content} for m in request.messages],
            "corpus_text": request.corpus_text,
            "temperature": request.temperature,
            "schema": str(request.response_schema),
        }
        serialized = json.dumps(data, sort_keys=True)
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    def get(self, request: LLMRequest) -> LLMResponse | None:
        if not self.enabled:
            return None
        key = self._make_key(request)
        cached = self._cache.get(key)
        if cached:
            # Return a copy marked as cached
            return LLMResponse(
                content=cached.content,
                parsed=cached.parsed,
                corpus_tokens=cached.corpus_tokens,
                prompt_tokens=cached.prompt_tokens,
                completion_tokens=cached.completion_tokens,
                latency_ms=0.0,
                cached=True,
            )
        return None

    def set(self, request: LLMRequest, response: LLMResponse) -> None:
        if not self.enabled:
            return
        key = self._make_key(request)
        self._cache[key] = response

    def clear(self) -> None:
        self._cache.clear()
