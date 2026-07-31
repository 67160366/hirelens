"""Pick an extraction backend from settings."""

from __future__ import annotations

from app.config import LLMProvider, Settings
from app.llm.base import LLMConfigError, StructuredExtractor
from app.llm.fake import FakeExtractor


def build_extractor(settings: Settings) -> StructuredExtractor:
    """Construct the backend named by `settings.llm_provider`.

    Imports are local so that selecting one provider never requires the others'
    SDKs to be importable.
    """
    match settings.llm_provider:
        case LLMProvider.FAKE:
            return FakeExtractor(settings.fake_mode)

        case LLMProvider.GEMINI:
            from app.llm.gemini import GeminiExtractor

            return GeminiExtractor(
                api_key=settings.gemini_api_key,
                model=settings.gemini_model,
            )

        case LLMProvider.ANTHROPIC:
            # Not implemented rather than half-implemented: an adapter that has
            # never run against the real API is worse than an honest error. The
            # seam is here — see docs/llm-providers.md for what it costs to add.
            raise LLMConfigError(
                "The Anthropic backend is not implemented yet. Use LLM_PROVIDER=gemini "
                "(free) or LLM_PROVIDER=fake (offline)."
            )
