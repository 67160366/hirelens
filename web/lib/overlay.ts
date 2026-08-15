/**
 * Turning stored character geometry into boxes on a rendered PDF page (M5 slice 4).
 *
 * In `lib/` for the reason `lib/metrics.ts` and `lib/evidence.ts` are: `web/` runs
 * vitest with no DOM, so a rule expressed inside a component is a rule no test can
 * reach — and the last two slices each shipped a defect that lived exactly there.
 * Everything here is a pure function of the server's payload.
 *
 * **Nothing in this module searches for text.** `pipeline/geometry.py` measured a box
 * per character in the same pass that measured the offsets, precisely so a client
 * never has to match anything: a citation is a character range, and a range selects
 * runs. Re-deriving positions here would mean reproducing the server's NFC
 * normalization, NUL strip and two-column reading order, and the day they drifted the
 * overlay would highlight the wrong region — a visual claim nobody can check.
 *
 * The other half of that instinct is `gapForPage`: when the geometry cannot be shown
 * to describe the page being rendered, this module says so and draws **nothing**.
 * Same shape as `runs_for` answering `None`, `detect_reading_order` answering `None`,
 * and `OCR_MIN_CONFIDENCE` refusing a page it read badly.
 */

import type { EvidenceRef, GeometryReport, PageGeometry } from "@/lib/api";

/** A rectangle in PDF user space — the units the geometry was measured in. */
export interface Box {
  left: number;
  top: number;
  width: number;
  height: number;
}

/** One box, and the citation that produced it. */
export interface CitationBox {
  reference: EvidenceRef;
  page: number;
  box: Box;
}

/**
 * How far a rendered page may differ from the size it was measured at, in points.
 *
 * Small because it is guarding against a *different* page box — a rotated page or a
 * different crop — not against rounding. `geometry.py` already rounds to two
 * decimals, so anything above that is a real disagreement.
 */
const SIZE_TOLERANCE = 0.5;

/**
 * Every box a citation covers on one page.
 *
 * A run is contiguous in character space by construction, so a range that overlaps a
 * run yields exactly one box from that run, and a citation crossing a line break
 * yields one box per line. That is the whole reason the geometry stores runs of
 * characters rather than words: in `resume_th.pdf` the quote `ชำระเงิน` sits inside
 * an unbroken 31-character run, and a word box would highlight all 31.
 */
export function boxesForPage(page: PageGeometry, reference: EvidenceRef): Box[] {
  const boxes: Box[] = [];
  if (reference.char_end <= reference.char_start) return boxes;

  for (const run of page.runs) {
    const runEnd = run.char_start + run.x.length;
    const from = Math.max(reference.char_start, run.char_start);
    const to = Math.min(reference.char_end, runEnd);
    if (to <= from) continue;

    const first = run.x[from - run.char_start];
    const last = run.x[to - 1 - run.char_start];
    // Both indices are inside the run by the clamp above; the guard is what
    // `noUncheckedIndexedAccess` asks for, and a malformed payload draws nothing
    // rather than a box at NaN.
    if (!first || !last) continue;

    boxes.push({
      left: first[0],
      top: run.top,
      width: last[1] - first[0],
      height: run.bottom - run.top,
    });
  }

  return boxes;
}

/**
 * One entry per distinct span, keeping the first claim that cited it.
 *
 * Two claims regularly rest on the same quote — in `resume_th.pdf` the headline and
 * the seniority both cite characters 11–72 — and drawing a translucent box twice at
 * the same coordinates renders it **darker than its neighbours**, which reads as
 * "this line is more strongly evidenced" and is not a claim anything supports. Found
 * by driving the overlay in a browser: the arithmetic was right and the picture was
 * not, which no unit test was looking at.
 *
 * `DocumentPane` solves the same problem for the text view in `buildSegments`, where
 * it also drops *overlapping* spans because nested `<mark>` elements are unreadable.
 * Boxes have no such trouble, so only exact duplicates are collapsed here: two
 * different ranges that happen to overlap really are two regions.
 */
export function distinctSpans(references: EvidenceRef[]): EvidenceRef[] {
  const seen = new Set<string>();
  return references.filter((reference) => {
    const key = `${reference.char_start}-${reference.char_end}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

/** The same, across every page that has geometry. */
export function boxesFor(pages: PageGeometry[], references: EvidenceRef[]): CitationBox[] {
  const out: CitationBox[] = [];
  for (const page of pages) {
    for (const reference of references) {
      for (const box of boxesForPage(page, reference)) {
        out.push({ reference, page: page.page_number, box });
      }
    }
  }
  return out;
}

export function pageOf(report: GeometryReport, pageNumber: number): PageGeometry | null {
  return report.pages.find((page) => page.page_number === pageNumber) ?? null;
}

/** What the rendered page says about itself, as pdf.js reports it. */
export interface RenderedPage {
  width: number;
  height: number;
  rotation: number;
}

/**
 * Why this page carries no overlay, or `null` when it does.
 *
 * Four reasons, kept apart because they are four different things to tell a reader
 * and only one of them is about this document being unusual. A single "no highlights
 * here" would be indistinguishable from a bug — which is M4 slice 5's disabled-button
 * lesson, and slice 2's inline-sentence defect, in a third costume.
 */
export type OverlayGap =
  | { kind: "not_measured" }
  | { kind: "from_ocr"; page: number }
  | { kind: "unverified"; page: number }
  | { kind: "page_mismatch"; page: number };

export function gapForPage(
  report: GeometryReport,
  pageNumber: number,
  rendered: RenderedPage,
): OverlayGap | null {
  if (!report.measured) return { kind: "not_measured" };
  if (report.pages_from_ocr.includes(pageNumber)) return { kind: "from_ocr", page: pageNumber };

  const page = pageOf(report, pageNumber);
  if (page === null) return { kind: "unverified", page: pageNumber };

  // The stored box travels with the runs so the client never asks the PDF a second
  // time for something already known. Where the two disagree, the geometry is not
  // describing what is on screen — so nothing is drawn.
  const rotated = ((rendered.rotation % 360) + 360) % 360 !== 0;
  const resized =
    Math.abs(page.width - rendered.width) > SIZE_TOLERANCE ||
    Math.abs(page.height - rendered.height) > SIZE_TOLERANCE;
  if (rotated || resized) return { kind: "page_mismatch", page: pageNumber };

  return null;
}

/**
 * The gap in words.
 *
 * Every sentence says what is missing *and* that the text view still has it, because
 * the fallback is a working view rather than a dead end.
 */
export function describeGap(gap: OverlayGap): string {
  switch (gap.kind) {
    case "not_measured":
      return (
        "This resume was parsed before character positions were measured, so there is " +
        "nothing to draw on it. Every citation is still highlighted in the text view."
      );
    case "from_ocr":
      return (
        `Page ${gap.page} was read by OCR, so its text came from an image rather than ` +
        "from characters on the page — there is no glyph to point at. The text view " +
        "still highlights every citation."
      );
    case "unverified":
      return (
        `Page ${gap.page}'s character positions could not be checked against its text, ` +
        "so nothing is drawn on it rather than drawn in the wrong place."
      );
    case "page_mismatch":
      return (
        `Page ${gap.page} is not the size or orientation it was measured at, so nothing ` +
        "is drawn on it rather than drawn in the wrong place."
      );
  }
}

/**
 * Whether the original document is worth offering at all.
 *
 * pdf.js renders PDFs. A `.docx` has no fixed pages — which is also why a `.docx`
 * citation says "page 1" — so there is no document view to switch to, and offering a
 * tab that cannot work is worse than not offering one.
 */
export function canRenderOriginal(filename: string | null | undefined): boolean {
  return (filename ?? "").toLowerCase().endsWith(".pdf");
}

/** How many of a document's pages carry boxes, for the viewer's header. */
export function coverageNote(report: GeometryReport, pageCount: number): string {
  if (!report.measured) return "No measured positions";
  const covered = report.pages.length;
  if (covered === 0) return "No measured positions";
  if (covered === pageCount) return pageCount === 1 ? "Positions measured" : "All pages measured";
  return `${covered} of ${pageCount} pages measured`;
}
