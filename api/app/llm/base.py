"""Provider-agnostic contract for structured extraction.

One call shape — system prompt, user prompt, Pydantic schema out — implemented by
each backend. Two reasons this seam exists rather than calling a vendor SDK inline:

*   The default backend is a fixture-driven fake, so a fresh clone runs the whole
    test suite with no API key and no spend, and CI never depends on a third party.
*   Swapping providers is an env var, not a refactor. Which matters because the
    right provider changes with the budget.

Calls are stateless. The retry-on-bad-evidence loop composes a fresh user message
each attempt instead of holding a conversation, which keeps every backend simple.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import ClassVar, Generic, TypeVar

from pydantic import BaseModel

SchemaT = TypeVar("SchemaT", bound=BaseModel)


class LLMError(Exception):
    """Base class for extraction backend failures."""


class LLMConfigError(LLMError):
    """The backend is selected but not usable — missing key, unknown model."""


class LLMUnavailableError(LLMError):
    """The backend could not be reached, or refused the request transiently."""


class LLMResponseError(LLMError):
    """The backend replied, but not with something matching the schema."""


@dataclass(frozen=True, slots=True)
class TokenPrice:
    """USD per million tokens."""

    input_usd: float
    output_usd: float
    cached_input_usd: float = 0.0

    def cost_for(self, *, input_tokens: int, output_tokens: int, cached_tokens: int) -> float:
        billed_input = max(input_tokens - cached_tokens, 0)
        return (
            billed_input * self.input_usd
            + cached_tokens * self.cached_input_usd
            + output_tokens * self.output_usd
        ) / 1_000_000


@dataclass(slots=True)
class LLMUsage:
    """What one call consumed.

    Recorded per call so cost per application is a measured number rather than an
    estimate. `cost_usd` is None when the provider's price is not known.
    """

    provider: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cached_input_tokens: int = 0
    latency_ms: int = 0
    cost_usd: float | None = None

    @property
    def cache_hit(self) -> bool:
        return self.cached_input_tokens > 0


@dataclass(slots=True)
class StructuredResult(Generic[SchemaT]):
    value: SchemaT
    usage: LLMUsage
    raw_text: str = field(default="", repr=False)
    """The unparsed response body, kept for debugging a schema mismatch."""


class StructuredExtractor(ABC):
    """A backend that turns a prompt into a validated Pydantic object."""

    provider_name: ClassVar[str]

    @abstractmethod
    async def extract(
        self,
        *,
        system: str,
        user: str,
        schema: type[SchemaT],
    ) -> StructuredResult[SchemaT]:
        """Return an instance of `schema`.

        Raises:
            LLMUnavailableError: the backend could not be reached.
            LLMResponseError: the reply did not match `schema`.
        """

    async def aclose(self) -> None:
        """Release any held connections. Safe to call more than once."""
        return None
