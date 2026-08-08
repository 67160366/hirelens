"""Tests for document parsing.

The offset contract is what matters here: `ParsedDocument.text` is the coordinate
space every evidence span points into, so page boundaries and offsets have to be
exact, and Thai has to survive extraction intact.
"""

from __future__ import annotations

import json
import unicodedata
from itertools import pairwise
from pathlib import Path

import pdfplumber
import pytest

from app.pipeline.evidence import EvidenceResolver, ResolvedSpan
from app.pipeline.parse import (
    CorruptDocumentError,
    EmptyDocumentError,
    NoTextLayerError,
    ParsedDocument,
    UnsupportedFileTypeError,
    _assemble,
    parse_document,
    parse_pdf,
)

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def resume_en():
    return parse_pdf(FIXTURES / "resume_en.pdf")


@pytest.fixture(scope="module")
def resume_th():
    return parse_pdf(FIXTURES / "resume_th.pdf")


@pytest.fixture(scope="module")
def multipage():
    return parse_pdf(FIXTURES / "resume_multipage.pdf")


@pytest.fixture(scope="module")
def two_column():
    return parse_pdf(FIXTURES / "resume_two_column.pdf")


@pytest.fixture(scope="module")
def two_column_header():
    return parse_pdf(FIXTURES / "resume_two_column_header.pdf")


class TestEnglishResume:
    def test_extracts_expected_content(self, resume_en):
        assert "Somchai Jaidee" in resume_en.text
        assert "Acme Logistics" in resume_en.text
        assert "Chulalongkorn University" in resume_en.text

    def test_single_page_spans_whole_text(self, resume_en):
        assert resume_en.page_count == 1
        page = resume_en.pages[0]
        assert page.page_number == 1
        assert page.char_start == 0
        assert page.char_end == len(resume_en.text)

    def test_no_pages_flagged_as_missing_text(self, resume_en):
        assert resume_en.pages_without_text == ()
        assert not resume_en.is_partially_scanned


class TestThaiResume:
    def test_thai_words_survive_extraction_unbroken(self, resume_th):
        """If extraction split Thai mid-word, every downstream quote would need
        the loosest matching tier. Assert the clean path holds."""
        assert "วิศวกรซอฟต์แวร์อาวุโส" in resume_th.text
        assert "ประสบการณ์ทำงาน" in resume_th.text
        assert "จุฬาลงกรณ์มหาวิทยาลัย" in resume_th.text

    def test_thai_quotes_resolve_exactly(self, resume_th):
        """The parser and the resolver have to agree on Thai, not just each work."""
        from app.pipeline.evidence import MatchKind

        resolver = EvidenceResolver(resume_th.text)
        result = resolver.resolve("ดูแลระบบกระทบยอดการชำระเงินด้วย Python และ PostgreSQL")
        assert isinstance(result, ResolvedSpan)
        assert result.match_kind is MatchKind.EXACT

    def test_mixed_thai_and_latin_on_one_line(self, resume_th):
        assert "Python, FastAPI, PostgreSQL, Docker, การออกแบบระบบ" in resume_th.text


class TestPageMapping:
    def test_page_spans_are_contiguous_and_ordered(self, multipage):
        assert multipage.page_count == 3
        for earlier, later in pairwise(multipage.pages):
            assert earlier.char_end <= later.char_start
            assert later.page_number == earlier.page_number + 1

    def test_page_text_slices_back_out_of_the_document(self, multipage):
        """Each page's span must isolate that page's content."""
        for page in multipage.pages:
            chunk = multipage.text[page.char_start : page.char_end]
            assert f"Project Portfolio — Page {page.page_number}" in chunk

    @pytest.mark.parametrize("page_number", [1, 2, 3])
    def test_offset_maps_back_to_the_right_page(self, multipage, page_number: int):
        marker = f"distinctive marker P{page_number}I3"
        offset = multipage.text.index(marker)
        assert multipage.page_for_offset(offset) == page_number

    def test_offsets_outside_the_document_clamp_instead_of_raising(self, multipage):
        """A citation should never fail to render over an off-by-one."""
        assert multipage.page_for_offset(-5) == 1
        assert multipage.page_for_offset(10**9) == 3

    def test_evidence_offsets_carry_a_page_number(self, multipage):
        """The parser/resolver handoff that the API depends on."""
        resolver = EvidenceResolver(multipage.text)
        result = resolver.resolve("Page 2 project 4: distinctive marker P2I4.")
        assert isinstance(result, ResolvedSpan)
        assert multipage.page_for_offset(result.char_start) == 2


class TestStoredPageSpans:
    """Page mapping for a quote located long after the upload — what judging does.

    The round trip goes through `resumes.page_spans`, so it has to survive being
    stored as plain JSON and read back without re-parsing anything.
    """

    def test_spans_round_trip_through_the_stored_shape(self, multipage):
        restored = ParsedDocument.from_stored(multipage.text, multipage.stored_page_spans)
        assert restored.pages == multipage.pages
        assert restored.page_count == multipage.page_count

    def test_stored_shape_is_json_safe(self, multipage):
        """It lands in a JSON column, so it may hold only ints and str keys."""
        assert json.loads(json.dumps(multipage.stored_page_spans)) == multipage.stored_page_spans

    @pytest.mark.parametrize("page_number", [1, 2, 3])
    def test_a_restored_document_maps_offsets_to_the_same_pages(self, multipage, page_number: int):
        restored = ParsedDocument.from_stored(multipage.text, multipage.stored_page_spans)
        offset = multipage.text.index(f"distinctive marker P{page_number}I3")
        assert restored.page_for_offset(offset) == page_number

    def test_a_new_quote_resolves_against_restored_text_with_its_page(self, multipage):
        """The judging path end to end: resolve, then name the page."""
        restored = ParsedDocument.from_stored(multipage.text, multipage.stored_page_spans)
        result = EvidenceResolver(restored.text).resolve(
            "Page 2 project 4: distinctive marker P2I4."
        )
        assert isinstance(result, ResolvedSpan)
        assert restored.page_for_offset(result.char_start) == 2

    def test_rows_written_before_the_migration_report_page_one(self, multipage):
        """Null `page_spans` is honest, not broken — those rows never recorded them."""
        restored = ParsedDocument.from_stored(multipage.text, None)
        assert restored.pages == ()
        assert restored.page_for_offset(len(multipage.text) - 1) == 1

    def test_restoring_reparses_nothing(self, multipage):
        """The property that separates this from `reparse_document`: same text in,
        same text out, byte for byte, whatever the OCR configuration now is."""
        restored = ParsedDocument.from_stored(multipage.text, multipage.stored_page_spans)
        assert restored.text == multipage.text

    def test_ocr_page_lists_survive_when_supplied(self, multipage):
        restored = ParsedDocument.from_stored(
            multipage.text,
            multipage.stored_page_spans,
            pages_without_text=[3],
            pages_from_ocr=[2],
        )
        assert restored.pages_without_text == (3,)
        assert restored.pages_from_ocr == (2,)
        assert restored.used_ocr


class TestScannedAndBlank:
    def test_image_only_pdf_reports_a_scan(self):
        """Recoverable by OCR in M2 — the error says so."""
        with pytest.raises(NoTextLayerError) as exc:
            parse_pdf(FIXTURES / "resume_scanned.pdf")
        assert exc.value.page_count == 1

    def test_blank_pdf_is_distinguished_from_a_scan(self):
        """OCR cannot rescue a blank page; conflating the two would send it there."""
        with pytest.raises(EmptyDocumentError):
            parse_pdf(FIXTURES / "empty.pdf")

    def test_partial_scan_parses_and_reports_the_ocr_work_list(self):
        doc = parse_pdf(FIXTURES / "resume_mixed_scan.pdf")
        assert doc.page_count == 2
        assert doc.pages_without_text == (2,)
        assert doc.is_partially_scanned
        # Page 1 still yields usable text rather than failing the whole document.
        assert "Preecha Boonmee" in doc.text


class TestFailureModes:
    def test_non_pdf_bytes_raise_a_clear_error(self):
        with pytest.raises(CorruptDocumentError):
            parse_pdf(FIXTURES / "not_a_pdf.pdf")

    def test_unsupported_extension_names_the_extension(self):
        # `.docx` used to be the example here; it routes to a real parser now.
        with pytest.raises(UnsupportedFileTypeError) as exc:
            parse_document(Path("resume.rtf"))
        assert exc.value.suffix == ".rtf"

    def test_missing_file_raises_rather_than_returning_empty(self):
        with pytest.raises((CorruptDocumentError, FileNotFoundError)):
            parse_pdf(FIXTURES / "does_not_exist.pdf")


class TestControlCharacters:
    """A real-world PDF with a broken ToUnicode map made pdfplumber emit U+0000
    for glyphs it could not name (a Thai tone mark, in the incident). Postgres
    refuses NUL in a text column, so it must never leave the parser."""

    PAGE_ONE = "วิทยาลัยที\x00่คุณจบ — ประวัติการทำงานและการศึกษาของผู้สมัคร"
    PAGE_TWO = "Skills: Python, FastAPI\x00, PostgreSQL and Docker\x00"

    def test_nul_never_leaves_the_parser(self):
        doc = _assemble([self.PAGE_ONE, self.PAGE_TWO])
        assert "\x00" not in doc.text
        # The characters around each NUL survive, joined back up.
        assert "วิทยาลัยที่คุณจบ" in doc.text
        assert "FastAPI, PostgreSQL" in doc.text

    def test_offsets_are_measured_after_the_strip(self):
        """Stripping happens before spans are computed, so each page's span must
        slice its own cleaned text back out exactly — no shifted citations."""
        doc = _assemble([self.PAGE_ONE, self.PAGE_TWO])
        for page, original in zip(doc.pages, (self.PAGE_ONE, self.PAGE_TWO), strict=True):
            expected = unicodedata.normalize("NFC", original).replace("\x00", "")
            assert doc.text[page.char_start : page.char_end] == expected


class TestADamagedPDF:
    """The road to the seam above, walked by a real file.

    The two tests before this one hand `_assemble` strings that already contain
    NUL, which pins the strip but assumes the premise. `resume_broken_tounicode.pdf`
    is a PDF whose font map says several glyphs mean U+0000 — the shape of the
    incident in `docs/HANDOFF.md` §11 — so the premise is checked too: pdfplumber
    really does emit NUL for it, and the parser really does remove it.

    Every other fixture in this repo is well-formed, which makes them prove less
    than they look like they do. This is the only one that is broken on purpose.
    """

    PATH = FIXTURES / "resume_broken_tounicode.pdf"

    def test_pdfplumber_really_does_emit_nul_for_it(self):
        """Guards the fixture itself. If a future pdfplumber stops producing NUL
        here, the tests below would keep passing while testing nothing."""
        with pdfplumber.open(self.PATH) as pdf:
            raw = pdf.pages[0].extract_text() or ""
        assert "\x00" in raw

    def test_the_parser_removes_it(self):
        document = parse_pdf(self.PATH)
        assert "\x00" not in document.text

    def test_the_undamaged_text_survives(self):
        """Only the broken glyphs are lost — the file is damaged, not unreadable."""
        document = parse_pdf(self.PATH)
        assert "PostgreSQL" in document.text
        assert "Acme Log" in document.text

    def test_offsets_still_slice_back_out(self):
        """The reason the strip happens before spans are measured: a citation into
        this document has to point where it says it points."""
        document = parse_pdf(self.PATH)
        for page in document.pages:
            assert document.text[page.char_start : page.char_end] in document.text
        assert document.pages[-1].char_end == len(document.text)


class TestTwoColumnLayout:
    """A two-column page is read one column at a time (M2 #6).

    pdfplumber reads a page in visual order, which interleaves two columns: a job
    title from the right column lands next to contact details from the left.
    Evidence quotes stay truthful either way — the text really is in the document —
    but adjacency is most of what an extractor uses to decide which company a role
    belongs to, so the wrong company gets attached to the wrong role.

    The characterization test that pinned the old interleaved behaviour was deleted
    when `app/pipeline/layout.py` landed and the strict xfail below started passing.
    """

    def test_all_content_is_present(self, two_column):
        """Nothing is lost — reordering must not drop or duplicate anything."""
        for expected in (
            "Nadia Wong",
            "nadia.w@example.com",
            "Northstar Cloud — SRE",
            "Go, Kubernetes",
            "Highland Systems — DevOps",
        ):
            assert two_column.text.count(expected) == 1

    def test_columns_should_read_one_after_the_other(self, two_column):
        """Finish the left column before starting the right.

        This assertion is the one that defined "done" for M2 #6. It carried a
        `xfail(strict=True)` from M1 until `app/pipeline/layout.py` landed, at which
        point it started passing and failed the suite on purpose — the signal to
        delete the characterization test above it and take this marker off. The test
        itself stays, and keeps its name, so the rule in `CLAUDE.md` still points at
        something real.
        """
        text = two_column.text
        assert text.index("Chiang Mai, Thailand") < text.index("Northstar Cloud")

    def test_header_and_footer_bracket_the_columns(self, two_column_header):
        """A full-width header is read before both columns and a footer after both.

        The header is why detection cuts horizontally first: a line that spans the
        gutter hides it from any profile taken over the whole page.
        """
        text = two_column_header.text
        assert text.index("Ratana Phongam") < text.index("CONTACT")
        assert text.index("Ratana Phongam") < text.index("EXPERIENCE")
        assert text.index("Kubernetes, Grafana") < text.index("Mekong Payments")
        assert text.index("Isan Retail") < text.index("References available on request")

    def test_offsets_still_slice_back_out(self, two_column, two_column_header):
        """Reordering happens before spans are measured, so the offset contract holds."""
        for document in (two_column, two_column_header):
            for page in document.pages:
                assert document.text[page.char_start : page.char_end].strip()
            assert document.pages[-1].char_end == len(document.text)
