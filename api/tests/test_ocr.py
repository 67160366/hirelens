"""Tests for the OCR fallback.

Driven by a stub engine rather than a real Tesseract, for the same reason the
suite runs on the fake extraction backend: OCR needs a system binary, CI will
never have one, and `git clone && pytest -q` has to stay green with no servers.
Real Tesseract is exercised by the opt-in `test_ocr_tesseract.py`.

What matters here is the offset contract. OCR text is substituted before page
spans are measured, so a rescued page has to be indistinguishable from a page
that always had text — the same slice-it-back-out assertion `test_parse.py` makes.
"""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar

import pytest

from app.jobs import is_retryable
from app.pipeline.evidence import EvidenceResolver, ResolvedSpan
from app.pipeline.ocr import OCREngine, OCRError, OCRUnavailableError
from app.pipeline.parse import (
    EmptyDocumentError,
    NoTextLayerError,
    parse_pdf,
)

FIXTURES = Path(__file__).parent / "fixtures"

# Long enough to clear MIN_CHARS_PER_TEXT_PAGE, so the page counts as recovered.
RECOGNIZED = "Somchai Jaidee — Senior Backend Engineer\nSkills: Python, FastAPI"


class StubOCR(OCREngine):
    """Returns canned text and records what it was asked to read."""

    engine_name: ClassVar[str] = "stub"

    def __init__(self, text: str = RECOGNIZED, *, fails: bool = False) -> None:
        self._text = text
        self._fails = fails
        self.calls: list[int] = []
        # Small, so a test that cares about rendering cost does not pay for it.
        self.dpi = 72

    def recognize(self, image: object, *, page_number: int) -> str:
        self.calls.append(page_number)
        if self._fails:
            raise OCRError(f"stub failure on page {page_number}")
        return self._text


class TestAScanIsRecovered:
    def test_an_image_only_pdf_parses_instead_of_raising(self):
        """The whole point: this document used to be a permanent failure."""
        engine = StubOCR()
        doc = parse_pdf(FIXTURES / "resume_scanned.pdf", ocr=engine)

        assert engine.calls == [1]
        assert doc.pages_from_ocr == (1,)
        assert doc.used_ocr
        assert "Somchai Jaidee" in doc.text

    def test_a_recovered_page_is_no_longer_reported_as_text_less(self):
        """`pages_without_text` is a work list, so it must not name a done page."""
        doc = parse_pdf(FIXTURES / "resume_scanned.pdf", ocr=StubOCR())
        assert doc.pages_without_text == ()

    def test_without_an_engine_the_scan_still_fails(self):
        """OCR is opt-in; the default is exactly the old behaviour."""
        with pytest.raises(NoTextLayerError) as exc:
            parse_pdf(FIXTURES / "resume_scanned.pdf")
        assert exc.value.ocr_attempted is False


class TestPartialScans:
    """The interesting case: one page from a text layer, one from OCR."""

    @pytest.fixture
    def mixed(self):
        engine = StubOCR()
        return engine, parse_pdf(FIXTURES / "resume_mixed_scan.pdf", ocr=engine)

    def test_only_the_text_less_page_is_sent_to_ocr(self, mixed):
        """Page 1 already has text — rendering and recognizing it would be waste."""
        engine, doc = mixed
        assert engine.calls == [2]
        assert doc.pages_from_ocr == (2,)

    def test_the_text_layer_page_is_untouched(self, mixed):
        _, doc = mixed
        assert "Preecha Boonmee" in doc.text
        assert "Data platform engineer" in doc.text

    def test_each_page_still_slices_its_own_text_back_out(self, mixed):
        """The offset contract. OCR text is substituted before spans are measured,
        so page boundaries have to survive it exactly."""
        _, doc = mixed
        assert doc.page_count == 2
        assert "Preecha Boonmee" in doc.text[doc.pages[0].char_start : doc.pages[0].char_end]
        assert RECOGNIZED in doc.text[doc.pages[1].char_start : doc.pages[1].char_end]

    def test_a_quote_from_the_ocr_page_resolves_exactly(self, mixed):
        """The guardrail is unchanged: the model quotes the text it was shown."""
        _, doc = mixed
        resolver = EvidenceResolver(doc.text)
        result = resolver.resolve("Skills: Python, FastAPI")
        assert isinstance(result, ResolvedSpan)
        assert doc.page_for_offset(result.char_start) == 2

    def test_a_fabricated_quote_is_still_rejected(self, mixed):
        """OCR must not become a way for an unverified claim to get through."""
        _, doc = mixed
        resolver = EvidenceResolver(doc.text)
        assert not isinstance(resolver.resolve("Led a team of 40 engineers"), ResolvedSpan)


class TestWhenOCRFindsNothing:
    def test_empty_recognition_leaves_the_scan_failed(self):
        engine = StubOCR("")
        with pytest.raises(NoTextLayerError) as exc:
            parse_pdf(FIXTURES / "resume_scanned.pdf", ocr=engine)
        assert engine.calls == [1]
        # The message has to say OCR ran, rather than asking for OCR again.
        assert exc.value.ocr_attempted is True
        assert "recognized no usable text" in str(exc.value)

    def test_noise_below_the_threshold_never_enters_the_document(self):
        """A handful of stray characters is not text somebody wrote, and this
        project only quotes text somebody wrote."""
        engine = StubOCR("|.:")
        with pytest.raises(NoTextLayerError):
            parse_pdf(FIXTURES / "resume_scanned.pdf", ocr=engine)

    def test_one_page_failing_does_not_cost_the_pages_that_worked(self):
        """A mixed scan whose OCR fails still keeps page 1's real text."""
        engine = StubOCR(fails=True)
        doc = parse_pdf(FIXTURES / "resume_mixed_scan.pdf", ocr=engine)
        assert "Preecha Boonmee" in doc.text
        assert doc.pages_from_ocr == ()
        assert doc.pages_without_text == (2,)


class TestBlankPagesAreNotOCRed:
    def test_a_blank_pdf_never_reaches_the_engine(self):
        """A blank page has no image to read. Rendering it would spend a second
        per page to recognize nothing, and would blur the reason reported."""
        engine = StubOCR()
        with pytest.raises(EmptyDocumentError):
            parse_pdf(FIXTURES / "empty.pdf", ocr=engine)
        assert engine.calls == []


class TestTheBudget:
    def test_pages_past_max_pages_are_left_alone(self):
        """A long scan must not pin a worker for minutes."""
        engine = StubOCR()
        engine.max_pages = 0
        with pytest.raises(NoTextLayerError):
            parse_pdf(FIXTURES / "resume_scanned.pdf", ocr=engine)
        assert engine.calls == []


class TestFailureClassification:
    def test_an_unusable_engine_is_permanent_not_transient(self):
        """A missing binary will still be missing in five seconds. Retrying it
        three times only burns the budget; `POST /retry` after fixing the config
        is the real path."""
        assert is_retryable(OCRUnavailableError("no tesseract")) is False

    def test_a_failed_recognition_is_transient(self):
        """A timeout or a crashed subprocess is the kind of blip a retry fixes."""
        assert is_retryable(OCRError("timed out")) is True
