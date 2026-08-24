import { describe, expect, it } from "vitest";

import {
  SAMPLE_DOCUMENT,
  SAMPLE_FABRICATION,
  SAMPLE_QUOTE,
  splitAroundQuote,
} from "./sample";

/**
 * The explainer illustrates the guardrail, so the illustration has to obey it.
 *
 * Both properties below are invisible on the rendered page — a highlight looks
 * the same whether or not the text under it is really there, which is exactly the
 * thing this product refuses to take on trust anywhere else.
 */
describe("the sample the explainer is drawn from", () => {
  it("contains the quote it shows as cited", () => {
    expect(SAMPLE_DOCUMENT).toContain(SAMPLE_QUOTE);
  });

  // The sharper half. If somebody edits the sample document later and happens to
  // include this sentence, the page would strike through a quote that is in the
  // document and teach the reader the opposite of the mechanism.
  it("does not contain the quote it shows as fabricated", () => {
    expect(SAMPLE_DOCUMENT).not.toContain(SAMPLE_FABRICATION);
  });
});

describe("splitAroundQuote", () => {
  it("returns the text on either side of the quote", () => {
    expect(splitAroundQuote("abcdef", "cd")).toEqual({ before: "ab", after: "ef" });
  });

  it("keeps the whole document reconstructable, so nothing is lost to the highlight", () => {
    const parts = splitAroundQuote(SAMPLE_DOCUMENT, SAMPLE_QUOTE);
    expect(parts).not.toBeNull();
    expect(`${parts!.before}${SAMPLE_QUOTE}${parts!.after}`).toBe(SAMPLE_DOCUMENT);
  });

  it("refuses to locate a quote that is not there", () => {
    expect(splitAroundQuote(SAMPLE_DOCUMENT, SAMPLE_FABRICATION)).toBeNull();
  });

  it("splits on the first occurrence only", () => {
    expect(splitAroundQuote("aXbXc", "X")).toEqual({ before: "a", after: "bXc" });
  });
});
