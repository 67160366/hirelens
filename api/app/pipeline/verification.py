"""The bookkeeping both pipelines keep while checking a model's quotes.

`extract.py` and `judge.py` ask different questions — what is this candidate's
profile, and which requirements does this resume evidence — but they enforce the
guarantee identically: resolve every quote against the source, keep only what was
located, and record what was not so it shows up in `dropped` and in the
hallucination rate. That loop lives here once.

It is a separate module rather than a function in either of them because it needs
`pipeline.evidence` *and* `schemas.profile`, and `schemas.profile` already imports
`pipeline.evidence` — putting it in the lower of the two would be a cycle.

Nothing here decides anything. It resolves and it counts; what a resolved quote
*means* is the caller's question, and deliberately so: it is what lets judging
derive a verdict from an empty evidence list without this module knowing verdicts
exist.
"""

from __future__ import annotations

from app.pipeline.evidence import (
    EvidenceResolver,
    MatchKind,
    RejectedQuote,
    RejectReason,
)
from app.pipeline.parse import ParsedDocument
from app.schemas.profile import DroppedClaim, EvidenceRef, EvidenceStats


class EvidenceRecorder:
    """Resolves quotes against one document, tallying every outcome.

    One instance per attempt: the counters describe that attempt, and both pipelines
    compare attempts by them.
    """

    def __init__(self, document: ParsedDocument) -> None:
        self._document = document
        self._resolver = EvidenceResolver(document.text)
        self.dropped: list[DroppedClaim] = []
        self.match_kinds: list[MatchKind] = []
        self.reject_reasons: list[RejectReason] = []

    def reference(self, *, field: str, value: str, quote: str) -> EvidenceRef | None:
        """Locate a quote, recording the outcome either way.

        `None` means the quote was not in the document — the caller must drop the
        claim it belonged to rather than keeping it unverified. That is the whole
        contract, and it is why this returns an optional instead of raising.
        """
        resolution = self._resolver.resolve(quote)

        if isinstance(resolution, RejectedQuote):
            self.reject_reasons.append(resolution.reason)
            self.dropped.append(
                DroppedClaim(field=field, value=value, quote=quote, reason=resolution.reason)
            )
            return None

        self.match_kinds.append(resolution.match_kind)
        return EvidenceRef.from_span(
            resolution, page=self._document.page_for_offset(resolution.char_start)
        )

    def reject(self, *, field: str, value: str, quote: str, reason: RejectReason) -> None:
        """Record a claim rejected for a reason the resolver cannot produce.

        Judging needs this for `UNKNOWN_REQUIREMENT`: a quote attached to a
        requirement number nobody asked about may well be real text, but it cannot be
        attributed to anything, so locating it would answer the wrong question. It
        still belongs in `dropped` and in the rate — the alternative is discarding it
        in silence, which this project does not do.
        """
        self.reject_reasons.append(reason)
        self.dropped.append(DroppedClaim(field=field, value=value, quote=quote, reason=reason))

    def stats(self, *, attempts: int) -> EvidenceStats:
        return EvidenceStats.build(
            match_kinds=self.match_kinds,
            reject_reasons=self.reject_reasons,
            attempts=attempts,
        )
