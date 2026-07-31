"""Tests for document parsing.

The offset contract is what matters here: `ParsedDocument.text` is the coordinate
space every evidence span points into, so page boundaries and offsets have to be
exact, and Thai has to survive extraction intact.
"""

from __future__ import annotations

from itertools import pairwise
from pathlib import Path

import pytest

from app.pipeline.evidence import EvidenceResolver, ResolvedSpan
from app.pipeline.parse import (
    CorruptDocumentError,
    EmptyDocumentError,
    NoTextLayerError,
    UnsupportedFileTypeError,
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
        with pytest.raises(UnsupportedFileTypeError) as exc:
            parse_document(Path("resume.docx"))
        assert exc.value.suffix == ".docx"

    def test_missing_file_raises_rather_than_returning_empty(self):
        with pytest.raises((CorruptDocumentError, FileNotFoundError)):
            parse_pdf(FIXTURES / "does_not_exist.pdf")


class TestTwoColumnLayout:
    """Characterization tests for a known limitation.

    pdfplumber reads a two-column page in visual order, which interleaves the two
    columns: a job title from the right column lands next to contact details from
    the left. Evidence quotes stay truthful — the text really is in the document —
    but adjacency is misleading, so an extractor can attach the wrong company to
    the wrong role.

    These tests pin the current behaviour so that fixing it in M2 (bbox-based
    column detection) is a visible, deliberate change rather than a silent one.
    """

    def test_all_content_is_present(self, two_column):
        """Nothing is lost — the problem is ordering, not omission."""
        for expected in (
            "Nadia Wong",
            "nadia.w@example.com",
            "Northstar Cloud — SRE",
            "Go, Kubernetes",
            "Highland Systems — DevOps",
        ):
            assert expected in two_column.text

    def test_columns_are_currently_interleaved(self, two_column):
        """KNOWN LIMITATION. When M2 adds column detection, this test should fail
        and be replaced with the correct-order assertion below it."""
        text = two_column.text
        # The right column's EXPERIENCE heading appears before the left column's
        # CONTACT heading, even though CONTACT is visually higher on the left.
        assert text.index("EXPERIENCE") < text.index("CONTACT")

    @pytest.mark.xfail(reason="Needs bbox-based column detection — scheduled for M2", strict=True)
    def test_columns_should_read_one_after_the_other(self, two_column):
        """The behaviour we want: finish the left column before starting the right."""
        text = two_column.text
        assert text.index("Chiang Mai, Thailand") < text.index("Northstar Cloud")
