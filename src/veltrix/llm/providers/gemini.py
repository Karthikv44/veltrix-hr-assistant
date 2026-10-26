"""Gemini LLM client implementation using Google GenAI SDK."""

import asyncio
from typing import Any

import google.genai as genai

from veltrix.api.errors import LLMError
from veltrix.core.logging import get_logger
from veltrix.llm.base import LLMRequest, LLMResponse

logger = get_logger("gemini_client")


def _strip_additional_properties(schema: Any) -> Any:
    """Recursively strip 'additionalProperties' from JSON schema dictionaries.

    The Google Gemini Developer API rejects schemas containing 'additionalProperties',
    which Pydantic generates by default for generic Dict types.
    """
    if isinstance(schema, dict):
        return {
            k: _strip_additional_properties(v)
            for k, v in schema.items()
            if k != "additionalProperties"
        }
    if isinstance(schema, list):
        return [_strip_additional_properties(item) for item in schema]
    return schema


class GeminiClient:
    """LLM client adapter for Google Gemini models using official google-genai SDK."""

    def __init__(self, api_key: str, model: str = "gemini-3.8-flash") -> None:
        self.api_key = api_key
        self.model = model
        self._client: genai.Client | None = None

    def _get_client(self) -> genai.Client:
        if self._client is None:
            # If no API key provided, GenAI SDK checks GEMINI_API_KEY env var
            self._client = genai.Client(api_key=self.api_key) if self.api_key else genai.Client()
        return self._client

    async def complete(self, request: LLMRequest) -> LLMResponse:
        """Call Gemini model asynchronously with exponential backoff on transient errors."""
        max_attempts = 3
        backoff_sec = 2.0

        for attempt in range(1, max_attempts + 1):
            try:
                client = self._get_client()

                # Format prompt from messages
                contents: list[str] = []
                system_instruction = None

                for m in request.messages:
                    if m.role == "system":
                        system_instruction = m.content
                    else:
                        contents.append(f"{m.role.upper()}: {m.content}")

                prompt_text = "\n\n".join(contents)

                config: dict[str, Any] = {
                    "temperature": request.temperature,
                }
                if system_instruction:
                    config["system_instruction"] = system_instruction
                if request.response_schema:
                    config["response_mime_type"] = "application/json"
                    if hasattr(request.response_schema, "model_json_schema"):
                        raw_schema = request.response_schema.model_json_schema()
                        config["response_schema"] = _strip_additional_properties(raw_schema)
                    elif isinstance(request.response_schema, dict):
                        config["response_schema"] = _strip_additional_properties(
                            request.response_schema
                        )
                    else:
                        config["response_schema"] = request.response_schema

                # Execute generation with a per-request timeout to prevent stalling
                response = await asyncio.wait_for(
                    client.aio.models.generate_content(
                        model=self.model,
                        contents=prompt_text,
                        config=config,
                    ),
                    timeout=20.0,
                )

                text_output = response.text or ""
                return LLMResponse(
                    content=text_output,
                    prompt_tokens=100,
                    completion_tokens=50,
                )

            except (Exception, asyncio.TimeoutError) as e:
                err_str = str(e).lower()
                is_transient = isinstance(e, asyncio.TimeoutError) or any(
                    code in err_str
                    for code in (
                        "503",
                        "429",
                        "unavailable",
                        "resource_exhausted",
                        "high demand",
                        "rate limit",
                        "timeout",
                        "connection",
                    )
                )
                if is_transient and attempt < max_attempts:
                    logger.warning(
                        "Gemini API transient error, retrying...",
                        attempt=attempt,
                        backoff=backoff_sec,
                        error=str(e),
                    )
                    await asyncio.sleep(backoff_sec)
                    backoff_sec *= 2.0
                    continue

                logger.error("Gemini API call failed", attempt=attempt, error=str(e))
                raise LLMError(f"Gemini error: {e}") from e
