"""Tests for the extraction backends and the provider seam.

The fake backend is load-bearing infrastructure, not a stub — the pipeline tests
run through it — so it gets real tests.
"""

from __future__ import annotations

import re

import pytest

from app.config import LLMProvider, Settings
from app.llm.base import LLMConfigError, LLMResponseError, LLMUnavailableError, TokenPrice
from app.llm.fake import FakeExtractor, FakeMode
from app.llm.registry import build_extractor
from app.schemas.extraction import RawExtraction, Seniority

RESUME = """Somchai Jaidee
Senior Backend Engineer

EXPERIENCE
Acme Logistics — Backend Engineer (Jan 2021 - Mar 2024)
Built payment reconciliation services in Python and PostgreSQL.
Siam Digital — Junior Developer (Jun 2019 - Dec 2020)

SKILLS
Python, FastAPI, PostgreSQL, Docker

EDUCATION
Chulalongkorn University — B.Eng Computer Engineering (2015 - 2019)
"""

THAI_RESUME = """สมชาย ใจดี
วิศวกรซอฟต์แวร์อาวุโส

ประสบการณ์ทำงาน
บริษัท เอซีเอ็มอี โลจิสติกส์ — วิศวกรซอฟต์แวร์ (ม.ค. 2564 - มี.ค. 2567)

ทักษะ
Python, FastAPI, การออกแบบระบบ

การศึกษา
จุฬาลงกรณ์มหาวิทยาลัย — วิศวกรรมศาสตรบัณฑิต
"""


async def run_fake(document: str, mode: FakeMode = FakeMode.FAITHFUL) -> RawExtraction:
    result = await FakeExtractor(mode).extract(
        system="ignored", user=document, schema=RawExtraction
    )
    return result.value


class TestFakeExtractorFindsRealContent:
    async def test_reads_name_and_headline(self):
        extraction = await run_fake(RESUME)
        assert extraction.full_name is not None
        assert extraction.full_name.value == "Somchai Jaidee"
        assert extraction.headline is not None
        assert extraction.headline.value == "Senior Backend Engineer"

    async def test_reads_skills_section(self):
        extraction = await run_fake(RESUME)
        assert [s.name for s in extraction.skills] == [
            "Python",
            "FastAPI",
            "PostgreSQL",
            "Docker",
        ]

    async def test_reads_roles_with_dates(self):
        extraction = await run_fake(RESUME)
        assert len(extraction.experiences) == 2
        first = extraction.experiences[0]
        assert first.company == "Acme Logistics"
        assert first.title == "Backend Engineer"
        assert first.start == "Jan 2021"
        assert first.end == "Mar 2024"

    async def test_prose_lines_are_not_mistaken_for_roles(self):
        """A sentence inside the experience section must not become a role."""
        extraction = await run_fake(RESUME)
        companies = [e.company for e in extraction.experiences]
        assert not any("Built payment" in company for company in companies)

    async def test_reads_education(self):
        extraction = await run_fake(RESUME)
        assert len(extraction.education) == 1
        assert extraction.education[0].institution == "Chulalongkorn University"

    async def test_infers_seniority_from_headline(self):
        extraction = await run_fake(RESUME)
        assert extraction.seniority is Seniority.SENIOR
        assert extraction.seniority_quote == "Senior Backend Engineer"

    async def test_unknown_seniority_leaves_the_quote_empty(self):
        extraction = await run_fake("Jane Doe\nDeveloper\n")
        assert extraction.seniority is Seniority.UNKNOWN
        assert extraction.seniority_quote == ""


class TestFakeExtractorHandlesThai:
    async def test_recognizes_thai_section_headings(self):
        extraction = await run_fake(THAI_RESUME)
        assert [s.name for s in extraction.skills] == [
            "Python",
            "FastAPI",
            "การออกแบบระบบ",
        ]
        assert len(extraction.experiences) == 1
        assert extraction.experiences[0].title == "วิศวกรซอฟต์แวร์"

    async def test_detects_thai_seniority_marker(self):
        extraction = await run_fake(THAI_RESUME)
        assert extraction.seniority is Seniority.SENIOR


class TestFakeExtractorQuotesAreReal:
    async def test_every_quote_appears_in_the_source_document(self):
        """The property that makes the fake worth having: it does not invent text,
        so evidence validation downstream behaves as it would in production."""
        extraction = await run_fake(RESUME)

        quotes = [
            extraction.full_name.quote if extraction.full_name else "",
            extraction.headline.quote if extraction.headline else "",
            *(s.quote for s in extraction.skills),
            *(e.quote for e in extraction.experiences),
            *(e.quote for e in extraction.education),
        ]
        missing = [q for q in quotes if q and q not in RESUME]
        assert missing == []

    async def test_hallucinating_mode_emits_a_quote_that_is_not_in_the_source(self):
        """The failure shape the pipeline must survive."""
        extraction = await run_fake(RESUME, FakeMode.HALLUCINATING)
        fabricated = [s for s in extraction.skills if s.quote not in RESUME]
        assert len(fabricated) == 1
        assert fabricated[0].name == "Team leadership"


class TestFakeExtractorFailureModes:
    async def test_unavailable_mode_raises(self):
        with pytest.raises(LLMUnavailableError):
            await run_fake(RESUME, FakeMode.UNAVAILABLE)

    async def test_rejects_a_schema_it_cannot_produce(self):
        from pydantic import BaseModel

        class Unrelated(BaseModel):
            x: int

        with pytest.raises(LLMResponseError):
            await FakeExtractor().extract(system="", user=RESUME, schema=Unrelated)

    async def test_counts_its_calls(self):
        extractor = FakeExtractor()
        for _ in range(3):
            await extractor.extract(system="", user=RESUME, schema=RawExtraction)
        assert extractor.call_count == 3

    async def test_empty_document_yields_an_empty_extraction_not_an_error(self):
        extraction = await run_fake("")
        assert extraction.full_name is None
        assert extraction.skills == []
        assert extraction.experiences == []


class TestRegistry:
    def test_fake_is_the_default_provider(self):
        # _env_file=None: the developer's .env may select a real provider; the
        # test is about the built-in default, not this machine's configuration.
        extractor = build_extractor(Settings(_env_file=None))
        assert extractor.provider_name == "fake"

    def test_gemini_without_a_key_fails_loudly_with_a_next_step(self):
        settings = Settings(llm_provider=LLMProvider.GEMINI, gemini_api_key="")
        with pytest.raises(LLMConfigError, match=re.escape("aistudio.google.com")):
            build_extractor(settings)

    def test_gemini_builds_when_a_key_is_present(self):
        settings = Settings(llm_provider=LLMProvider.GEMINI, gemini_api_key="test-key-not-real")
        extractor = build_extractor(settings)
        assert extractor.provider_name == "gemini"

    def test_anthropic_is_reported_as_unimplemented_rather_than_failing_obscurely(self):
        settings = Settings(llm_provider=LLMProvider.ANTHROPIC, anthropic_api_key="x")
        with pytest.raises(LLMConfigError, match="not implemented"):
            build_extractor(settings)


class TestTokenPricing:
    def test_charges_cached_input_at_the_cached_rate(self):
        price = TokenPrice(input_usd=5.0, output_usd=25.0, cached_input_usd=0.5)
        cost = price.cost_for(input_tokens=1_000_000, output_tokens=0, cached_tokens=800_000)
        # 200k at full rate + 800k at the cached rate.
        assert cost == pytest.approx(200_000 * 5.0 / 1e6 + 800_000 * 0.5 / 1e6)

    def test_free_tier_costs_nothing(self):
        price = TokenPrice(0.0, 0.0)
        assert price.cost_for(input_tokens=50_000, output_tokens=9_000, cached_tokens=0) == 0.0

    def test_cached_count_above_input_count_does_not_go_negative(self):
        """Providers occasionally report cached >= prompt tokens; never bill below zero."""
        price = TokenPrice(input_usd=5.0, output_usd=25.0, cached_input_usd=0.5)
        cost = price.cost_for(input_tokens=100, output_tokens=0, cached_tokens=500)
        assert cost >= 0.0
