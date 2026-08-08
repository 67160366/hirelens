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
    _gutter,
    _merge_columned_bands,
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
        region: nothing can be dropped and nothing can be read twice."""
        with pdfplumber.open(FIXTURES / "resume_two_column_header.pdf") as pdf:
            page = pdf.pages[0]
            boxes = detect_reading_order(page)
        assert boxes is not None
        tops = sorted({(box[1], box[3]) for box in boxes})
        assert tops[0][0] == 0.0
        assert tops[-1][1] == pytest.approx(float(page.height))
        for upper, lower in pairwise(tops):
            assert upper[1] == pytest.approx(lower[0])


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
