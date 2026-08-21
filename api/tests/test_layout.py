"""Tests for column detection.

Two things are being pinned, and the second matters more than the first:

1.  A genuinely two-column page is split into columns and read one at a time.
2.  **Everything else is left alone.** `detect_reading_order` returning `None` is
    what makes `parse_pdf` fall back to the code path that ran before this module
    existed, so a document that parsed correctly yesterday parses identically today
    and no evidence offset already shown to a user can shift. The guards that
    produce `None` are therefore tested one at a time, at the unit level, where the
    numbers are visible instead of buried in a PDF.
"""

from __future__ import annotations

from itertools import pairwise
from pathlib import Path

import pdfplumber
import pytest

from app.pipeline.layout import (
    _Band,
    _Edges,
    _gutter,
    _merge_columned_bands,
    _within,
    _Word,
    detect_reading_order,
)
from app.pipeline.parse import parse_pdf

FIXTURES = Path(__file__).parent / "fixtures"

# Every fixture that must be read exactly as it was before column detection existed.
SINGLE_COLUMN_FIXTURES = [
    "resume_en.pdf",
    "resume_th.pdf",
    "resume_multipage.pdf",
    "resume_mixed_scan.pdf",
    "resume_scanned.pdf",
    "resume_right_aligned_dates.pdf",
    "empty.pdf",
]

PAGE_WIDTH = 595.0


def _row(*spans: tuple[float, float], top: float) -> list[_Word]:
    """Words on one baseline, given as (x0, x1) pairs."""
    return [_Word(x0=x0, x1=x1, top=top, bottom=top + 10) for x0, x1 in spans]


class TestSingleColumnPagesAreUntouched:
    @pytest.mark.parametrize("name", SINGLE_COLUMN_FIXTURES)
    def test_detection_declines(self, name):
        with pdfplumber.open(FIXTURES / name) as pdf:
            for page in pdf.pages:
                assert detect_reading_order(page) is None

    def test_right_aligned_dates_are_not_a_second_column(self):
        """The realistic false positive: every role line leaves a wide empty strip
        between the title and its date. The bullets underneath run the full width,
        which is what makes it a margin rather than a gutter."""
        document = parse_pdf(FIXTURES / "resume_right_aligned_dates.pdf")
        assert document.text.index("Andaman Software") < document.text.index("2022 - Present")
        assert "Cut p95 checkout latency" in document.text

    def test_a_page_with_too_few_words_declines(self):
        with pdfplumber.open(FIXTURES / "resume_mixed_scan.pdf") as pdf:
            assert detect_reading_order(pdf.pages[1]) is None


class TestTwoColumnPagesAreSplit:
    def test_plain_two_columns_give_two_regions(self):
        with pdfplumber.open(FIXTURES / "resume_two_column.pdf") as pdf:
            boxes = detect_reading_order(pdf.pages[0])
        assert boxes is not None
        assert len(boxes) == 2
        left, right = boxes
        assert left[2] == right[0], "the columns must meet, so no character falls between them"

    def test_a_full_width_header_becomes_its_own_region(self):
        with pdfplumber.open(FIXTURES / "resume_two_column_header.pdf") as pdf:
            page = pdf.pages[0]
            boxes = detect_reading_order(page)
        assert boxes is not None
        # header, left, right, footer
        assert len(boxes) == 4
        assert boxes[0][2] == pytest.approx(float(page.width))
        assert boxes[-1][2] == pytest.approx(float(page.width))

    def test_regions_tile_the_page_vertically(self):
        """Bands are cut through the middle of the gaps between them, and the first
        and last reach the page edges, so every character lands in exactly one
        region: nothing can be dropped and nothing can be read twice.

        The edges are read off `page.bbox`, not off `page.height`. The two agree on
        every page that starts at the origin, which is exactly why measuring the
        wrong one went unnoticed until a page turned up that does not."""
        with pdfplumber.open(FIXTURES / "resume_two_column_header.pdf") as pdf:
            page = pdf.pages[0]
            boxes = detect_reading_order(page)
        assert boxes is not None
        tops = sorted({(box[1], box[3]) for box in boxes})
        assert tops[0][0] == pytest.approx(float(page.bbox[1]))
        assert tops[-1][1] == pytest.approx(float(page.bbox[3]))
        for upper, lower in pairwise(tops):
            assert upper[1] == pytest.approx(lower[0])


class TestAPageWhoseBoxDoesNotStartAtTheOrigin:
    """The shape a real resume had on 2026-08-22 and no fixture here did.

    A design tool exports a bleed box, so the page runs from -7.83 to 834.06 instead
    of from 0 to 841.89. The height is unchanged and nothing else in the stack
    notices. Column detection built its crop boxes out of the page's *lengths*, so
    the last band ended 7.83pt below the bottom of the page, `crop` refused it, and
    `parse_pdf` turned that into `CorruptDocumentError` — the terminal `failed`
    status, not the retryable one — for a document that reads perfectly well.

    Two columns are what makes it fire, which is to say: the most common shape of
    real resume there is.
    """

    FIXTURE = "resume_two_column_shifted_box.pdf"

    def test_the_fixture_still_has_a_shifted_box(self):
        """Pinned, because the bug is invisible without it. A regenerated fixture
        that quietly went back to starting at the origin would leave every test
        below passing against a page that cannot fail."""
        with pdfplumber.open(FIXTURES / self.FIXTURE) as pdf:
            page = pdf.pages[0]
            assert float(page.bbox[1]) < 0.0
            assert float(page.bbox[3]) == pytest.approx(float(page.height) + float(page.bbox[1]))

    def test_every_region_stays_inside_the_page(self):
        """What `crop` checks, checked here where the numbers are visible."""
        with pdfplumber.open(FIXTURES / self.FIXTURE) as pdf:
            page = pdf.pages[0]
            boxes = detect_reading_order(page)
            assert boxes is not None
            for box in boxes:
                assert box[0] >= float(page.bbox[0])
                assert box[1] >= float(page.bbox[1])
                assert box[2] <= float(page.bbox[2])
                assert box[3] <= float(page.bbox[3])
                page.crop(box)

    def test_the_document_parses_and_reads_in_column_order(self):
        """The regression itself: this raised `CorruptDocumentError` before the fix.

        The assertion is the last line of the left column against the first line of
        the right one — the pair that interleaving puts the wrong way round."""
        document = parse_pdf(FIXTURES / self.FIXTURE)
        assert document.text.index("dbt, BigQuery") < document.text.index("Andaman Analytics")
        assert document.pages_without_text == ()


class TestABoxThatCannotBeTrusted:
    """A box is clamped to the page, and a page that clamps away keeps its text.

    `_within` is the guard behind the arithmetic rather than instead of it: the
    edges are floats read out of a PDF, and a boundary computed to land exactly on
    one can miss it by a rounding step. Failing that must cost the page its columns,
    never its text.
    """

    EDGES = _Edges(left=0.0, top=-7.83, right=595.0, bottom=834.0)

    def test_a_box_hanging_off_the_page_is_pulled_back(self):
        clamped = _within([(0.0, -8.0, 595.0, 841.89)], self.EDGES)
        assert clamped == ((0.0, -7.83, 595.0, 834.0),)

    def test_a_box_with_nothing_left_declines_the_whole_page(self):
        """`None`, not a shorter list: dropping one region would drop the characters
        in it, and this module's one promise is that a page it cannot handle is read
        the way it always was."""
        off_the_page = (700.0, 100.0, 800.0, 200.0)
        assert _within([(0.0, 100.0, 595.0, 200.0), off_the_page], self.EDGES) is None


class TestGutterGuards:
    """Each guard, in isolation. A guard that stops firing is a page silently
    reordered, which is the failure this module is least able to notice."""

    def test_a_clear_gutter_is_found(self):
        words = _row((50, 150), (300, 450), top=100) + _row((50, 140), (300, 430), top=120)
        assert _gutter(words, page_width=PAGE_WIDTH) == (150, 300)

    def test_a_narrow_gap_is_word_spacing_not_a_gutter(self):
        """Under 4% of the page width — the space between two words, not a column."""
        words = _row((50, 150), (165, 450), top=100) + _row((50, 150), (165, 450), top=120)
        assert _gutter(words, page_width=PAGE_WIDTH) is None

    def test_a_lopsided_split_is_not_two_columns(self):
        """One stray word past a wide gap — a page number, not a column."""
        words = (
            _row((50, 200), top=100)
            + _row((50, 210), top=120)
            + _row((50, 205), top=140)
            + _row((50, 195), top=160)
            + _row((50, 200), top=180)
            + _row((500, 540), top=200)
        )
        assert _gutter(words, page_width=PAGE_WIDTH) is None

    def test_a_gap_wider_than_the_text_beside_it_is_not_a_gutter(self):
        """The sparse right-aligned-dates shape: the right side is 40pt of text with
        250pt of whitespace beside it. A gutter is a gap *between* two blocks and is
        narrower than either of them."""
        words = (
            _row((50, 200), (500, 540), top=100)
            + _row((50, 190), top=120)
            + _row((50, 195), (500, 545), top=140)
            + _row((50, 200), top=160)
        )
        assert _gutter(words, page_width=PAGE_WIDTH) is None

    def test_two_real_columns_survive_all_the_guards(self):
        """The same shape as the previous test but with a real right column: the
        guards must not be so strict that they refuse the case they exist for."""
        words = (
            _row((50, 200), (330, 540), top=100)
            + _row((50, 190), (330, 520), top=120)
            + _row((50, 195), (330, 545), top=140)
            + _row((50, 200), (330, 530), top=160)
        )
        assert _gutter(words, page_width=PAGE_WIDTH) == (200, 330)


class TestBandMerging:
    def test_bands_sharing_a_gutter_are_joined(self):
        """A blank line that happens to fall at the same height in both columns must
        not split the body: left, right, left, right would put the bottom of the
        left column after the top of the right one."""
        bands = [
            _Band(top=0, bottom=100, gutter=(150, 300)),
            _Band(top=100, bottom=200, gutter=(155, 295)),
        ]
        merged = _merge_columned_bands(bands)
        assert len(merged) == 1
        assert merged[0].bottom == 200
        assert merged[0].gutter == (155, 295)

    def test_bands_with_different_gutters_stay_separate(self):
        bands = [
            _Band(top=0, bottom=100, gutter=(100, 200)),
            _Band(top=100, bottom=200, gutter=(350, 450)),
        ]
        assert len(_merge_columned_bands(bands)) == 2

    def test_a_full_width_band_separates_two_columned_ones(self):
        bands = [
            _Band(top=0, bottom=100, gutter=(150, 300)),
            _Band(top=100, bottom=140, gutter=None),
            _Band(top=140, bottom=200, gutter=(150, 300)),
        ]
        assert len(_merge_columned_bands(bands)) == 3
