"""Where each character sits on the page it was read from (M5 slice 3).

The overlay in slice 4 has to draw a box around a character range, and nothing in
the system could say where on a page a character range sits: `PageSpan` carries
`page_number`/`char_start`/`char_end` and `EvidenceRef` carries
`char_start`/`char_end`/`page`. This module measures that, in the same pass that
measures the offsets, because anything running *after* offsets are fixed cannot
shift them — the same placement rule as the NUL strip and the OCR substitution.

**Nothing here searches for text.** The obvious implementation locates a word in the
page string with `find()`, and it is wrong three ways, each measured on this repo's
own fixtures rather than argued:

- 8 of the 11 words in `resume_broken_tounicode.pdf` contain a literal `\\x00`, so
  `find()` locates 3 of them — on the fixture that exists to pin the NUL strip.
- `find()` returns the *first* occurrence, and 105 of the 120 words in
  `resume_multipage.pdf` occur more than once. A highlight would look right and sit
  on the wrong line.
- A two-column page is assembled in *reading* order, which is not the PDF's internal
  order: walking `resume_two_column.pdf`'s words in visual order gives 11 offset
  inversions.

So the mapping is built **by construction** instead. pdfplumber's textmap emits one
`(character, source_char)` pair per character of the extracted string, in order, and
`to_string()` reproduces `extract_text()` exactly. Walking it therefore yields a char
range and a box together, with no matching step that could be wrong.

**The consistency check is the load-bearing part.** `runs_for` compares the textmap's
own string against the text the caller actually kept, and answers `None` if they
differ by so much as a character. `None` means "this page has no geometry" and is a
supported, rendered state — slice 4 falls back to the text pane and says why. That is
deliberately the same shape as `layout.detect_reading_order` answering `None` and
`OCR_MIN_CONFIDENCE` refusing a page it read badly: **a wrong box is a visual claim
nobody can check, and this project refuses those in preference to admitting it does
not know.**

### Why characters rather than words

`docs/PLAN.md` scoped this as *per-word* boxes. That is wrong for the language this
project cares most about: Thai has no spaces between words, so a whitespace-delimited
"word" in `resume_th.pdf` is the unbroken 31-character run
`ดูแลระบบกระทบยอดการชำระเงินด้วย` — and real quotes such as `ชำระเงิน` sit *inside*
it. Word boxes would highlight the whole run for a quote covering a quarter of it.
This is the same measurement that made `pipeline/retrieval.py` tokenize Thai by
character n-gram rather than by whitespace.

Characters are grouped into **runs** — consecutive characters sharing a line — so the
common case stays compact: a space carries no glyph, so Latin text breaks into runs at
word boundaries on its own. Measured across every readable fixture it costs about
**20 bytes per character** (`resume_multipage.pdf`: 723 characters, 120 runs, 15 KB).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

# PDF user-space units. Two decimals is far below a device pixel at any sane zoom,
# and rounding here rather than at render time keeps the stored JSON from carrying
# seventeen meaningless digits per coordinate.
_PRECISION = 2


@dataclass(frozen=True, slots=True)
class CharRun:
    """Consecutive characters that share a line, with a box for each one.

    `top`/`bottom` are shared because every character in a run has them by
    definition, which is most of why this is cheaper than a box per character.
    """

    char_start: int
    top: float
    bottom: float

    x: tuple[tuple[float, float], ...]
    """`(x0, x1)` per character, in order, starting at `char_start`."""

    @property
    def char_end(self) -> int:
        return self.char_start + len(self.x)


@dataclass(frozen=True, slots=True)
class PageGeometry:
    """One page's characters, and the page box they are measured against.

    `width`/`height` travel with the runs because a client scaling PDF user space
    onto a canvas needs them, and asking the PDF for them again at render time is a
    second source of truth for something already known here.
    """

    page_number: int
    width: float
    height: float
    runs: tuple[CharRun, ...]


def runs_for(container: Any, expected_text: str) -> tuple[CharRun, ...] | None:
    """Character boxes for `container`, or `None` if they cannot be trusted.

    `container` is a pdfplumber `Page` or the `CroppedPage` a column extraction
    produces; both expose the same textmap.

    Returns `None` — meaning "no geometry for this page" — when the textmap's string
    is not exactly the text the caller kept, and when pdfplumber raises. Both are
    states the overlay renders as a fallback rather than states that fail a parse: a
    document must still be readable when only its geometry is unavailable.
    """
    if not expected_text:
        return ()

    try:
        textmap = container._get_textmap()
        tuples = textmap.tuples
        if textmap.to_string() != expected_text:
            return None
    except Exception:
        # pdfplumber and pdfminer raise a wide variety of types, and `_get_textmap`
        # is underscore-private — a version that renames it must cost the overlay,
        # never the parse. Everything downstream of text extraction keeps working.
        return None

    # Built as plain mutable tuples and frozen once at the end: `CharRun` is
    # immutable, and growing one character at a time would rebuild a tuple per
    # character.
    building: list[tuple[int, float, float, list[tuple[float, float]]]] = []

    for index, (_char, source) in enumerate(tuples):
        if source is None:
            # An inserted separator — a space between words, a newline between
            # lines. It occupies a character position and carries no ink, so it
            # belongs to no run.
            #
            # Skipping it is all that is needed: it advances `index` without growing
            # the open run, so the contiguity test below fails on the next character
            # and a new run starts. An explicit reset here was tried and **mutation
            # testing proved it could not fail**, which in this repo is the signal to
            # delete it rather than keep a line that only looks careful. This is also
            # what makes Latin text break into one run per word for free.
            continue

        char_top = round(float(source["top"]), _PRECISION)
        char_bottom = round(float(source["bottom"]), _PRECISION)
        box = (
            round(float(source["x0"]), _PRECISION),
            round(float(source["x1"]), _PRECISION),
        )

        if building:
            start, top, bottom, boxes = building[-1]
            # Same line, and no character position skipped since the run started.
            if top == char_top and bottom == char_bottom and start + len(boxes) == index:
                boxes.append(box)
                continue

        building.append((index, char_top, char_bottom, [box]))

    return tuple(
        CharRun(char_start=start, top=top, bottom=bottom, x=tuple(boxes))
        for start, top, bottom, boxes in building
    )


def shift(runs: Iterable[CharRun], delta: int) -> tuple[CharRun, ...]:
    """Move every run by `delta` characters, for rebasing into a wider coordinate space."""
    return tuple(
        CharRun(char_start=run.char_start + delta, top=run.top, bottom=run.bottom, x=run.x)
        for run in runs
    )


def remap(runs: Iterable[CharRun], positions: Sequence[int | None]) -> tuple[CharRun, ...]:
    """Rewrite runs after characters were removed from the text they index into.

    `positions[old_index]` is the character's new index, or `None` if it was
    removed. A run whose middle loses a character **splits**, because the surviving
    halves are no longer contiguous and one run spanning the gap would claim a
    character range it does not cover.

    This is what the NUL strip needs: a broken ToUnicode map makes an extractor emit
    `\\x00` for glyphs it cannot name, and `resume_broken_tounicode.pdf` carries 11 of
    them — enough to shift later characters by up to 11 positions.
    """
    out: list[CharRun] = []

    for run in runs:
        pending: list[tuple[float, float]] = []
        pending_start: int | None = None
        previous: int | None = None

        for offset, box in enumerate(run.x):
            old = run.char_start + offset
            new = positions[old] if old < len(positions) else None

            if new is None:
                _flush(out, run, pending_start, pending)
                pending, pending_start, previous = [], None, None
                continue

            if previous is not None and new != previous + 1:
                _flush(out, run, pending_start, pending)
                pending, pending_start = [], None

            if pending_start is None:
                pending_start = new
            pending.append(box)
            previous = new

        _flush(out, run, pending_start, pending)

    return tuple(out)


def _flush(
    out: list[CharRun],
    run: CharRun,
    start: int | None,
    boxes: list[tuple[float, float]],
) -> None:
    if start is None or not boxes:
        return
    out.append(CharRun(char_start=start, top=run.top, bottom=run.bottom, x=tuple(boxes)))


def stored(pages: Iterable[PageGeometry]) -> list[dict[str, Any]]:
    """The shape `resumes.page_geometry` holds.

    Written out field by field, and kept beside `from_stored` because the two are the
    halves of one round-trip — the same pairing `stored_page_spans` has. The
    per-character boxes stay a flat list of pairs rather than named keys: there is one
    per character rather than one per page, and `{"x0": …, "x1": …}` would roughly
    double a figure already measured at ~20 bytes per character.
    """
    return [
        {
            "page_number": page.page_number,
            "width": page.width,
            "height": page.height,
            "runs": [
                {
                    "char_start": run.char_start,
                    "top": run.top,
                    "bottom": run.bottom,
                    "x": [list(box) for box in run.x],
                }
                for run in page.runs
            ],
        }
        for page in pages
    ]


def from_stored(pages: list[dict[str, Any]] | None) -> tuple[PageGeometry, ...]:
    """Rebuild geometry from a stored row. `None` is a row written before migration `0010`."""
    return tuple(
        PageGeometry(
            page_number=int(page["page_number"]),
            width=float(page["width"]),
            height=float(page["height"]),
            runs=tuple(
                CharRun(
                    char_start=int(run["char_start"]),
                    top=float(run["top"]),
                    bottom=float(run["bottom"]),
                    x=tuple((float(box[0]), float(box[1])) for box in run["x"]),
                )
                for run in page["runs"]
            ),
        )
        for page in pages or ()
    )
