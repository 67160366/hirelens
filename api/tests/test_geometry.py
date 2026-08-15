"""Character geometry: where each character of `document_text` sits on its page.

M5 slice 3. What these pin, in rough order of how badly they would fail in silence:

- **Geometry cannot move the text.** This slice touches `parse.py`, the most
  load-bearing module in the project, and the property that keeps every citation
  already shown to a user pointing where it did is that `document_text` and the page
  spans are byte-identical to what they were.
- **Every inked character is covered exactly once, and no whitespace is.** This is
  the invariant that catches an off-by-one anywhere in the chain — the textmap walk,
  the reading-order join, the NUL remap, the page rebase — because almost any drift
  puts a run over a space or past the end.
- **A page whose geometry cannot be proven consistent has none**, rather than
  approximate boxes. A wrong box is a visual claim nobody can check.
- **The NUL strip remaps rather than invalidates.** `resume_broken_tounicode.pdf`
  carries 11 NULs across 8 of its 11 words.
"""

from __future__ import annotations

from itertools import pairwise
from pathlib import Path
from typing import ClassVar

import pytest

from app.pipeline.geometry import CharRun, PageGeometry, from_stored, remap, runs_for, shift, stored
from app.pipeline.ocr import OCREngine
from app.pipeline.parse import ParsedDocument, _assemble, parse_document, parse_pdf

FIXTURES = Path(__file__).parent / "fixtures"

# Every fixture that parses to text. `empty.pdf` and `not_a_pdf.pdf` raise, and
# `resume_scanned.pdf` has no text layer without an OCR engine.
PARSEABLE = [
    "resume_broken_tounicode.pdf",
    "resume_en.pdf",
    "resume_mixed_scan.pdf",
    "resume_multipage.pdf",
    "resume_right_aligned_dates.pdf",
    "resume_th.pdf",
    "resume_two_column.pdf",
    "resume_two_column_header.pdf",
]


def _covered(document: ParsedDocument) -> list[int]:
    return [
        index
        for page in document.page_geometry
        for run in page.runs
        for index in range(run.char_start, run.char_end)
    ]


class TestTheInkedCharactersArePartitioned:
    """The one invariant that catches an off-by-one anywhere in the chain."""

    @pytest.mark.parametrize("name", PARSEABLE)
    def test_every_run_covers_only_inked_characters(self, name: str):
        document = parse_document(FIXTURES / name)

        for index in _covered(document):
            assert index < len(document.text), "a run points past the end of the text"
            character = document.text[index]
            assert not character.isspace(), (
                f"a run covers whitespace at {index}: an inserted separator carries no "
                f"glyph, so covering one means the offsets have drifted"
            )
            assert character != "\x00"

    @pytest.mark.parametrize("name", PARSEABLE)
    def test_every_inked_character_is_covered_exactly_once(self, name: str):
        document = parse_document(FIXTURES / name)
        covered = _covered(document)
        inked = [index for index, char in enumerate(document.text) if not char.isspace()]

        assert covered == inked, (
            "the geometry must be a partition of the inked characters — no gaps, no "
            "overlaps, and in document order"
        )

    @pytest.mark.parametrize("name", PARSEABLE)
    def test_runs_are_ordered_and_do_not_overlap(self, name: str):
        document = parse_document(FIXTURES / name)

        for page in document.page_geometry:
            for earlier, later in pairwise(page.runs):
                assert earlier.char_end <= later.char_start

    @pytest.mark.parametrize("name", PARSEABLE)
    def test_a_run_carries_one_box_per_character(self, name: str):
        document = parse_document(FIXTURES / name)

        for page in document.page_geometry:
            for run in page.runs:
                assert run.char_end - run.char_start == len(run.x)
                for x0, x1 in run.x:
                    assert x0 <= x1
                    assert 0 <= x0 <= page.width + 1, "a box outside the page box"


class TestTheTextIsUnmoved:
    """The property that keeps every citation already shown to a user pointing where
    it did. Measured against HEAD when this slice landed: `document_text`, page spans,
    `pages_without_text` and `pages_from_ocr` were byte-identical across all 13
    fixtures. These keep it true."""

    PAGE_ONE: ClassVar[str] = "Somchai Jaidee — Backend Engineer with plenty of text here"
    PAGE_TWO: ClassVar[str] = "Second page, also carrying more than the minimum characters"

    def test_assembling_without_geometry_is_the_default(self):
        """`_assemble` is the DOCX path too, and the tests that call it with bare
        strings must keep working — a document has to be assemblable from text alone."""
        document = _assemble([self.PAGE_ONE, self.PAGE_TWO])

        assert document.page_geometry == ()
        assert document.text == f"{self.PAGE_ONE}\n\n{self.PAGE_TWO}"

    def test_a_docx_has_no_geometry_and_still_parses(self):
        """Word reflows at render time; there are no glyph boxes in the file."""
        document = parse_document(FIXTURES / "resume_th.docx")

        assert document.page_geometry == ()
        assert document.text

    @pytest.mark.parametrize("name", PARSEABLE)
    def test_page_spans_still_cover_the_text_with_no_drift(self, name: str):
        document = parse_document(FIXTURES / name)

        assert document.pages[0].char_start == 0
        assert document.pages[-1].char_end == len(document.text)


class TestGeometryIsRefusedRatherThanGuessed:
    def test_a_textmap_that_disagrees_with_the_text_yields_none(self):
        """The consistency check is the load-bearing part of `runs_for`."""
        import pdfplumber

        with pdfplumber.open(FIXTURES / "resume_en.pdf") as pdf:
            page = pdf.pages[0]
            assert runs_for(page, page.extract_text() or "") is not None
            assert runs_for(page, "text this page never produced") is None

    def test_an_object_without_a_textmap_yields_none_rather_than_raising(self):
        """`_get_textmap` is underscore-private. A pdfplumber that renames it must
        cost the overlay, never the parse."""

        class NoTextmap:
            pass

        assert runs_for(NoTextmap(), "anything") is None

    def test_empty_text_has_empty_geometry_rather_than_none(self):
        """No characters is a real answer about the page, not a failure to measure."""
        assert runs_for(object(), "") == ()

    def test_an_ocr_page_has_no_geometry(self):
        """OCR replaces a page's text wholesale, so every offset the text layer's
        boxes described is gone. There are no glyph boxes for recognized text."""

        class StubOCR(OCREngine):
            engine_name: ClassVar[str] = "stub"

            def __init__(self) -> None:
                self.dpi = 72

            def recognize(self, image: object, *, page_number: int) -> str:
                return "Recognized text long enough to clear the minimum bar for a page."

        document = parse_pdf(FIXTURES / "resume_mixed_scan.pdf", ocr=StubOCR())

        assert document.pages_from_ocr == (2,)
        rescued = [page.page_number for page in document.page_geometry]
        assert 2 not in rescued, "a page rescued by OCR must carry no geometry"
        assert 1 in rescued, "...and the page that kept its text layer must keep its geometry"


class TestTheNulStrip:
    """`resume_broken_tounicode.pdf` has a well-formed ToUnicode map that says several
    glyphs mean U+0000. 8 of its 11 words carry one, and the NULs shift later
    characters by up to 11 positions — which is why a naive `find()` locates 3 of 11."""

    def test_the_fixture_still_carries_its_nuls_before_assembly(self):
        """A positive control: if the fixture stopped producing NULs this whole class
        would pass while testing nothing."""
        import pdfplumber

        with pdfplumber.open(FIXTURES / "resume_broken_tounicode.pdf") as pdf:
            raw = pdf.pages[0].extract_text() or ""

        assert raw.count("\x00") > 0, "the fixture no longer reproduces the incident"

    def test_the_stored_text_has_none_and_the_geometry_still_lines_up(self):
        document = parse_document(FIXTURES / "resume_broken_tounicode.pdf")

        assert "\x00" not in document.text
        covered = _covered(document)
        inked = [index for index, char in enumerate(document.text) if not char.isspace()]
        assert covered == inked, "the remap must survive characters being removed"


class TestRemap:
    def test_a_removal_inside_a_run_splits_it(self):
        """The halves are no longer contiguous, and one run spanning the gap would
        claim a character range it does not cover."""
        run = CharRun(char_start=0, top=1.0, bottom=2.0, x=((0.0, 1.0), (1.0, 2.0), (2.0, 3.0)))

        out = remap([run], [0, None, 1])

        assert [(r.char_start, r.char_end) for r in out] == [(0, 1), (1, 2)]
        assert [r.x for r in out] == [((0.0, 1.0),), ((2.0, 3.0),)]

    def test_a_removal_at_the_edge_shortens_rather_than_splits(self):
        run = CharRun(char_start=0, top=1.0, bottom=2.0, x=((0.0, 1.0), (1.0, 2.0)))

        out = remap([run], [None, 0])

        assert [(r.char_start, r.char_end) for r in out] == [(0, 1)]

    def test_a_run_removed_entirely_disappears(self):
        run = CharRun(char_start=0, top=1.0, bottom=2.0, x=((0.0, 1.0),))

        assert remap([run], [None]) == ()

    def test_shift_moves_every_run(self):
        run = CharRun(char_start=3, top=1.0, bottom=2.0, x=((0.0, 1.0),))

        assert shift([run], 10)[0].char_start == 13


class TestTheStorageRoundTrip:
    def test_geometry_survives_being_stored_and_read_back(self):
        document = parse_document(FIXTURES / "resume_th.pdf")

        rebuilt = ParsedDocument.from_stored(
            document.text,
            document.stored_page_spans,
            page_geometry=document.stored_page_geometry,
        )

        assert rebuilt.page_geometry == document.page_geometry

    def test_a_row_written_before_migration_0010_reads_back_empty(self):
        """Null is the honest answer for a row that never recorded geometry —
        deliberately not backfilled, exactly like `page_spans` in `0005`."""
        rebuilt = ParsedDocument.from_stored("some stored text", None, page_geometry=None)

        assert rebuilt.page_geometry == ()
        assert rebuilt.text == "some stored text"

    def test_the_stored_shape_is_json_safe(self):
        import json

        document = parse_document(FIXTURES / "resume_two_column.pdf")
        blob = document.stored_page_geometry

        assert json.loads(json.dumps(blob)) == blob
        assert from_stored(blob) == document.page_geometry

    def test_stored_names_its_keys(self):
        page = PageGeometry(
            page_number=1, width=10.0, height=20.0, runs=(CharRun(0, 1.0, 2.0, ((0.0, 1.0),)),)
        )

        assert stored([page]) == [
            {
                "page_number": 1,
                "width": 10.0,
                "height": 20.0,
                "runs": [{"char_start": 0, "top": 1.0, "bottom": 2.0, "x": [[0.0, 1.0]]}],
            }
        ]


class TestTwoColumns:
    """The page where offsets are least recoverable afterwards: the text is assembled
    in *reading* order, which is not the PDF's internal order — walking the words
    visually gives 11 offset inversions on this fixture."""

    def test_the_reordered_page_still_partitions_exactly(self):
        document = parse_document(FIXTURES / "resume_two_column.pdf")
        covered = _covered(document)
        inked = [index for index, char in enumerate(document.text) if not char.isspace()]

        assert covered == inked

    def test_the_right_column_sits_to_the_right_of_the_left_one(self):
        """Reading order is not x order, so the boxes must disagree with the offsets
        somewhere — which is the whole reason this cannot be re-derived downstream."""
        document = parse_document(FIXTURES / "resume_two_column.pdf")
        runs = document.page_geometry[0].runs

        assert any(later.x[0][0] < earlier.x[0][0] for earlier, later in pairwise(runs)), (
            "a later character sitting further left is what reading order produces"
        )
