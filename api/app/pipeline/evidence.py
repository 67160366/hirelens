"""Resolve LLM-supplied quotes to verbatim spans in the source document.

The core invariant of this system: every claim the model makes must point at real
text in the source document. We enforce it by never letting the model report
character offsets itself — models cannot count characters reliably. The model
returns only a `quote`, and this module locates it.

A quote that cannot be located is a hallucination. Counting those gives us a
hallucination rate for free, with no labelled dataset required.

Source text is expected to be NFC-normalized already (the parser guarantees
this), so offset maps here only ever deal with whitespace differences.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from enum import StrEnum

# A quote shorter than this is not evidence of anything — "AI" or "Go" would
# match in dozens of places and tells a reviewer nothing.
MIN_QUOTE_CHARS = 4

# Stripping whitespace entirely is the loosest tier and the easiest to match by
# accident ("go" inside "django"), so it demands a longer quote.
MIN_STRIPPED_QUOTE_CHARS = 8

_WHITESPACE_RUN = re.compile(r"\s+")


class MatchKind(StrEnum):
    """How closely the quote matched. Useful telemetry, not just bookkeeping.

    A high share of `whitespace_stripped` matches means the PDF parser is
    injecting stray spaces — a parser problem surfacing as a matching problem.
    """

    EXACT = "exact"
    WHITESPACE_COLLAPSED = "whitespace_collapsed"
    WHITESPACE_STRIPPED = "whitespace_stripped"


class RejectReason(StrEnum):
    EMPTY = "empty"
    TOO_SHORT = "too_short"
    NOT_FOUND = "not_found"


@dataclass(frozen=True, slots=True)
class ResolvedSpan:
    """A quote successfully located in the source document."""

    quote: str
    """The quote as it appears in the source, sliced from the original text."""

    char_start: int
    char_end: int
    match_kind: MatchKind
    occurrences: int
    """How many places the quote matched. >1 means the span is the first hit and
    the citation is ambiguous — surface it rather than pretending it is unique."""

    @property
    def is_ambiguous(self) -> bool:
        return self.occurrences > 1


@dataclass(frozen=True, slots=True)
class RejectedQuote:
    """A quote that could not be located — i.e. the model made it up."""

    quote: str
    reason: RejectReason


Resolution = ResolvedSpan | RejectedQuote


@dataclass(frozen=True, slots=True)
class _IndexedText:
    """A transformed copy of the source plus a map back to original offsets.

    `offsets[i]` is the index in the original text that produced `text[i]`.
    """

    text: str
    offsets: tuple[int, ...]


def _collapse_whitespace(source: str) -> _IndexedText:
    """Collapse each whitespace run to a single space, tracking origins.

    Handles the common case where a model reflows a quote that crossed a line
    break in the PDF.
    """
    chars: list[str] = []
    offsets: list[int] = []
    in_run = False

    for i, ch in enumerate(source):
        if ch.isspace():
            # Skip leading whitespace outright so offsets stay tight.
            if not in_run and chars:
                chars.append(" ")
                offsets.append(i)
            in_run = True
        else:
            chars.append(ch)
            offsets.append(i)
            in_run = False

    # Drop a trailing collapsed space.
    if chars and chars[-1] == " ":
        chars.pop()
        offsets.pop()

    return _IndexedText("".join(chars), tuple(offsets))


def _strip_whitespace(source: str) -> _IndexedText:
    """Remove whitespace entirely, tracking origins.

    Thai does not put spaces between words, and PDF text extraction frequently
    injects spurious ones mid-word. Comparing with all whitespace removed is the
    only way those quotes match at all.
    """
    chars: list[str] = []
    offsets: list[int] = []

    for i, ch in enumerate(source):
        if not ch.isspace():
            chars.append(ch)
            offsets.append(i)

    return _IndexedText("".join(chars), tuple(offsets))


def _count_occurrences(haystack: str, needle: str, limit: int = 8) -> int:
    """Count non-overlapping occurrences, stopping once `limit` is reached.

    We only need to know "one" vs "more than one"; a pathological quote like a
    single space should not cost a full scan.
    """
    count = 0
    start = 0
    while count < limit:
        found = haystack.find(needle, start)
        if found == -1:
            break
        count += 1
        start = found + len(needle)
    return count


class EvidenceResolver:
    """Locates quotes within one document.

    Build once per document and reuse: the whitespace-normalized copies and
    their offset maps are computed up front, since a single resume yields dozens
    of quotes to resolve.
    """

    __slots__ = ("_collapsed", "_source", "_stripped")

    def __init__(self, source_text: str) -> None:
        # The parser already emits NFC, but a resolver built from an arbitrary
        # string should not silently mis-map Thai combining marks.
        self._source = unicodedata.normalize("NFC", source_text)
        self._collapsed = _collapse_whitespace(self._source)
        self._stripped = _strip_whitespace(self._source)

    @property
    def source_text(self) -> str:
        return self._source

    def resolve(self, quote: str) -> Resolution:
        """Locate `quote` in the document, trying progressively looser matches."""
        normalized_quote = unicodedata.normalize("NFC", quote).strip()

        if not normalized_quote:
            return RejectedQuote(quote=quote, reason=RejectReason.EMPTY)

        if len(normalized_quote) < MIN_QUOTE_CHARS:
            return RejectedQuote(quote=quote, reason=RejectReason.TOO_SHORT)

        # Tier 1: verbatim. The overwhelming majority of good quotes land here.
        exact_start = self._source.find(normalized_quote)
        if exact_start != -1:
            return self._span(
                start=exact_start,
                end=exact_start + len(normalized_quote),
                kind=MatchKind.EXACT,
                occurrences=_count_occurrences(self._source, normalized_quote),
            )

        # Tier 2: same words, different whitespace.
        collapsed_quote = _WHITESPACE_RUN.sub(" ", normalized_quote).strip()
        resolution = self._resolve_via(
            self._collapsed, collapsed_quote, MatchKind.WHITESPACE_COLLAPSED
        )
        if resolution is not None:
            return resolution

        # Tier 3: ignore whitespace completely. Mostly rescues Thai.
        stripped_quote = _WHITESPACE_RUN.sub("", normalized_quote)
        if len(stripped_quote) >= MIN_STRIPPED_QUOTE_CHARS:
            resolution = self._resolve_via(
                self._stripped, stripped_quote, MatchKind.WHITESPACE_STRIPPED
            )
            if resolution is not None:
                return resolution

        return RejectedQuote(quote=quote, reason=RejectReason.NOT_FOUND)

    def _resolve_via(
        self, indexed: _IndexedText, needle: str, kind: MatchKind
    ) -> ResolvedSpan | None:
        if not needle:
            return None
        found = indexed.text.find(needle)
        if found == -1:
            return None
        return self._span(
            start=indexed.offsets[found],
            end=indexed.offsets[found + len(needle) - 1] + 1,
            kind=kind,
            occurrences=_count_occurrences(indexed.text, needle),
        )

    def _span(self, *, start: int, end: int, kind: MatchKind, occurrences: int) -> ResolvedSpan:
        # Return the source's own text, not the model's rendering of it. If the
        # model reflowed a line break, the citation shown to a reviewer should be
        # what the document actually says.
        return ResolvedSpan(
            quote=self._source[start:end],
            char_start=start,
            char_end=end,
            match_kind=kind,
            occurrences=occurrences,
        )
