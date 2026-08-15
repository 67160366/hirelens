import { describe, expect, it } from "vitest";

import type { EvidenceRef, GeometryReport, PageGeometry } from "./api";
import {
  boxesFor,
  boxesForPage,
  canRenderOriginal,
  coverageNote,
  describeGap,
  gapForPage,
} from "./overlay";

/**
 * The overlay's arithmetic and its refusals (M5 slice 4).
 *
 * Two properties carry this module. **A citation covers its own characters and no
 * others** — the reason the geometry stores runs of characters rather than words, and
 * the case that would silently regress into "close enough". And **a page that cannot
 * be shown to match its geometry gets no boxes at all**, because a box in the wrong
 * place is a visual claim nobody can check.
 */

/** Ten characters on one line, 10pt wide each, starting at document offset 100. */
function run(charStart: number, count: number, top = 50, left = 0) {
  return {
    char_start: charStart,
    top,
    bottom: top + 12,
    x: Array.from({ length: count }, (_, index): [number, number] => [
      left + index * 10,
      left + index * 10 + 10,
    ]),
  };
}

const PAGE: PageGeometry = {
  page_number: 1,
  width: 595,
  height: 842,
  runs: [run(100, 10), run(110, 5, 70)],
};

function ref(char_start: number, char_end: number, extra: Partial<EvidenceRef> = {}): EvidenceRef {
  return {
    quote: "…",
    char_start,
    char_end,
    page: 1,
    match_kind: "exact",
    is_ambiguous: false,
    ...extra,
  } as EvidenceRef;
}

function report(overrides: Partial<GeometryReport> = {}): GeometryReport {
  return { measured: true, pages: [PAGE], pages_from_ocr: [], ...overrides };
}

const SAME_SIZE = { width: 595, height: 842, rotation: 0 };

describe("boxesForPage", () => {
  it("covers a quote's own characters, not the run it sits inside", () => {
    // The `ชำระเงิน` case from slice 3: eight characters inside an unbroken run, which
    // per-word geometry would have highlighted whole.
    const [box] = boxesForPage(PAGE, ref(102, 106));

    expect(box).toEqual({ left: 20, top: 50, width: 40, height: 12 });
  });

  it("splits into one box per line when a citation crosses a break", () => {
    const boxes = boxesForPage(PAGE, ref(105, 112));

    expect(boxes.map((box) => box.top)).toEqual([50, 70]);
  });

  it("clips to the characters a run actually holds", () => {
    // A citation running off the end of the measured text must not read past it.
    const boxes = boxesForPage(PAGE, ref(90, 103));

    expect(boxes).toEqual([{ left: 0, top: 50, width: 30, height: 12 }]);
  });

  it("draws nothing for a range no run covers", () => {
    expect(boxesForPage(PAGE, ref(0, 40))).toEqual([]);
  });

  it("draws nothing for an empty range", () => {
    expect(boxesForPage(PAGE, ref(102, 102))).toEqual([]);
  });

  it("keeps each box with the page it came from", () => {
    const second: PageGeometry = { ...PAGE, page_number: 2, runs: [run(200, 4)] };

    const boxes = boxesFor([PAGE, second], [ref(102, 104), ref(201, 203)]);

    expect(boxes.map((entry) => entry.page)).toEqual([1, 2]);
  });
});

describe("gapForPage", () => {
  it("draws on a page whose geometry matches what is rendered", () => {
    expect(gapForPage(report(), 1, SAME_SIZE)).toBeNull();
  });

  it("refuses a document that was never measured", () => {
    // Every resume uploaded before migration `0010`, which is not backfilled.
    const gap = gapForPage(report({ measured: false, pages: [] }), 1, SAME_SIZE);

    expect(gap).toEqual({ kind: "not_measured" });
  });

  it("names OCR before it names anything else", () => {
    // A recognized page has no glyph on the page to point at, and that is a different
    // sentence from "we could not verify this page".
    const gap = gapForPage(report({ pages: [], pages_from_ocr: [1] }), 1, SAME_SIZE);

    expect(gap).toEqual({ kind: "from_ocr", page: 1 });
  });

  it("refuses a page the parser could not prove", () => {
    const gap = gapForPage(report({ pages: [] }), 1, SAME_SIZE);

    expect(gap).toEqual({ kind: "unverified", page: 1 });
  });

  it("refuses a page that is not the size it was measured at", () => {
    // The stored box travels with the runs precisely so this can be checked. Without
    // it, a differently-cropped page would scale every box wrongly and look plausible.
    const gap = gapForPage(report(), 1, { ...SAME_SIZE, width: 612 });

    expect(gap).toEqual({ kind: "page_mismatch", page: 1 });
  });

  it("refuses a rotated page", () => {
    const gap = gapForPage(report(), 1, { ...SAME_SIZE, rotation: 90 });

    expect(gap).toEqual({ kind: "page_mismatch", page: 1 });
  });

  it("tolerates rounding, which the stored geometry has to two decimals", () => {
    expect(gapForPage(report(), 1, { ...SAME_SIZE, width: 595.01 })).toBeNull();
  });
});

describe("describeGap", () => {
  it("says what is missing and where the citations still are", () => {
    for (const gap of [
      { kind: "not_measured" },
      { kind: "from_ocr", page: 2 },
      { kind: "unverified", page: 2 },
      { kind: "page_mismatch", page: 2 },
    ] as const) {
      const sentence = describeGap(gap);
      expect(sentence.length).toBeGreaterThan(20);
      expect(sentence).toMatch(/\.$/);
    }
  });

  it("never claims the document lacks the citation", () => {
    // The same restraint as `not_evidenced`: the overlay cannot draw it, which is not
    // a statement about whether the quote is there.
    for (const gap of [
      { kind: "unverified", page: 1 },
      { kind: "page_mismatch", page: 1 },
    ] as const) {
      expect(describeGap(gap)).toContain("rather than drawn in the wrong place");
    }
  });

  it("names the page it is talking about", () => {
    expect(describeGap({ kind: "from_ocr", page: 3 })).toContain("Page 3");
  });
});

describe("canRenderOriginal", () => {
  it("offers the original only for a PDF", () => {
    expect(canRenderOriginal("resume_th.pdf")).toBe(true);
    expect(canRenderOriginal("RESUME.PDF")).toBe(true);
  });

  it("declines anything pdf.js cannot render, and anything it cannot name", () => {
    // A `.docx` has no fixed pages — the same reason a `.docx` citation says page 1 —
    // and an unknown filename fails closed rather than opening a tab that would throw.
    expect(canRenderOriginal("resume_th.docx")).toBe(false);
    expect(canRenderOriginal("a1b2c3d4")).toBe(false);
    expect(canRenderOriginal(null)).toBe(false);
  });
});

describe("coverageNote", () => {
  it("counts the pages that carry boxes", () => {
    expect(coverageNote(report(), 1)).toBe("Positions measured");
    expect(coverageNote(report(), 3)).toBe("1 of 3 pages measured");
  });

  it("says nothing was measured rather than 0 of 3", () => {
    expect(coverageNote(report({ measured: false, pages: [] }), 3)).toBe("No measured positions");
    expect(coverageNote(report({ pages: [] }), 3)).toBe("No measured positions");
  });
});
