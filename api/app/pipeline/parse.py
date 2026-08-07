"""Turn an uploaded document into text with stable character offsets.

Two things make this more than a wrapper around `extract_text()`:

1.  Offsets are the contract the rest of the system depends on. `ParsedDocument.text`
    is the single coordinate space that evidence spans point into, and page
    boundaries are recorded so a span can be mapped back to a page for the UI.
2.  Text is NFC-normalized per page *before* joining. Normalizing later would shift
    every offset computed before it, which silently corrupts Thai combining marks.

A page with no text layer is handed to OCR when an engine is supplied, and the
recognized text is substituted into the page list *before* spans are measured — so
a rescued page is indistinguishable from a normal one to everything downstream.
Without an engine the page is reported rather than quietly yielding an empty
document.
"""

from __future__ import annotations

import io
import logging
import unicodedata
from bisect import bisect_right
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pdfplumber

from app.pipeline.ocr import OCREngine, OCRError, OCRUnavailableError

# Resumes are PII: log page numbers and error types, never text.
logger = logging.getLogger(__name__)

# A page with fewer than this many non-whitespace characters is treated as having
# no text layer. Scanned pages usually extract to nothing at all, but a stray
# ligature or page number can leak through.
MIN_CHARS_PER_TEXT_PAGE = 20

PAGE_SEPARATOR = "\n\n"


def _needs_ocr(text: str) -> bool:
    """Whether a page yielded too little text to count as having a text layer.

    One rule, used both to pick the pages OCR should run on and to decide what
    `pages_without_text` reports afterwards — so the two can never disagree.
    """
    return len(text.strip()) < MIN_CHARS_PER_TEXT_PAGE


class ParseError(Exception):
    """Base class for document parsing failures."""


class UnsupportedFileTypeError(ParseError):
    def __init__(self, suffix: str) -> None:
        super().__init__(f"Unsupported file type: {suffix or '(no extension)'}")
        self.suffix = suffix


class CorruptDocumentError(ParseError):
    """The file could not be opened as the type its extension claims."""


class NoTextLayerError(ParseError):
    """Every page is an image, and OCR either was not available or found nothing."""

    def __init__(self, page_count: int, *, ocr_attempted: bool = False) -> None:
        if ocr_attempted:
            detail = "OCR ran but recognized no usable text; the scan may be too low quality."
        else:
            detail = "It is a scan and requires OCR, which is not enabled."
        super().__init__(
            f"Document has no text layer on any of its {page_count} page(s) but does "
            f"contain images. {detail}"
        )
        self.page_count = page_count
        self.ocr_attempted = ocr_attempted


class EmptyDocumentError(ParseError):
    """No text and no images. Distinct from a scan on purpose.

    A scan is recoverable by OCR; a blank document is not. Collapsing the two would
    send blank pages through the OCR path in M2 and report a misleading reason to
    the user.
    """

    def __init__(self, page_count: int) -> None:
        super().__init__(
            f"Document has no text and no images across its {page_count} page(s); "
            "it appears to be blank."
        )
        self.page_count = page_count


@dataclass(frozen=True, slots=True)
class PageSpan:
    """Where one page's text sits inside `ParsedDocument.text`."""

    page_number: int
    """1-indexed, matching what a person sees in a PDF viewer."""

    char_start: int
    char_end: int

    @property
    def is_empty(self) -> bool:
        return self.char_end <= self.char_start


@dataclass(frozen=True, slots=True)
class ParsedDocument:
    text: str
    """NFC-normalized full text. The coordinate space for all evidence offsets."""

    pages: tuple[PageSpan, ...]
    pages_without_text: tuple[int, ...]
    """1-indexed pages that *still* yielded no usable text, after OCR if it ran.

    Kept as the honest work list: a page OCR rescued is not in here, because it has
    text now."""

    pages_from_ocr: tuple[int, ...] = ()
    """1-indexed pages whose text was recognized from an image rather than read
    from a text layer. Surfaced to the user, because a citation into one of these
    is faithful to what was read, not necessarily to what was printed."""

    # Page start offsets, precomputed for O(log n) lookup: a resume yields dozens of
    # spans to map and page_for_offset runs on each one.
    _page_starts: tuple[int, ...] = field(init=False, repr=False, compare=False, default=())

    def __post_init__(self) -> None:
        object.__setattr__(self, "_page_starts", tuple(p.char_start for p in self.pages))

    @property
    def page_count(self) -> int:
        return len(self.pages)

    @property
    def is_partially_scanned(self) -> bool:
        """Some pages had text and some did not — worth surfacing to the user."""
        return bool(self.pages_without_text) and len(self.pages_without_text) < self.page_count

    @property
    def used_ocr(self) -> bool:
        return bool(self.pages_from_ocr)

    def page_for_offset(self, offset: int) -> int:
        """Return the 1-indexed page containing `offset`.

        Offsets outside the text clamp to the first or last page rather than
        raising: a citation should never fail to render because of an off-by-one.
        """
        if not self.pages:
            return 1
        index = bisect_right(self._page_starts, offset) - 1
        return self.pages[max(index, 0)].page_number


def parse_document(path: Path, *, ocr: OCREngine | None = None) -> ParsedDocument:
    """Parse a document by file extension.

    DOCX arrives in M2; the dispatcher exists now so callers do not have to change.
    """
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return parse_pdf(path, ocr=ocr)
    raise UnsupportedFileTypeError(suffix)


def parse_document_bytes(
    data: bytes, *, filename: str, ocr: OCREngine | None = None
) -> ParsedDocument:
    """Parse an in-memory upload, dispatching on the filename's extension.

    Uploads arrive as bytes; going via a temp file would add I/O and a cleanup
    path for no benefit.
    """
    suffix = Path(filename).suffix.lower()
    if suffix == ".pdf":
        return parse_pdf(io.BytesIO(data), ocr=ocr)
    raise UnsupportedFileTypeError(suffix)


def parse_pdf(source: Path | io.BytesIO, *, ocr: OCREngine | None = None) -> ParsedDocument:
    """Read a PDF, optionally recovering text-less pages with OCR.

    `ocr=None` means OCR is off, which is deliberately not the same as an engine
    that ran and found nothing — the second is an answer about the document.
    """
    try:
        with pdfplumber.open(source) as pdf:
            raw_pages: list[str] = []
            # Whether a text-less page carries an image decides if OCR can rescue
            # it. Tracked per page so a blank page is never rendered and paid for.
            page_has_images: list[bool] = []
            for page in pdf.pages:
                raw_pages.append(page.extract_text() or "")
                page_has_images.append(bool(page.images))

            from_ocr: tuple[int, ...] = ()
            if ocr is not None:
                from_ocr = _recover_pages_with_ocr(pdf.pages, raw_pages, page_has_images, ocr)
    except (ParseError, OCRError):
        # An OCR fault is about the engine, not the document: letting it become a
        # CorruptDocumentError below would mark a fixable misconfiguration as a
        # permanently broken file.
        raise
    except Exception as exc:  # pdfplumber/pdfminer raise a wide variety of types
        raise CorruptDocumentError(f"Could not read PDF: {exc}") from exc

    return _assemble(
        raw_pages,
        has_images=any(page_has_images),
        pages_from_ocr=from_ocr,
        ocr_attempted=ocr is not None,
    )


def _recover_pages_with_ocr(
    pages: list[Any],
    raw_pages: list[str],
    page_has_images: list[bool],
    ocr: OCREngine,
) -> tuple[int, ...]:
    """Fill text-less pages from OCR, **editing `raw_pages` in place**.

    Returns the 1-indexed pages that OCR actually rescued. A page is only replaced
    when the recognized text clears the same bar a text layer has to clear, so a
    handful of noise characters never enters `document_text` — it would be text
    nobody wrote, in a system whose whole job is quoting text somebody did.
    """
    recovered: list[int] = []
    budget = ocr.max_pages

    for index, (raw, has_image) in enumerate(zip(raw_pages, page_has_images, strict=True)):
        page_number = index + 1
        if not _needs_ocr(raw) or not has_image:
            continue
        if budget <= 0:
            logger.warning(
                "ocr: page %d skipped, past the %d-page budget", page_number, ocr.max_pages
            )
            continue

        budget -= 1
        try:
            image = pages[index].to_image(resolution=ocr.dpi).original
            recognized = ocr.recognize(image, page_number=page_number)
        except OCRUnavailableError:
            # The engine itself is broken, so the next page would fail identically.
            raise
        except OCRError as exc:
            # One page failing should not cost the pages that worked; it simply
            # stays reported as having no text.
            logger.warning("ocr: page %d failed (%s)", page_number, type(exc).__name__)
            continue

        if _needs_ocr(recognized):
            logger.info("ocr: page %d yielded no usable text", page_number)
            continue

        raw_pages[index] = recognized
        recovered.append(page_number)

    return tuple(recovered)


def _assemble(
    raw_pages: list[str],
    *,
    has_images: bool = False,
    pages_from_ocr: tuple[int, ...] = (),
    ocr_attempted: bool = False,
) -> ParsedDocument:
    """Join per-page text into one offset space, tracking page boundaries."""
    chunks: list[str] = []
    pages: list[PageSpan] = []
    without_text: list[int] = []
    cursor = 0

    for index, raw in enumerate(raw_pages, start=1):
        # Normalize before measuring — see module docstring. U+0000 is stripped
        # here too: a broken ToUnicode map makes extractors emit NUL for glyphs
        # they cannot name, and Postgres refuses NUL in text columns. Removing
        # characters before the spans are measured shifts no offsets. OCR text
        # arrives here as well, so it is held to exactly the same contract.
        page_text = unicodedata.normalize("NFC", raw).replace("\x00", "")

        if _needs_ocr(page_text):
            without_text.append(index)

        if chunks:
            chunks.append(PAGE_SEPARATOR)
            cursor += len(PAGE_SEPARATOR)

        start = cursor
        chunks.append(page_text)
        cursor += len(page_text)
        pages.append(PageSpan(page_number=index, char_start=start, char_end=cursor))

    if raw_pages and len(without_text) == len(raw_pages):
        if has_images:
            raise NoTextLayerError(page_count=len(raw_pages), ocr_attempted=ocr_attempted)
        raise EmptyDocumentError(page_count=len(raw_pages))

    return ParsedDocument(
        text="".join(chunks),
        pages=tuple(pages),
        pages_without_text=tuple(without_text),
        pages_from_ocr=pages_from_ocr,
    )
