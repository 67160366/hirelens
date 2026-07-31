"""Google Gemini backend.

Chosen as the default real provider because its free tier is generous enough to
develop and demo against, it takes a Pydantic model directly as `response_schema`
(so the same schema drives every backend), and its 1M context window swallows a
long resume without chunking.

Thinking tokens are billed as output on Gemini 2.5, so `thoughts_token_count` is
folded into `output_tokens` rather than ignored — otherwise cost-per-application
reads low for exactly the calls that cost most.
"""

from __future__ import annotations

import time
from typing import ClassVar

from google import genai
from google.genai import errors as genai_errors
from google.genai import types

from app.llm.base import (
    LLMConfigError,
    LLMResponseError,
    LLMUnavailableError,
    LLMUsage,
    SchemaT,
    StructuredExtractor,
    StructuredResult,
    TokenPrice,
)

# USD per million tokens. Zero reflects the free tier, which is what this project
# runs on. If you move to a paid tier, replace these with the current published
# rates — a wrong price here silently corrupts the cost dashboard.
FREE_TIER = TokenPrice(input_usd=0.0, output_usd=0.0, cached_input_usd=0.0)
_PRICES: dict[str, TokenPrice] = {
    "gemini-2.5-flash": FREE_TIER,
    "gemini-2.5-flash-lite": FREE_TIER,
    "gemini-2.5-pro": FREE_TIER,
}


class GeminiExtractor(StructuredExtractor):
    provider_name: ClassVar[str] = "gemini"

    def __init__(
        self,
        *,
        api_key: str,
        model: str = "gemini-2.5-flash",
        thinking_budget: int | None = None,
        max_output_tokens: int | None = None,
        timeout_seconds: float = 120.0,
    ) -> None:
        if not api_key:
            raise LLMConfigError(
                "GEMINI_API_KEY is not set. Create a free key at "
                "https://aistudio.google.com/apikey, or set LLM_PROVIDER=fake."
            )
        self._model = model
        self._thinking_budget = thinking_budget
        self._max_output_tokens = max_output_tokens
        self._client = genai.Client(
            api_key=api_key,
            # The SDK takes milliseconds here.
            http_options=types.HttpOptions(timeout=int(timeout_seconds * 1000)),
        )

    @property
    def model(self) -> str:
        return self._model

    async def extract(
        self,
        *,
        system: str,
        user: str,
        schema: type[SchemaT],
    ) -> StructuredResult[SchemaT]:
        config = types.GenerateContentConfig(
            system_instruction=system,
            response_mime_type="application/json",
            response_schema=schema,
            max_output_tokens=self._max_output_tokens,
            thinking_config=(
                types.ThinkingConfig(thinking_budget=self._thinking_budget)
                if self._thinking_budget is not None
                else None
            ),
        )

        started = time.perf_counter()
        try:
            response = await self._client.aio.models.generate_content(
                model=self._model,
                contents=user,
                config=config,
            )
        except genai_errors.ClientError as exc:
            # 4xx. A bad key or an exhausted free-tier quota lands here, and both
            # are actionable by the operator rather than retryable in a loop.
            raise LLMUnavailableError(f"Gemini rejected the request: {exc}") from exc
        except genai_errors.APIError as exc:
            raise LLMUnavailableError(f"Gemini call failed: {exc}") from exc
        latency_ms = int((time.perf_counter() - started) * 1000)

        parsed = response.parsed
        if not isinstance(parsed, schema):
            # Happens when the model is cut off mid-JSON, or a safety filter fires.
            raise LLMResponseError(
                f"Gemini did not return a valid {schema.__name__}; got {type(parsed).__name__}"
            )

        return StructuredResult(
            value=parsed,
            usage=self._usage(response, latency_ms),
            raw_text=response.text or "",
        )

    def _usage(self, response: types.GenerateContentResponse, latency_ms: int) -> LLMUsage:
        meta = response.usage_metadata
        input_tokens = (meta.prompt_token_count or 0) if meta else 0
        cached_tokens = (meta.cached_content_token_count or 0) if meta else 0
        # Thinking is billed as output; count it or under-report the expensive calls.
        output_tokens = (
            ((meta.candidates_token_count or 0) + (meta.thoughts_token_count or 0)) if meta else 0
        )

        price = _PRICES.get(self._model)
        cost = (
            price.cost_for(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cached_tokens=cached_tokens,
            )
            if price is not None
            else None
        )

        return LLMUsage(
            provider=self.provider_name,
            model=self._model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cached_input_tokens=cached_tokens,
            latency_ms=latency_ms,
            cost_usd=cost,
        )
