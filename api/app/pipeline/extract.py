"""Turn a parsed document into a profile in which every field is backed by source.

The shape of this module is the shape of the product's central promise:

    parse -> ask the model -> verify every quote -> keep only what verified

Verification is not advisory. A claim whose quote cannot be located is removed
from the profile and recorded in `dropped`, so the response tells you both what
the system believes and what it refused to believe.

Retries feed the rejected quotes back to the model. If it still cannot cite the
document, the claims stay dropped — the system reports less rather than asserting
something unverifiable.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.llm.base import LLMUsage, StructuredExtractor
from app.pipeline.evidence import (
    EvidenceResolver,
    MatchKind,
    RejectedQuote,
    RejectReason,
)
from app.pipeline.parse import ParsedDocument
from app.pipeline.prompts import (
    EXTRACTION_SYSTEM,
    build_extraction_retry_prompt,
    build_extraction_user_prompt,
)
from app.schemas.extraction import RawExtraction, Seniority
from app.schemas.profile import (
    Claim,
    DroppedClaim,
    Education,
    EvidenceRef,
    EvidenceStats,
    Experience,
    ExtractedProfile,
)


@dataclass(slots=True)
class ExtractionOutcome:
    """A verified profile plus what it cost to produce."""

    profile: ExtractedProfile
    usages: list[LLMUsage]

    @property
    def total_cost_usd(self) -> float | None:
        """None when any call's price is unknown — better than a misleading sum."""
        if any(usage.cost_usd is None for usage in self.usages):
            return None
        return sum(usage.cost_usd or 0.0 for usage in self.usages)

    @property
    def total_latency_ms(self) -> int:
        return sum(usage.latency_ms for usage in self.usages)


class _Verifier:
    """Resolves one raw extraction against one document."""

    def __init__(self, document: ParsedDocument) -> None:
        self._document = document
        self._resolver = EvidenceResolver(document.text)
        self.dropped: list[DroppedClaim] = []
        self.match_kinds: list[MatchKind] = []
        self.reject_reasons: list[RejectReason] = []

    def _reference(self, *, field: str, value: str, quote: str) -> EvidenceRef | None:
        """Resolve a quote, recording the outcome either way."""
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

    def _claim(self, *, field: str, value: str, quote: str) -> Claim | None:
        reference = self._reference(field=field, value=value, quote=quote)
        return Claim(value=value, evidence=reference) if reference else None

    def verify(self, raw: RawExtraction, *, attempts: int) -> ExtractedProfile:
        full_name = (
            self._claim(field="full_name", value=raw.full_name.value, quote=raw.full_name.quote)
            if raw.full_name
            else None
        )
        headline = (
            self._claim(field="headline", value=raw.headline.value, quote=raw.headline.quote)
            if raw.headline
            else None
        )
        years_experience = (
            self._claim(
                field="years_experience",
                value=raw.years_experience.value,
                quote=raw.years_experience.quote,
            )
            if raw.years_experience
            else None
        )

        # Seniority is the field a model is most tempted to infer, so an
        # unsupported level is downgraded to unknown rather than kept unverified.
        seniority = raw.seniority
        seniority_evidence: EvidenceRef | None = None
        if seniority is not Seniority.UNKNOWN:
            seniority_evidence = self._reference(
                field="seniority", value=seniority.value, quote=raw.seniority_quote
            )
            if seniority_evidence is None:
                seniority = Seniority.UNKNOWN

        skills: list[Claim] = []
        for index, skill in enumerate(raw.skills):
            claim = self._claim(field=f"skills[{index}]", value=skill.name, quote=skill.quote)
            if claim is not None:
                skills.append(claim)

        experiences: list[Experience] = []
        for index, role in enumerate(raw.experiences):
            reference = self._reference(
                field=f"experiences[{index}]",
                value=f"{role.title} at {role.company}",
                quote=role.quote,
            )
            if reference is not None:
                experiences.append(
                    Experience(
                        company=role.company,
                        title=role.title,
                        start=role.start,
                        end=role.end,
                        evidence=reference,
                    )
                )

        education: list[Education] = []
        for index, entry in enumerate(raw.education):
            reference = self._reference(
                field=f"education[{index}]",
                value=f"{entry.credential}, {entry.institution}",
                quote=entry.quote,
            )
            if reference is not None:
                education.append(
                    Education(
                        institution=entry.institution,
                        credential=entry.credential,
                        evidence=reference,
                    )
                )

        return ExtractedProfile(
            full_name=full_name,
            headline=headline,
            years_experience=years_experience,
            seniority=seniority,
            seniority_evidence=seniority_evidence,
            skills=skills,
            experiences=experiences,
            education=education,
            dropped=self.dropped,
            stats=EvidenceStats.build(
                match_kinds=self.match_kinds,
                reject_reasons=self.reject_reasons,
                attempts=attempts,
            ),
        )


async def extract_profile(
    document: ParsedDocument,
    extractor: StructuredExtractor,
    *,
    max_attempts: int = 2,
) -> ExtractionOutcome:
    """Extract and verify a profile, re-asking the model about rejected quotes.

    Accepts the first attempt that cites the document cleanly; failing that, keeps
    the attempt with the fewest rejections. Never returns an unverified claim.
    """
    if max_attempts < 1:
        raise ValueError("max_attempts must be at least 1")

    usages: list[LLMUsage] = []
    best: ExtractedProfile | None = None

    for attempt in range(1, max_attempts + 1):
        if attempt == 1 or best is None:
            user_prompt = build_extraction_user_prompt(document.text)
        else:
            user_prompt = build_extraction_retry_prompt(
                document.text, [claim.quote for claim in best.dropped]
            )

        result = await extractor.extract(
            system=EXTRACTION_SYSTEM, user=user_prompt, schema=RawExtraction
        )
        usages.append(result.usage)

        candidate = _Verifier(document).verify(result.value, attempts=attempt)

        if best is None or candidate.stats.dropped < best.stats.dropped:
            best = candidate

        if candidate.stats.dropped == 0:
            break

    if best is None:  # unreachable: max_attempts >= 1 guarantees one pass
        raise RuntimeError("extraction produced no result")
    # Report the number of calls actually made, not the attempt that won.
    best.stats.attempts = len(usages)
    return ExtractionOutcome(profile=best, usages=usages)
