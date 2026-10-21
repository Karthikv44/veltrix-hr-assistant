"""Base protocols and data classes for LLM clients and requests."""

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class LLMMessage:
    """Single message in a conversational LLM interaction."""

    role: str  # 'system', 'user', 'assistant'
    content: str


@dataclass
class LLMRequest:
    """Request payload passed to LLMClient through the gateway."""

    messages: list[LLMMessage]
    corpus_text: str = ""  # Corpus passages strictly subject to the 3,000 token limit
    temperature: float = 0.0
    max_tokens: int = 2048
    response_schema: type | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class LLMResponse:
    """Response returned from LLMClient through the gateway."""

    content: str
    parsed: Any | None = None
    corpus_tokens: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: float = 0.0
    cached: bool = False


class LLMClient(Protocol):
    """Protocol for LLM provider adapters."""

    async def complete(self, request: LLMRequest) -> LLMResponse:
        """Execute completion against the LLM provider."""
        ...
