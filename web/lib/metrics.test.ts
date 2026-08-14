/**
 * Tests for how the usage and quality dashboard is worded.
 *
 * Every failure here is silent. An unknown cost rendered as `$0.00` is a number a
 * reader will act on; a `0.0%` hallucination rate over zero claims reads as a clean
 * bill of health for data that does not exist; and an anomaly bucket hidden because
 * it happened to be empty in development is a row nobody sees on the day it is not.
 * None of the three throws, and none is visible in a screenshot.
 *
 * The cost cases matter most *because* every call is free-tier today: a real 0.00 and
 * an unknown price render identically the moment somebody writes `?? 0`.
 */

import { describe, expect, it } from "vitest";

import type { CallTotals, ParseOutcome, QualitySummary, UsageReport } from "./api";
import {
  NOTHING_YET,
  UNKNOWN,
  attributionIsClean,
  bucketLabel,
  bucketsToShow,
  costIsComplete,
  describeAttributionGap,
  describeCostGap,
  droppedNote,
  formatCost,
  formatLatency,
  formatParseSuccess,
  formatRate,
  isClean,
  isEmpty,
  parseSuccess,
  scopeNote,
  totalTokens,
} from "./metrics";

function totals(overrides: Partial<CallTotals> = {}): CallTotals {
  return {
    calls: 2,
    input_tokens: 100,
    output_tokens: 50,
    cached_input_tokens: 0,
    latency_ms_total: 500,
    latency_ms_mean: 250,
    calls_priced: 2,
    cost_usd: 0,
    ...overrides,
  };
}

function quality(overrides: Partial<QualitySummary> = {}): QualitySummary {
  return {
    profiles: 1,
    claims_verified: 9,
    claims_dropped: 1,
    hallucination_rate: 0.1,
    extraction_attempts_total: 2,
    ...overrides,
  };
}

function report(overrides: Partial<UsageReport> = {}): UsageReport {
  return {
    scope: "own",
    generated_at: "2026-08-15T00:00:00Z",
    totals: totals(),
    by_bucket: {
      extraction: totals(),
      judging: totals({ calls: 0, calls_priced: 0, latency_ms_mean: null }),
      unattributed: totals({ calls: 0, calls_priced: 0, latency_ms_mean: null }),
      ambiguous: totals({ calls: 0, calls_priced: 0, latency_ms_mean: null }),
    },
    by_group: [],
    quality: quality(),
    parse_outcomes: [],
    ...overrides,
  };
}

describe("cost", () => {
  it("renders a known zero cost as money, not as unknown", () => {
    // The free tier really does cost nothing, and saying so is a true answer.
    expect(formatCost(totals({ cost_usd: 0 }))).toBe("$0.0000");
  });

  it("renders an unknown cost as unknown, never as $0.00", () => {
    // The whole point of the slice's one surviving cost rule.
    expect(formatCost(totals({ cost_usd: null, calls_priced: 1 }))).toBe(UNKNOWN);
  });

  it("keeps a real zero and an unknown price distinguishable", () => {
    // They are one `?? 0` apart, and today every call is free-tier — which is
    // exactly when collapsing them looks harmless.
    expect(formatCost(totals({ cost_usd: 0 }))).not.toBe(formatCost(totals({ cost_usd: null })));
  });

  it("names how many rows are unpriced, so unknown is a measurement not a bug", () => {
    expect(describeCostGap(totals({ calls: 22, calls_priced: 19, cost_usd: null }))).toBe(
      "3 of 22 calls have no known price",
    );
  });

  it("says nothing about a gap when there is none", () => {
    expect(describeCostGap(totals({ cost_usd: 1.5 }))).toBeNull();
  });

  it("agrees with itself about completeness", () => {
    expect(costIsComplete(totals({ cost_usd: 0 }))).toBe(true);
    expect(costIsComplete(totals({ cost_usd: null }))).toBe(false);
  });

  it("uses singular wording for a single call", () => {
    expect(describeCostGap(totals({ calls: 1, calls_priced: 0, cost_usd: null }))).toBe(
      "1 of 1 call has no known price",
    );
  });
});

describe("latency", () => {
  it("shows a dash rather than 0 ms when there are no calls", () => {
    // 0 ms would read as "instant".
    expect(formatLatency(null)).toBe(NOTHING_YET);
  });

  it("keeps milliseconds under a second and switches to seconds above it", () => {
    expect(formatLatency(250)).toBe("250 ms");
    expect(formatLatency(9698)).toBe("9.7 s");
  });
});

describe("the hallucination rate", () => {
  it("shows a dash rather than 0.0% when no claims exist", () => {
    // 0.0% over nothing reads as "nothing was fabricated".
    expect(formatRate(null)).toBe(NOTHING_YET);
  });

  it("renders a real rate at the precision it is stored to", () => {
    expect(formatRate(0.091)).toBe("9.1%");
    expect(formatRate(0)).toBe("0.0%");
  });

  it("keeps a real zero rate and an absent one apart", () => {
    expect(formatRate(0)).not.toBe(formatRate(null));
  });

  it("calls a summary clean only when nothing was dropped", () => {
    expect(isClean(quality({ claims_dropped: 0 }))).toBe(true);
    expect(isClean(quality({ claims_dropped: 1 }))).toBe(false);
  });

  it("does not derive cleanliness from the rounded rate", () => {
    // A single dropped claim among thousands rounds to 0.0% and is still not clean.
    expect(isClean(quality({ claims_verified: 9999, claims_dropped: 1 }))).toBe(false);
  });

  it("counts a single dropped claim in the singular", () => {
    // The browser walkthrough rendered "1 claims dropped"; the sentence lived
    // inside JSX where nothing could test it.
    expect(droppedNote(quality({ claims_dropped: 1 }))).toBe("1 claim dropped");
  });

  it("counts several in the plural, with a thousands separator", () => {
    expect(droppedNote(quality({ claims_dropped: 1234 }))).toBe("1,234 claims dropped");
  });

  it("says nothing when nothing was dropped", () => {
    expect(droppedNote(quality({ claims_dropped: 0 }))).toBeNull();
  });
});

describe("attribution", () => {
  it("is clean when every call named exactly one owner", () => {
    expect(attributionIsClean(report())).toBe(true);
    expect(describeAttributionGap(report())).toBeNull();
  });

  it("reports an unattributed call rather than letting it vanish", () => {
    const withOrphan = report({
      by_bucket: { ...report().by_bucket, unattributed: totals({ calls: 3 }) },
    });
    expect(attributionIsClean(withOrphan)).toBe(false);
    expect(describeAttributionGap(withOrphan)).toContain("3 unattributed");
  });

  it("reports both anomalies together when both occur", () => {
    const messy = report({
      by_bucket: {
        ...report().by_bucket,
        unattributed: totals({ calls: 1 }),
        ambiguous: totals({ calls: 2 }),
      },
    });
    expect(describeAttributionGap(messy)).toContain("1 unattributed and 2 ambiguous");
  });

  it("hides the anomaly buckets while they are empty and shows them when they are not", () => {
    // A permanent pair of zeroes trains people to skip the row that matters on the
    // day it is not zero.
    expect(bucketsToShow(report())).toEqual(["extraction", "judging"]);

    const withOrphan = report({
      by_bucket: { ...report().by_bucket, unattributed: totals({ calls: 1 }) },
    });
    expect(bucketsToShow(withOrphan)).toEqual(["extraction", "judging", "unattributed"]);
  });

  it("never hides the two real buckets, even at zero", () => {
    // These are the split the whole schema exists to keep separable; an absent
    // "judging" row and a zero are different claims.
    const nothing = report({
      by_bucket: {
        extraction: totals({ calls: 0 }),
        judging: totals({ calls: 0 }),
        unattributed: totals({ calls: 0 }),
        ambiguous: totals({ calls: 0 }),
      },
    });
    expect(bucketsToShow(nothing)).toEqual(["extraction", "judging"]);
  });

  it("labels every bucket", () => {
    for (const bucket of ["extraction", "judging", "unattributed", "ambiguous"] as const) {
      expect(bucketLabel(bucket)).toBeTruthy();
    }
  });
});

describe("parse success", () => {
  const outcomes: ParseOutcome[] = [
    { status: "extracted", resumes: 3 },
    { status: "failed", resumes: 1 },
  ];

  it("counts extracted over everything accounted for", () => {
    expect(parseSuccess(outcomes)).toEqual({ extracted: 3, total: 4 });
    expect(formatParseSuccess(outcomes)).toBe("75%");
  });

  it("shows a dash rather than 0% when nothing has been uploaded", () => {
    expect(formatParseSuccess([])).toBe(NOTHING_YET);
  });

  it("counts a status with no extracted rows as zero rather than throwing", () => {
    expect(formatParseSuccess([{ status: "failed", resumes: 2 }])).toBe("0%");
  });
});

describe("the rest", () => {
  it("sums tokens in and out", () => {
    expect(totalTokens(totals({ input_tokens: 8410, output_tokens: 27439 }))).toBe(35849);
  });

  it("says whose rows are being counted", () => {
    expect(scopeNote("own")).toContain("Your own rows only");
    expect(scopeNote("all")).toContain("admin");
  });

  it("knows an empty report from a populated one", () => {
    expect(isEmpty(report({ totals: totals({ calls: 0 }), quality: quality({ profiles: 0 }) }))).toBe(
      true,
    );
    expect(isEmpty(report())).toBe(false);
  });
});
