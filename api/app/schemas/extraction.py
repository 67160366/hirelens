"""The shape we ask the model for.

Deliberately narrow: every claim carries a `quote` and nothing else. The model is
never asked for character offsets, page numbers, or confidence scores — it is bad
at all three, and we can derive the first two ourselves from the quote.

Kept JSON-Schema-plain (no recursion, no string/number constraints) so the same
models drive Gemini's `responseSchema` and Anthropic's structured outputs without
per-provider rewriting.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class Seniority(StrEnum):
    JUNIOR = "junior"
    MID = "mid"
    SENIOR = "senior"
    LEAD = "lead"
    UNKNOWN = "unknown"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RawClaim(_Strict):
    """A single extracted value plus the text it came from."""

    value: str = Field(description="The extracted value, normalized for display.")
    quote: str = Field(
        description=(
            "Text copied character-for-character from the document that shows this "
            "value. Do not paraphrase, translate, reformat, or summarize. If no such "
            "text exists, omit the whole claim."
        )
    )


class RawSkill(_Strict):
    name: str = Field(description="The skill as the candidate wrote it.")
    quote: str = Field(description="Verbatim text from the document mentioning this skill.")


class RawExperience(_Strict):
    company: str
    title: str
    start: str = Field(
        description="Start date exactly as written in the document, e.g. 'Jan 2021'."
    )
    end: str = Field(
        description="End date exactly as written, or 'Present' if the role is current."
    )
    quote: str = Field(
        description="Verbatim text from the document covering this role's header line."
    )


class RawEducation(_Strict):
    institution: str
    credential: str = Field(description="Degree or certificate, as written.")
    quote: str = Field(description="Verbatim text from the document covering this entry.")


class RawExtraction(_Strict):
    """The complete model response for one resume."""

    full_name: RawClaim | None = None
    headline: RawClaim | None = Field(
        default=None, description="The candidate's current role or professional summary line."
    )
    years_experience: RawClaim | None = Field(
        default=None,
        description=(
            "Total years of professional experience, only if the document states it "
            "outright. Do not compute it from date ranges — leave this out instead."
        ),
    )
    seniority: Seniority = Field(
        default=Seniority.UNKNOWN,
        description="Use 'unknown' unless the document supports a specific level.",
    )
    seniority_quote: str = Field(
        default="",
        description="Verbatim supporting text. Leave empty when seniority is 'unknown'.",
    )
    skills: list[RawSkill] = Field(default_factory=list)
    experiences: list[RawExperience] = Field(default_factory=list)
    education: list[RawEducation] = Field(default_factory=list)
