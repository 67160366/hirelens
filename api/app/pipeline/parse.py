"""Turn an uploaded document into text with stable character offsets.

Two things make this more than a wrapper around `extract_text()`:

1.  Offsets are the contract the rest of the system depends on. `ParsedDocument.text`
    is the single coordinate space that evidence spans point into, and page
    boundaries are recorded so a span can be mapped back to a page for the UI.
2.  Text is NFC-normalized per page *before* joining. Normalizing later would shift
    every offset computed before it, which silently corrupts Thai combining marks.

Scanned PDFs are detected and reported rather than quietly yielding an empty
document — OCR fallback lands in M2 and will consume `pages_without_text`.
"""

from __future__ import annotations

import io
import unicodedata
from bisect import bisect_right
from dataclasses import dataclass, field
from pathlib import Path

import pdfplumber

# A page with fewer than this many non-whitespace characters is treated as having
# no text layer. Scanned pages usually extract to nothing at all, but a stray
# ligature or page number can leak through.
MIN_CHARS_PER_TEXT_PAGE = 20

PAGE_SEPARATOR = "\n\n"


class ParseError(Exception):
    """Base class for document parsing failures."""


class UnsupportedFileTypeError(ParseError):
    def __init__(self, suffix: str) -> None:
        super().__init__(f"Unsupported file type: {suffix or '(no extension)'}")
        self.suffix = suffix


class CorruptDocumentError(ParseError):
    """The file could not be opened as the type its extension claims."""


class NoTextLayerError(ParseError):
    """Every page is an image. Needs OCR, which arrives in M2."""

    def __init__(self, page_count: int) -> None:
        super().__init__(
            f"Document has no text layer on any of its {page_count} page(s) but does "
            "contain images; it is a scan and requires OCR."
        )
        self.page_count = page_count


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
    """1-indexed pages that yielded no usable text — the OCR work list for M2."""

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

    def page_for_offset(self, offset: int) -> int:
        """Return the 1-indexed page containing `offset`.

        Offsets outside the text clamp to the first or last page rather than
        raising: a citation should never fail to render because of an off-by-one.
        """
        if not self.pages:
            return 1
        index = bisect_right(self._page_starts, offset) - 1
        return self.pages[max(index, 0)].page_number


def parse_document(path: Path) -> ParsedDocument:
    """Parse a document by file extension.

    DOCX arrives in M2; the dispatcher exists now so callers do not have to change.
    """
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return parse_pdf(path)
    raise UnsupportedFileTypeError(suffix)


def parse_document_bytes(data: bytes, *, filename: str) -> ParsedDocument:
    """Parse an in-memory upload, dispatching on the filename's extension.

    Uploads arrive as bytes; going via a temp file would add I/O and a cleanup
    path for no benefit.
    """
    suffix = Path(filename).suffix.lower()
    if suffix == ".pdf":
        return parse_pdf(io.BytesIO(data))
    raise UnsupportedFileTypeError(suffix)


def parse_pdf(source: Path | io.BytesIO) -> ParsedDocument:
    try:
        with pdfplumber.open(source) as pdf:
            raw_pages = [page.extract_text() or "" for page in pdf.pages]
            # Whether a text-less page carries an image decides if OCR can rescue it.
            has_images = any(page.images for page in pdf.pages)
    except ParseError:
        raise
    except Exception as exc:  # pdfplumber/pdfminer raise a wide variety of types
        raise CorruptDocumentError(f"Could not read PDF: {exc}") from exc

    return _assemble(raw_pages, has_images=has_images)


def _assemble(raw_pages: list[str], *, has_images: bool = False) -> ParsedDocument:
    """Join per-page text into one offset space, tracking page boundaries."""
    chunks: list[str] = []
    pages: list[PageSpan] = []
    without_text: list[int] = []
    cursor = 0

    for index, raw in enumerate(raw_pages, start=1):
        # Normalize before measuring — see module docstring.
        page_text = unicodedata.normalize("NFC", raw)

        if len(page_text.strip()) < MIN_CHARS_PER_TEXT_PAGE:
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
            raise NoTextLayerError(page_count=len(raw_pages))
        raise EmptyDocumentError(page_count=len(raw_pages))

    return ParsedDocument(
        text="".join(chunks),
        pages=tuple(pages),
        pages_without_text=tuple(without_text),
    )
