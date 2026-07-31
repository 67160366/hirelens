"""Tests for the evidence resolver.

These are the tests that matter most in the project: the resolver is what stops
a plausible-sounding fabrication from reaching a recruiter's screen.
"""

from __future__ import annotations

import pytest

from app.pipeline.evidence import (
    EvidenceResolver,
    MatchKind,
    RejectedQuote,
    RejectReason,
    ResolvedSpan,
)

RESUME = """Somchai Jaidee
Senior Backend Engineer

EXPERIENCE
Acme Co — Backend Engineer (Jan 2021 - Mar 2024)
  Built payment reconciliation services in Python and
  PostgreSQL, handling 40k transactions per day.

SKILLS
Python, FastAPI, PostgreSQL, Docker
"""


def resolve(quote: str, source: str = RESUME):
    return EvidenceResolver(source).resolve(quote)


class TestExactMatch:
    def test_locates_verbatim_quote(self):
        result = resolve("Senior Backend Engineer")
        assert isinstance(result, ResolvedSpan)
        assert result.match_kind is MatchKind.EXACT
        assert RESUME[result.char_start : result.char_end] == "Senior Backend Engineer"

    def test_offsets_always_slice_back_to_the_quote(self):
        """The offset contract: slicing the source must reproduce the span."""
        for quote in ("Somchai Jaidee", "Jan 2021 - Mar 2024", "40k transactions per day"):
            result = resolve(quote)
            assert isinstance(result, ResolvedSpan)
            assert RESUME[result.char_start : result.char_end] == result.quote

    def test_strips_surrounding_whitespace_from_model_output(self):
        result = resolve("  FastAPI  ")
        assert isinstance(result, ResolvedSpan)
        assert result.quote == "FastAPI"


class TestWhitespaceTolerance:
    def test_matches_quote_that_the_model_reflowed_across_a_line_break(self):
        """The source wraps mid-sentence; the model reports it as one line."""
        result = resolve("Built payment reconciliation services in Python and PostgreSQL")
        assert isinstance(result, ResolvedSpan)
        assert result.match_kind is MatchKind.WHITESPACE_COLLAPSED
        # The span covers the real text, newline and indentation included.
        assert "\n" in result.quote

    def test_returns_the_source_text_not_the_models_rendering(self):
        """A reviewer should see what the document says, not the model's reflow."""
        model_quote = "Built payment reconciliation services in Python and PostgreSQL"
        result = resolve(model_quote)
        assert isinstance(result, ResolvedSpan)
        assert result.quote != model_quote
        assert result.quote == RESUME[result.char_start : result.char_end]

    def test_collapses_runs_of_spaces_in_the_quote(self):
        result = resolve("Python,    FastAPI")
        assert isinstance(result, ResolvedSpan)
        assert result.match_kind is MatchKind.WHITESPACE_COLLAPSED


class TestThaiText:
    THAI_RESUME = "ประสบการณ์ทำงาน\nบริษัท เอซีเอ็มอี จำกัด — วิศวกรซอฟต์แวร์\nดูแลระบบชำระเงิน\n"

    def test_locates_verbatim_thai_quote(self):
        result = resolve("วิศวกรซอฟต์แวร์", self.THAI_RESUME)
        assert isinstance(result, ResolvedSpan)
        assert result.match_kind is MatchKind.EXACT

    def test_rescues_quote_when_pdf_injected_stray_spaces_mid_word(self):
        """PDF extraction commonly breaks Thai words apart. Tier 3 handles it."""
        source = "ตำแหน่ง: วิศ วกร ซอฟต์ แวร์ อาวุโส"
        result = resolve("วิศวกรซอฟต์แวร์อาวุโส", source)
        assert isinstance(result, ResolvedSpan)
        assert result.match_kind is MatchKind.WHITESPACE_STRIPPED
        assert source[result.char_start : result.char_end] == "วิศ วกร ซอฟต์ แวร์ อาวุโส"

    def test_combining_marks_normalize_before_comparison(self):
        """Thai vowel/tone marks must not fail to match on encoding alone."""
        result = resolve("ดูแลระบบชำระเงิน", self.THAI_RESUME)
        assert isinstance(result, ResolvedSpan)


class TestRejection:
    def test_rejects_a_fabricated_quote(self):
        """The hallucination case — this is what the whole module exists for."""
        result = resolve("Led a team of 12 engineers at Google")
        assert isinstance(result, RejectedQuote)
        assert result.reason is RejectReason.NOT_FOUND

    def test_rejects_a_quote_that_only_looks_close(self):
        """Kubernetes is never mentioned; near-miss phrasing must not pass."""
        result = resolve("Built payment reconciliation services in Kubernetes")
        assert isinstance(result, RejectedQuote)
        assert result.reason is RejectReason.NOT_FOUND

    def test_rejects_empty_quote(self):
        assert resolve("").reason is RejectReason.EMPTY
        assert resolve("   \n  ").reason is RejectReason.EMPTY

    @pytest.mark.parametrize("quote", ["Go", "AI", "an", "x"])
    def test_rejects_quotes_too_short_to_be_evidence(self, quote: str):
        result = resolve(quote)
        assert isinstance(result, RejectedQuote)
        assert result.reason is RejectReason.TOO_SHORT

    def test_short_stripped_quote_does_not_fall_through_to_loosest_tier(self):
        """Tier 3 must not let a short fragment match inside an unrelated word."""
        result = resolve("go", "I work with django daily")
        assert isinstance(result, RejectedQuote)


class TestAmbiguity:
    def test_flags_a_quote_that_appears_more_than_once(self):
        source = "PostgreSQL experience. Also: PostgreSQL tuning."
        result = resolve("PostgreSQL", source)
        assert isinstance(result, ResolvedSpan)
        assert result.occurrences == 2
        assert result.is_ambiguous
        # Reports the first hit rather than guessing which one was meant.
        assert result.char_start == source.index("PostgreSQL")

    def test_unique_quote_is_not_ambiguous(self):
        result = resolve("Somchai Jaidee")
        assert isinstance(result, ResolvedSpan)
        assert result.occurrences == 1
        assert not result.is_ambiguous


class TestResolverReuse:
    def test_one_resolver_handles_many_quotes(self):
        """Built once per document, reused across every extracted field."""
        resolver = EvidenceResolver(RESUME)
        quotes = ["Somchai Jaidee", "FastAPI", "Acme Co", "not in the document at all"]
        results = [resolver.resolve(q) for q in quotes]
        assert [isinstance(r, ResolvedSpan) for r in results] == [True, True, True, False]

    def test_empty_document_rejects_everything(self):
        resolver = EvidenceResolver("")
        result = resolver.resolve("anything at all")
        assert isinstance(result, RejectedQuote)
        assert result.reason is RejectReason.NOT_FOUND
