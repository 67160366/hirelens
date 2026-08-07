"""Tests for the DOCX parser.

The offset contract is the same one `test_parse.py` pins for PDFs: whatever comes
out, `ParsedDocument.text` is the coordinate space evidence points into, and Thai
has to survive intact.

What is different is pages. A .docx does not have any — Word decides where page 2
starts when it renders — so the interesting assertions here are about *not*
inventing them, and about tables, which is where a resume's skills usually live.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.pipeline.evidence import EvidenceResolver, MatchKind, ResolvedSpan
from app.pipeline.parse import (
    CorruptDocumentError,
    EmptyDocumentError,
    parse_document,
    parse_document_bytes,
    parse_docx,
)

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def resume():
    return parse_docx(FIXTURES / "resume_th.docx")


class TestContent:
    def test_paragraphs_are_read(self, resume):
        assert "Kanya Sriwong" in resume.text
        assert "Lanna Data — Data Engineer (Feb 2022 - Present)" in resume.text

    def test_thai_survives_intact(self, resume):
        assert "วิศวกรข้อมูล" in resume.text
        assert "สร้างไปป์ไลน์ ETL ด้วย Python และ Airflow" in resume.text
        assert "มหาวิทยาลัยเชียงใหม่" in resume.text

    def test_table_cells_are_read(self, resume):
        """Resumes routinely put skills in a table. `document.paragraphs` skips
        those entirely, and the loss would look like a model that missed them."""
        assert "Python" in resume.text
        assert "Airflow, dbt" in resume.text
        assert "6 years" in resume.text

    def test_a_table_row_stays_on_one_line(self, resume):
        """Tab between cells, newline between rows — so a row reads as one line
        here just as it does in Word."""
        assert "Python\t6 years" in resume.text

    def test_document_order_is_preserved(self, resume):
        """The body's child order is walked rather than paragraphs-then-tables,
        so the skills table sits between its heading and the next section."""
        assert resume.text.index("SKILLS") < resume.text.index("Python\t6 years")
        assert resume.text.index("Python\t6 years") < resume.text.index("การศึกษา")


class TestQuotesResolve:
    def test_a_paragraph_quote_resolves_exactly(self, resume):
        resolver = EvidenceResolver(resume.text)
        result = resolver.resolve("สร้างไปป์ไลน์ ETL ด้วย Python และ Airflow")
        assert isinstance(result, ResolvedSpan)
        assert result.match_kind is MatchKind.EXACT

    def test_a_table_quote_resolves_exactly(self, resume):
        resolver = EvidenceResolver(resume.text)
        assert isinstance(resolver.resolve("Airflow, dbt"), ResolvedSpan)

    def test_a_fabricated_quote_is_still_rejected(self, resume):
        resolver = EvidenceResolver(resume.text)
        assert not isinstance(resolver.resolve("Led a team of 30 engineers"), ResolvedSpan)


class TestPages:
    """A .docx has no pages, and the parser must not pretend otherwise."""

    def test_the_whole_document_is_one_page(self, resume):
        assert resume.page_count == 1
        assert resume.pages[0].char_start == 0
        assert resume.pages[0].char_end == len(resume.text)

    def test_every_offset_maps_to_page_one(self, resume):
        """ "Somewhere in this document" is true; "page 2" would be a guess."""
        assert resume.page_for_offset(0) == 1
        assert resume.page_for_offset(len(resume.text) - 1) == 1

    def test_nothing_is_reported_as_needing_ocr(self, resume):
        """There is no text layer to be missing, so neither field applies."""
        assert resume.pages_without_text == ()
        assert resume.pages_from_ocr == ()


class TestFailureModes:
    def test_an_empty_docx_is_reported_as_blank(self):
        with pytest.raises(EmptyDocumentError):
            parse_docx(FIXTURES / "empty.docx")

    def test_a_pdf_renamed_to_docx_is_not_mistaken_for_one(self):
        data = (FIXTURES / "resume_en.pdf").read_bytes()
        with pytest.raises(CorruptDocumentError):
            parse_document_bytes(data, filename="resume.docx")

    def test_garbage_bytes_raise_a_clear_error(self):
        with pytest.raises(CorruptDocumentError):
            parse_document_bytes(b"not a document at all", filename="resume.docx")


class TestDispatch:
    """`.docx` used to be the example of an unsupported type; now it routes."""

    def test_parse_document_routes_docx(self):
        assert "Kanya Sriwong" in parse_document(FIXTURES / "resume_th.docx").text

    def test_parse_document_bytes_routes_docx(self):
        data = (FIXTURES / "resume_th.docx").read_bytes()
        assert "Kanya Sriwong" in parse_document_bytes(data, filename="CV.DOCX").text
