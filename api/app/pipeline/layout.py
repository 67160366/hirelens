"""Work out what order a page should be read in.

`pdfplumber.Page.extract_text()` reads a page in visual order: it walks characters
top to bottom and, within a line, left to right. On a single-column page that is the
reading order. On a two-column page it is not — it interleaves the columns, so a job
title from the right column lands next to contact details from the left.

Nothing is *lost* that way, and no citation is untrue: the quote really is in the
document. What breaks is **adjacency**, and adjacency is most of what an extractor
uses to decide which company a role belongs to. The fix is to hand pdfplumber one
column at a time instead of the whole page.

The one property this module must preserve is that **a page it does not understand
comes back untouched**. `detect_reading_order` returns `None` for anything that is
not clearly multi-column, and `parse.py` then calls `extract_text()` exactly as it
always did — so every document that parsed correctly yesterday produces byte-identical
text today, and no stored citation can shift. Every guard below exists to make `None`
the answer whenever there is doubt.

The algorithm is a bounded XY-cut, the classic page-segmentation move:

1.  **Cut horizontally first.** Words are grouped into rows, and a vertical gap
    noticeably larger than a line height splits the page into bands. This is what
    separates a full-width header or footer from the body — and it has to come
    first, because a spanning header line fills the gutter and hides it from any
    profile taken over the whole page.
2.  **Then cut vertically, inside each band.** A band whose words leave a wide
    empty column has two columns; a band whose words do not, has one.
3.  **Re-merge adjacent two-column bands** that share a gutter, so a blank line that
    happens to fall at the same height in both columns does not turn one two-column
    block into two — which would read left, right, left, right instead of the whole
    left column and then the whole right.

Text is then extracted by *cropping* to each region and letting pdfplumber assemble
it as usual, rather than by rebuilding lines from word boxes. Reassembling text by
hand would mean re-deciding where spaces go, and Thai has no spaces between words:
the reassembled version of a Thai line is not the same string, and every evidence
offset points into whatever string we produce.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from itertools import pairwise
from typing import Any

from app.pipeline.geometry import CharRun, runs_for, shift

BBox = tuple[float, float, float, float]
"""(x0, top, x1, bottom), the argument `pdfplumber.Page.crop` takes."""

# Below this many words a page is a cover sheet or a fragment; the statistics that
# follow would be describing noise.
MIN_WORDS = 10

# Words whose tops differ by less than this are the same row. Generous enough to
# survive mixed font sizes on one line, tight enough not to merge adjacent lines.
ROW_TOLERANCE = 3.0

# A vertical gap this many times the median row height starts a new band. Ordinary
# line spacing is well under 1.5; the space under a header is well over it.
BAND_GAP_FACTOR = 1.5

# A gutter must be at least this fraction of the page width. On A4 that is ~24pt —
# far wider than the space between two words, far narrower than a real column gap.
MIN_GUTTER_FRACTION = 0.04

# Each side of a gutter must hold at least this share of the band's words. This is
# what stops a page number or one indented block from being read as a second column:
# they are wide-set, but they are tiny.
MIN_SIDE_SHARE = 0.15

# Each side must also be at least this wide relative to the gutter. A real gutter is
# a *gap between* two blocks of text and is narrower than either of them; a strip of
# whitespace wider than the writing beside it is a sparse page, not a second column.
# This is what refuses a resume with its dates right-aligned at the margin, where
# everything between the body and the dates is empty.
MIN_SIDE_WIDTH_PER_GUTTER = 0.5


@dataclass(frozen=True, slots=True)
class _Word:
    """The only four numbers this module needs out of a pdfplumber word."""

    x0: float
    x1: float
    top: float
    bottom: float


@dataclass(slots=True)
class _Band:
    """A horizontal slice of the page, and the gutter in it if it has one."""

    top: float
    bottom: float
    gutter: tuple[float, float] | None


def detect_reading_order(page: Any) -> tuple[BBox, ...] | None:
    """Return crop boxes in reading order, or `None` to leave the page alone.

    `None` means "read this page the way you always have" and is deliberately the
    common answer: it is returned for every single-column page, every page with too
    few words to judge, and every page whose columns fail any of the guards above.
    """
    words = _words_of(page)
    if len(words) < MIN_WORDS:
        return None

    page_width = float(page.width)
    page_height = float(page.height)

    bands = _bands(words, page_height=page_height, page_width=page_width)
    if not any(band.gutter for band in bands):
        return None

    boxes: list[BBox] = []
    for band in _merge_columned_bands(bands):
        if band.gutter is None:
            boxes.append((0.0, band.top, page_width, band.bottom))
        else:
            # Cut at the middle of the gutter rather than at its edges. `crop` keeps
            # anything that *overlaps* the box, so a boundary drawn through a glyph
            # would put that glyph in both columns; the middle of a gutter has no
            # glyph in it by construction.
            middle = (band.gutter[0] + band.gutter[1]) / 2
            boxes.append((0.0, band.top, middle, band.bottom))
            boxes.append((middle, band.top, page_width, band.bottom))
    return tuple(boxes)


def extract_in_reading_order(
    page: Any, boxes: tuple[BBox, ...]
) -> tuple[str, tuple[CharRun, ...] | None]:
    """Extract each region with pdfplumber and join them in order.

    Returns the text and, beside it, where each of its characters sits on the page
    (M5 slice 3). The geometry is accumulated *as the text is joined*, so a run's
    offsets index into the string this function returns rather than into the region
    it came from — the reordering that makes this page's text differ from the PDF's
    internal order is exactly why it cannot be recovered afterwards.

    Geometry is `None` if any region's could not be trusted. All-or-nothing per page,
    because a half-covered page would render as a highlight that silently stops.
    """
    parts: list[str] = []
    runs: list[CharRun] = []
    geometry_ok = True
    cursor = 0

    for box in boxes:
        region = page.crop(box)
        text: str = region.extract_text() or ""
        if not text.strip():
            # Dropped from the join, so it contributes no characters and no offsets.
            continue

        if geometry_ok:
            region_runs = runs_for(region, text)
            if region_runs is None:
                geometry_ok = False
            else:
                runs.extend(shift(region_runs, cursor))

        parts.append(text)
        cursor += len(text) + len(_REGION_SEPARATOR)

    return _REGION_SEPARATOR.join(parts), (tuple(runs) if geometry_ok else None)


_REGION_SEPARATOR = "\n"
"""What the regions are joined with. Named because the geometry offsets above have
to advance by exactly its length, and a bare "\\n" in two places is how those two
drift apart."""


def _words_of(page: Any) -> list[_Word]:
    return [
        _Word(
            x0=float(word["x0"]),
            x1=float(word["x1"]),
            top=float(word["top"]),
            bottom=float(word["bottom"]),
        )
        for word in page.extract_words()
    ]


def _rows(words: list[_Word]) -> list[list[_Word]]:
    """Group words into rows by their top edge.

    A row spans the whole page: on a two-column page it holds a line from the left
    column *and* the line beside it on the right. That is exactly the interleaving
    this module exists to undo, and it is also why the vertical cut cannot be made
    from rows — only from the words inside a band.
    """
    rows: list[list[_Word]] = []
    for word in sorted(words, key=lambda w: (w.top, w.x0)):
        if rows and word.top - rows[-1][0].top <= ROW_TOLERANCE:
            rows[-1].append(word)
        else:
            rows.append([word])
    return rows


def _bands(words: list[_Word], *, page_height: float, page_width: float) -> list[_Band]:
    """Split the page at wide horizontal gaps and look for a gutter in each slice.

    Boundaries are drawn through the *middle* of each gap, and the first and last
    band run to the page edges, so every character on the page falls inside exactly
    one band. Nothing can be dropped, and nothing can be read twice.
    """
    rows = _rows(words)
    threshold = BAND_GAP_FACTOR * statistics.median(
        max(word.bottom for word in row) - min(word.top for word in row) for row in rows
    )

    groups: list[list[list[_Word]]] = [[rows[0]]]
    for previous, row in pairwise(rows):
        gap = min(word.top for word in row) - max(word.bottom for word in previous)
        if gap >= threshold:
            groups.append([row])
        else:
            groups[-1].append(row)

    bands: list[_Band] = []
    for index, group in enumerate(groups):
        band_words = [word for row in group for word in row]
        top = 0.0
        if index > 0:
            above = [word for row in groups[index - 1] for word in row]
            top = (max(word.bottom for word in above) + min(w.top for w in band_words)) / 2
        bottom = page_height
        if index + 1 < len(groups):
            below = [word for row in groups[index + 1] for word in row]
            bottom = (max(w.bottom for w in band_words) + min(word.top for word in below)) / 2
        bands.append(
            _Band(top=top, bottom=bottom, gutter=_gutter(band_words, page_width=page_width))
        )
    return bands


def _gutter(words: list[_Word], *, page_width: float) -> tuple[float, float] | None:
    """The widest empty vertical strip that looks like a column gap, if there is one."""
    spans = sorted((word.x0, word.x1) for word in words)
    merged: list[list[float]] = []
    for x0, x1 in spans:
        if merged and x0 <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], x1)
        else:
            merged.append([x0, x1])
    if len(merged) < 2:
        return None

    left, right = max(pairwise(merged), key=lambda pair: pair[1][0] - pair[0][1])
    gutter = (left[1], right[0])
    if gutter[1] - gutter[0] < MIN_GUTTER_FRACTION * page_width:
        return None

    before = [word for word in words if word.x1 <= gutter[0]]
    after = [word for word in words if word.x0 >= gutter[1]]
    if min(len(before), len(after)) < MIN_SIDE_SHARE * len(words):
        return None

    narrowest = min(
        max(word.x1 for word in before) - min(word.x0 for word in before),
        max(word.x1 for word in after) - min(word.x0 for word in after),
    )
    if narrowest < MIN_SIDE_WIDTH_PER_GUTTER * (gutter[1] - gutter[0]):
        return None
    return gutter


def _merge_columned_bands(bands: list[_Band]) -> list[_Band]:
    """Join consecutive two-column bands whose gutters overlap.

    Without this, a blank line that happens to fall at the same height in both
    columns splits the body in two, and the page reads left, right, left, right —
    which puts the bottom of the left column after the top of the right one, the
    very thing the module is fixing.
    """
    merged: list[_Band] = []
    for band in bands:
        previous = merged[-1] if merged else None
        if (
            previous is not None
            and previous.gutter is not None
            and band.gutter is not None
            and band.gutter[0] < previous.gutter[1]
            and previous.gutter[0] < band.gutter[1]
        ):
            previous.bottom = band.bottom
            previous.gutter = (
                max(previous.gutter[0], band.gutter[0]),
                min(previous.gutter[1], band.gutter[1]),
            )
        else:
            merged.append(_Band(top=band.top, bottom=band.bottom, gutter=band.gutter))
    return merged
