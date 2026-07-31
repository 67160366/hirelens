"""Tests for the extraction pipeline.

This is where the product's promise is enforced end-to-end: a real PDF goes in, and
what comes out contains only claims whose quotes were located in that PDF.
"""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar

import pytest

from app.llm.base import (
    LLMUnavailableError,
    LLMUsage,
    SchemaT,
    StructuredExtractor,
    StructuredResult,
)
from app.llm.fake import FakeExtractor, FakeMode
from app.pipeline.evidence import RejectReason
from app.pipeline.extract import extract_profile
from app.pipeline.parse import parse_pdf
from app.schemas.extraction import RawClaim, RawExtraction, RawSkill, Seniority

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def resume_en():
    return parse_pdf(FIXTURES / "resume_en.pdf")


@pytest.fixture(scope="module")
def resume_th():
    return parse_pdf(FIXTURES / "resume_th.pdf")


class ScriptedExtractor(StructuredExtractor):
    """Returns canned extractions in order, for cases the rule-based fake cannot pose."""

    provider_name: ClassVar[str] = "scripted"

    def __init__(self, *responses: RawExtraction) -> None:
        self._responses = list(responses)
        self.call_count = 0

    async def extract(
        self, *, system: str, user: str, schema: type[SchemaT]
    ) -> StructuredResult[SchemaT]:
        self.call_count += 1
        # Repeat the last response once the script runs out.
        index = min(self.call_count - 1, len(self._responses) - 1)
        usage = LLMUsage(provider=self.provider_name, model="scripted", cost_usd=0.0)
        return StructuredResult(value=self._responses[index], usage=usage)  # type: ignore[arg-type]


class TestFaithfulExtraction:
    async def test_produces_a_profile_from_a_real_pdf(self, resume_en):
        outcome = await extract_profile(resume_en, FakeExtractor())
        profile = outcome.profile

        assert profile.full_name is not None
        assert profile.full_name.value == "Somchai Jaidee"
        assert profile.seniority is Seniority.SENIOR
        assert [s.value for s in profile.skills] == [
            "Python",
            "FastAPI",
            "PostgreSQL",
            "Redis",
            "Docker",
            "pytest",
        ]
        assert len(profile.experiences) == 2
        assert len(profile.education) == 1

    async def test_nothing_is_dropped_and_hallucination_rate_is_zero(self, resume_en):
        outcome = await extract_profile(resume_en, FakeExtractor())
        assert outcome.profile.dropped == []
        assert outcome.profile.stats.dropped == 0
        assert outcome.profile.stats.hallucination_rate == 0.0
        assert outcome.profile.stats.verified == outcome.profile.stats.total_claims

    async def test_every_evidence_offset_slices_back_to_its_quote(self, resume_en):
        """The offset contract, checked across a whole real document."""
        outcome = await extract_profile(resume_en, FakeExtractor())
        references = _all_references(outcome.profile)
        assert references, "expected the profile to carry evidence"

        for reference in references:
            assert resume_en.text[reference.char_start : reference.char_end] == reference.quote

    async def test_every_evidence_reference_names_a_real_page(self, resume_en):
        outcome = await extract_profile(resume_en, FakeExtractor())
        for reference in _all_references(outcome.profile):
            assert 1 <= reference.page <= resume_en.page_count

    async def test_one_call_is_enough_when_the_model_behaves(self, resume_en):
        extractor = FakeExtractor()
        outcome = await extract_profile(resume_en, extractor, max_attempts=3)
        assert extractor.call_count == 1
        assert outcome.profile.stats.attempts == 1


class TestThaiExtraction:
    async def test_thai_resume_extracts_with_verified_evidence(self, resume_th):
        outcome = await extract_profile(resume_th, FakeExtractor())
        profile = outcome.profile

        assert profile.full_name is not None
        assert profile.full_name.value == "สมชาย ใจดี"
        assert profile.seniority is Seniority.SENIOR
        assert profile.stats.dropped == 0

    async def test_thai_evidence_offsets_are_exact(self, resume_th):
        outcome = await extract_profile(resume_th, FakeExtractor())
        for reference in _all_references(outcome.profile):
            assert resume_th.text[reference.char_start : reference.char_end] == reference.quote


class TestHallucinationHandling:
    async def test_a_fabricated_claim_is_removed_from_the_profile(self, resume_en):
        outcome = await extract_profile(
            resume_en, FakeExtractor(FakeMode.HALLUCINATING), max_attempts=1
        )
        skills = [s.value for s in outcome.profile.skills]
        assert "Team leadership" not in skills

    async def test_the_fabrication_is_recorded_rather_than_silently_dropped(self, resume_en):
        outcome = await extract_profile(
            resume_en, FakeExtractor(FakeMode.HALLUCINATING), max_attempts=1
        )
        assert len(outcome.profile.dropped) == 1
        dropped = outcome.profile.dropped[0]
        assert dropped.value == "Team leadership"
        assert dropped.reason is RejectReason.NOT_FOUND
        assert dropped.field.startswith("skills[")

    async def test_hallucination_rate_reflects_the_drop(self, resume_en):
        outcome = await extract_profile(
            resume_en, FakeExtractor(FakeMode.HALLUCINATING), max_attempts=1
        )
        stats = outcome.profile.stats
        assert stats.dropped == 1
        assert 0 < stats.hallucination_rate < 1
        assert stats.by_reject_reason == {RejectReason.NOT_FOUND: 1}

    async def test_a_rejection_triggers_a_retry(self, resume_en):
        extractor = FakeExtractor(FakeMode.HALLUCINATING)
        outcome = await extract_profile(resume_en, extractor, max_attempts=3)
        # The fake never improves, so it burns every attempt.
        assert extractor.call_count == 3
        assert outcome.profile.stats.attempts == 3

    async def test_a_clean_retry_is_preferred_over_a_dirty_first_attempt(self, resume_en):
        """The retry path's reason for existing."""
        dirty = RawExtraction(
            full_name=RawClaim(value="Somchai Jaidee", quote="Somchai Jaidee"),
            skills=[RawSkill(name="Kubernetes", quote="deep Kubernetes expertise since 2014")],
        )
        clean = RawExtraction(
            full_name=RawClaim(value="Somchai Jaidee", quote="Somchai Jaidee"),
            skills=[RawSkill(name="Python", quote="Python")],
        )
        extractor = ScriptedExtractor(dirty, clean)

        outcome = await extract_profile(resume_en, extractor, max_attempts=2)

        assert extractor.call_count == 2
        assert outcome.profile.dropped == []
        assert [s.value for s in outcome.profile.skills] == ["Python"]

    async def test_keeps_the_least_bad_attempt_when_none_are_clean(self, resume_en):
        worse = RawExtraction(
            skills=[
                RawSkill(name="A", quote="fabricated quote number one"),
                RawSkill(name="B", quote="fabricated quote number two"),
            ]
        )
        better = RawExtraction(skills=[RawSkill(name="C", quote="fabricated quote number three")])
        extractor = ScriptedExtractor(worse, better)

        outcome = await extract_profile(resume_en, extractor, max_attempts=2)

        assert len(outcome.profile.dropped) == 1


class TestInferenceGuards:
    async def test_unsupported_seniority_is_downgraded_to_unknown(self, resume_en):
        """Seniority is the field a model is most tempted to invent."""
        raw = RawExtraction(
            seniority=Seniority.LEAD,
            seniority_quote="promoted to engineering lead in 2023",
        )
        outcome = await extract_profile(resume_en, ScriptedExtractor(raw), max_attempts=1)

        assert outcome.profile.seniority is Seniority.UNKNOWN
        assert outcome.profile.seniority_evidence is None
        assert [d.field for d in outcome.profile.dropped] == ["seniority"]

    async def test_supported_seniority_keeps_its_evidence(self, resume_en):
        raw = RawExtraction(
            seniority=Seniority.SENIOR,
            seniority_quote="Senior Backend Engineer",
        )
        outcome = await extract_profile(resume_en, ScriptedExtractor(raw), max_attempts=1)

        assert outcome.profile.seniority is Seniority.SENIOR
        assert outcome.profile.seniority_evidence is not None
        assert outcome.profile.seniority_evidence.quote == "Senior Backend Engineer"

    async def test_too_short_quote_is_rejected_with_its_own_reason(self, resume_en):
        raw = RawExtraction(skills=[RawSkill(name="Go", quote="Go")])
        outcome = await extract_profile(resume_en, ScriptedExtractor(raw), max_attempts=1)

        assert outcome.profile.skills == []
        assert outcome.profile.dropped[0].reason is RejectReason.TOO_SHORT


class TestCostAccounting:
    async def test_usage_is_recorded_per_call(self, resume_en):
        outcome = await extract_profile(
            resume_en, FakeExtractor(FakeMode.HALLUCINATING), max_attempts=2
        )
        assert len(outcome.usages) == 2
        assert outcome.total_cost_usd == 0.0

    async def test_unknown_price_makes_the_total_unknown_rather_than_wrong(self, resume_en):
        class UnpricedExtractor(ScriptedExtractor):
            async def extract(self, *, system, user, schema):
                result = await super().extract(system=system, user=user, schema=schema)
                result.usage.cost_usd = None
                return result

        outcome = await extract_profile(
            resume_en, UnpricedExtractor(RawExtraction()), max_attempts=1
        )
        assert outcome.total_cost_usd is None


class TestFailurePropagation:
    async def test_backend_outage_is_not_swallowed(self, resume_en):
        with pytest.raises(LLMUnavailableError):
            await extract_profile(resume_en, FakeExtractor(FakeMode.UNAVAILABLE))

    async def test_max_attempts_must_be_at_least_one(self, resume_en):
        with pytest.raises(ValueError, match="at least 1"):
            await extract_profile(resume_en, FakeExtractor(), max_attempts=0)

    async def test_an_empty_extraction_is_a_valid_empty_profile(self, resume_en):
        outcome = await extract_profile(resume_en, ScriptedExtractor(RawExtraction()))
        profile = outcome.profile
        assert profile.full_name is None
        assert profile.skills == []
        assert profile.stats.total_claims == 0
        # No claims means nothing was fabricated, so the rate is 0, not undefined.
        assert profile.stats.hallucination_rate == 0.0


def _all_references(profile):
    """Every EvidenceRef in a profile, wherever it lives."""
    references = []
    for claim in (profile.full_name, profile.headline, profile.years_experience):
        if claim is not None:
            references.append(claim.evidence)
    if profile.seniority_evidence is not None:
        references.append(profile.seniority_evidence)
    references.extend(skill.evidence for skill in profile.skills)
    references.extend(role.evidence for role in profile.experiences)
    references.extend(entry.evidence for entry in profile.education)
    return references
