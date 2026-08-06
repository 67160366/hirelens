"""Gemini adapter tests against a mocked SDK — no network and no real key.

The live path is exercised manually through the CLI (docs/llm-providers.md);
what these pin is the adapter's contract: error mapping, schema enforcement,
and the thinking-tokens-are-billed-as-output rule.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from google.genai import errors as genai_errors

from app.llm.base import LLMConfigError, LLMResponseError, LLMUnavailableError
from app.llm.gemini import GeminiExtractor
from app.schemas.extraction import RawClaim, RawExtraction


def make_extractor(model: str = "gemini-3.6-flash") -> GeminiExtractor:
    return GeminiExtractor(api_key="test-key-not-real", model=model)


def stub_response(
    text: str,
    *,
    prompt_tokens: int = 100,
    candidate_tokens: int = 40,
    thought_tokens: int = 0,
    cached_tokens: int = 0,
) -> SimpleNamespace:
    """The slice of GenerateContentResponse the adapter reads.

    With `response_json_schema` the SDK does not parse the reply; the adapter
    validates `text` itself, so that is what the stub carries.
    """
    return SimpleNamespace(
        text=text,
        usage_metadata=SimpleNamespace(
            prompt_token_count=prompt_tokens,
            candidates_token_count=candidate_tokens,
            thoughts_token_count=thought_tokens,
            cached_content_token_count=cached_tokens,
        ),
    )


def install_reply(
    extractor: GeminiExtractor, monkeypatch: pytest.MonkeyPatch, reply: object
) -> None:
    """Make the SDK client return `reply`, or raise it if it is an exception."""

    async def fake_generate_content(**kwargs: object) -> object:
        if isinstance(reply, Exception):
            raise reply
        return reply

    monkeypatch.setattr(extractor._client.aio.models, "generate_content", fake_generate_content)


class TestConstruction:
    def test_a_missing_key_is_a_config_error_with_a_next_step(self):
        with pytest.raises(LLMConfigError, match="GEMINI_API_KEY"):
            GeminiExtractor(api_key="")


class TestExtract:
    async def test_returns_the_validated_schema_with_usage(self, monkeypatch: pytest.MonkeyPatch):
        extractor = make_extractor()
        raw = RawExtraction(full_name=RawClaim(value="Somchai", quote="Somchai"))
        install_reply(
            extractor, monkeypatch, stub_response(raw.model_dump_json(), prompt_tokens=120)
        )

        result = await extractor.extract(system="s", user="u", schema=RawExtraction)

        assert result.value == raw
        assert result.usage.provider == "gemini"
        assert result.usage.model == "gemini-3.6-flash"
        assert result.usage.input_tokens == 120

    async def test_thinking_tokens_are_billed_as_output(self, monkeypatch: pytest.MonkeyPatch):
        """Gemini 2.5 bills thinking as output; ignoring it under-reports the
        expensive calls."""
        extractor = make_extractor()
        empty = RawExtraction().model_dump_json()
        install_reply(
            extractor,
            monkeypatch,
            stub_response(empty, candidate_tokens=40, thought_tokens=60),
        )

        result = await extractor.extract(system="s", user="u", schema=RawExtraction)

        assert result.usage.output_tokens == 100

    async def test_free_tier_cost_is_zero_not_unknown(self, monkeypatch: pytest.MonkeyPatch):
        extractor = make_extractor()
        install_reply(extractor, monkeypatch, stub_response(RawExtraction().model_dump_json()))

        result = await extractor.extract(system="s", user="u", schema=RawExtraction)

        assert result.usage.cost_usd == 0.0

    async def test_an_unpriced_model_reports_cost_as_unknown(self, monkeypatch: pytest.MonkeyPatch):
        """None, never a misleading zero — the price table has no row for it."""
        extractor = make_extractor(model="gemini-99-experimental")
        install_reply(extractor, monkeypatch, stub_response(RawExtraction().model_dump_json()))

        result = await extractor.extract(system="s", user="u", schema=RawExtraction)

        assert result.usage.cost_usd is None

    async def test_a_truncated_or_filtered_reply_is_a_response_error(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """The reply body is broken JSON when the model was cut off by
        max_output_tokens or a safety filter — the caller must see a typed
        error, not a crash."""
        extractor = make_extractor()
        install_reply(extractor, monkeypatch, stub_response('{"full_name": {"value": "Som'))

        with pytest.raises(LLMResponseError, match="RawExtraction"):
            await extractor.extract(system="s", user="u", schema=RawExtraction)

    async def test_a_quota_rejection_maps_to_unavailable(self, monkeypatch: pytest.MonkeyPatch):
        extractor = make_extractor()
        quota = genai_errors.ClientError(
            429, {"error": {"message": "quota exhausted", "status": "RESOURCE_EXHAUSTED"}}
        )
        install_reply(extractor, monkeypatch, quota)

        with pytest.raises(LLMUnavailableError, match="Gemini"):
            await extractor.extract(system="s", user="u", schema=RawExtraction)

    async def test_a_server_error_maps_to_unavailable(self, monkeypatch: pytest.MonkeyPatch):
        extractor = make_extractor()
        outage = genai_errors.APIError(500, {"error": {"message": "internal"}})
        install_reply(extractor, monkeypatch, outage)

        with pytest.raises(LLMUnavailableError, match="Gemini"):
            await extractor.extract(system="s", user="u", schema=RawExtraction)
