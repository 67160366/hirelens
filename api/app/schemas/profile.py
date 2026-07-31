"""The shape we store and serve after evidence has been verified.

A claim only appears here if its quote was located in the source document. Claims
that failed verification are not silently discarded — they move to `dropped`,
which is both the debugging trail and the hallucination metric.
"""

from __future__ import annotations

from collections import Counter
from typing import Self

from pydantic import BaseModel, Field, computed_field

from app.pipeline.evidence import MatchKind, RejectReason, ResolvedSpan
from app.schemas.extraction import Seniority


class EvidenceRef(BaseModel):
    """Where in the document a claim came from.

    `char_start`/`char_end` index the parsed document text; `page` is derived from
    them so the UI can jump straight to the right page.
    """

    quote: str
    char_start: int
    char_end: int
    page: int
    match_kind: MatchKind
    is_ambiguous: bool = False

    @classmethod
    def from_span(cls, span: ResolvedSpan, page: int) -> Self:
        return cls(
            quote=span.quote,
            char_start=span.char_start,
            char_end=span.char_end,
            page=page,
            match_kind=span.match_kind,
            is_ambiguous=span.is_ambiguous,
        )


class Claim(BaseModel):
    """A verified value: the claim plus the span that backs it."""

    value: str
    evidence: EvidenceRef


class DroppedClaim(BaseModel):
    """A claim removed because its quote could not be found in the document."""

    field: str = Field(description="Dotted path of the claim, e.g. 'experiences[1].title'.")
    value: str
    quote: str = Field(description="What the model claimed to be quoting.")
    reason: RejectReason


class Experience(BaseModel):
    company: str
    title: str
    start: str
    end: str
    evidence: EvidenceRef


class Education(BaseModel):
    institution: str
    credential: str
    evidence: EvidenceRef


class EvidenceStats(BaseModel):
    """Per-document verification counters.

    This is the project's headline metric and it costs nothing to produce: no
    labelled dataset, no baseline to beat, just a count of what the validator
    accepted and rejected.
    """

    verified: int = 0
    dropped: int = 0
    by_match_kind: dict[MatchKind, int] = Field(default_factory=dict)
    by_reject_reason: dict[RejectReason, int] = Field(default_factory=dict)
    attempts: int = Field(default=1, description="Model calls spent on this document.")

    @computed_field  # type: ignore[prop-decorator]
    @property
    def total_claims(self) -> int:
        return self.verified + self.dropped

    @computed_field  # type: ignore[prop-decorator]
    @property
    def hallucination_rate(self) -> float:
        """Share of claims whose quote was not in the document."""
        if self.total_claims == 0:
            return 0.0
        return round(self.dropped / self.total_claims, 4)

    @classmethod
    def build(
        cls,
        *,
        match_kinds: list[MatchKind],
        reject_reasons: list[RejectReason],
        attempts: int,
    ) -> Self:
        return cls(
            verified=len(match_kinds),
            dropped=len(reject_reasons),
            by_match_kind=dict(Counter(match_kinds)),
            by_reject_reason=dict(Counter(reject_reasons)),
            attempts=attempts,
        )


class ExtractedProfile(BaseModel):
    """A resume as the system understands it — every field traceable to source."""

    full_name: Claim | None = None
    headline: Claim | None = None
    years_experience: Claim | None = None
    seniority: Seniority = Seniority.UNKNOWN
    seniority_evidence: EvidenceRef | None = None
    skills: list[Claim] = Field(default_factory=list)
    experiences: list[Experience] = Field(default_factory=list)
    education: list[Education] = Field(default_factory=list)

    dropped: list[DroppedClaim] = Field(default_factory=list)
    stats: EvidenceStats = Field(default_factory=EvidenceStats)
