"""Gemini LLM client implementation using Google GenAI SDK."""

from typing import Any

import google.genai as genai

from veltrix.api.errors import LLMError
from veltrix.core.logging import get_logger
from veltrix.llm.base import LLMRequest, LLMResponse

logger = get_logger("gemini_client")


class GeminiClient:
    """LLM client adapter for Google Gemini models using official google-genai SDK."""

    def __init__(self, api_key: str, model: str = "gemini-2.5-flash") -> None:
        self.api_key = api_key
        self.model = model
        self._client: genai.Client | None = None

    def _get_client(self) -> genai.Client:
        if self._client is None:
            # If no API key provided, GenAI SDK checks GEMINI_API_KEY env var
            self._client = genai.Client(api_key=self.api_key) if self.api_key else genai.Client()
        return self._client

    async def complete(self, request: LLMRequest) -> LLMResponse:
        """Call Gemini model asynchronously."""
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
                config["response_schema"] = request.response_schema

            # Execute generation
            response = await client.aio.models.generate_content(
                model=self.model,
                contents=prompt_text,
                config=config,
            )

            text_output = response.text or ""
            return LLMResponse(
                content=text_output,
                prompt_tokens=100,
                completion_tokens=50,
            )

        except Exception as e:
            logger.error("Gemini API call failed", error=str(e))
            raise LLMError(f"Gemini error: {e}") from e
