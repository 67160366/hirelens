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

import subprocess
from pathlib import Path
from typing import ClassVar

import pytest

import app.pipeline.ocr as ocr_module
from app.jobs import is_retryable
from app.pipeline.evidence import EvidenceResolver, ResolvedSpan
from app.pipeline.ocr import (
    OCREngine,
    OCRError,
    OCRUnavailableError,
    TesseractEngine,
    _mean_confidence,
)
from app.pipeline.parse import (
    EmptyDocumentError,
    NoTextLayerError,
    parse_pdf,
)

FIXTURES = Path(__file__).parent / "fixtures"

# Long enough to clear MIN_CHARS_PER_TEXT_PAGE, so the page counts as recovered.
RECOGNIZED = "Somchai Jaidee — Senior Backend Engineer\nSkills: Python, FastAPI"


class _Png:
    """Stands in for a PIL image: `TesseractEngine` only ever asks it to save."""

    def save(self, buffer: object, format: str) -> None:
        buffer.write(b"\x89PNG\r\n\x1a\n")  # type: ignore[attr-defined]


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


class TestTheConfidenceGate:
    """`TesseractEngine`'s own gate, driven without a Tesseract.

    The subprocess is stubbed rather than the engine, because the logic under test
    *is* the engine: which invocation runs, in what order, and what the page comes
    back as when the reading is not trustworthy. `test_ocr_tesseract.py` runs the
    same gate against the real binary.
    """

    # Tesseract's TSV header. `conf` is column 10 and `text` is column 11.
    COLUMNS: ClassVar[list[str]] = [
        "level",
        "page_num",
        "block_num",
        "par_num",
        "line_num",
        "word_num",
        "left",
        "top",
        "width",
        "height",
        "conf",
        "text",
    ]
    HEADER = "\t".join(COLUMNS)

    def _tsv(self, *scores: float) -> str:
        rows = [self.HEADER, "5\t1\t1\t1\t1\t0\t0\t0\t0\t0\t-1\t"]  # a non-word row
        rows += [f"5\t1\t1\t1\t1\t{i}\t0\t0\t0\t0\t{s}\tword" for i, s in enumerate(scores, 1)]
        return "\n".join(rows)

    def _engine(self, monkeypatch, tsv: str, text: str, *, min_confidence: float):
        """A TesseractEngine whose subprocess answers `tsv` then `text`."""
        calls: list[list[str]] = []

        def fake_run(command, **kwargs):
            calls.append(list(command))
            payload = tsv if command[-1] == "tsv" else text
            return subprocess.CompletedProcess(command, 0, payload.encode(), b"")

        monkeypatch.setattr(ocr_module.subprocess, "run", fake_run)
        engine = TesseractEngine(
            command="tesseract", languages="tha+eng", min_confidence=min_confidence
        )
        return engine, calls

    def test_a_confident_page_is_returned(self, monkeypatch):
        engine, calls = self._engine(
            monkeypatch, self._tsv(95, 92, 96), "Somchai Jaidee", min_confidence=75
        )
        assert engine.recognize(_Png(), page_number=1) == "Somchai Jaidee"
        assert [call[-1] for call in calls] == ["tsv", "tha+eng"], "confidence is asked first"

    def test_a_page_read_badly_comes_back_empty(self, monkeypatch):
        """Mean 47 is the 6px-blur case from the degradation table: 160 characters
        of confident nonsense, where "Somchai Jaidee" reads "Sore hector". Returning
        the text would put words nobody wrote into `document_text`."""
        engine, calls = self._engine(
            monkeypatch, self._tsv(50, 44, 48), "Sore hector", min_confidence=75
        )
        assert engine.recognize(_Png(), page_number=1) == ""
        assert len(calls) == 1, "a rejected page must not pay for the second call"

    def test_a_rejected_page_leaves_the_scan_failed(self):
        """End to end: the gate reuses the path a page that recognized nothing takes,
        so the user gets "OCR ran but recognized no usable text" rather than a
        profile built from noise."""
        with pytest.raises(NoTextLayerError) as caught:
            parse_pdf(FIXTURES / "resume_scanned.pdf", ocr=StubOCR(""))
        assert caught.value.ocr_attempted is True
        assert "too low quality" in str(caught.value)

    def test_the_gate_off_costs_nothing(self, monkeypatch):
        """`OCR_MIN_CONFIDENCE=0` must not spend the extra invocation."""
        engine, calls = self._engine(monkeypatch, self._tsv(10), "text", min_confidence=0)
        assert engine.recognize(_Png(), page_number=1) == "text"
        assert len(calls) == 1

    def test_a_page_with_no_words_scores_zero(self):
        assert _mean_confidence(self.HEADER) == 0.0

    def test_non_word_rows_do_not_drag_the_average_down(self):
        """Tesseract marks page, block and line rows -1. Counting them as zero would
        reject every page."""
        assert _mean_confidence(self._tsv(90, 90)) == pytest.approx(90.0)


class TestFailureClassification:
    def test_an_unusable_engine_is_permanent_not_transient(self):
        """A missing binary will still be missing in five seconds. Retrying it
        three times only burns the budget; `POST /retry` after fixing the config
        is the real path."""
        assert is_retryable(OCRUnavailableError("no tesseract")) is False

    def test_a_failed_recognition_is_transient(self):
        """A timeout or a crashed subprocess is the kind of blip a retry fixes."""
        assert is_retryable(OCRError("timed out")) is True
