/**
 * The bounds on the weight input, checked against the values that flow through it.
 *
 * This file exists because of a bug that a green suite, a clean typecheck and a
 * passing build all missed: the weight input carried `min=0.1 step=0.5`, while
 * every new requirement starts at `weight: 1`. A browser will not submit a number
 * input unless `(value - min)` is a whole multiple of `step`, and `(1 - 0.1) / 0.5`
 * is 1.8 — so `Create job` did nothing at all, with no request and no error of
 * ours. Chrome's own tooltip named the two nearest valid values, 0.6 and 1.1.
 *
 * It was invisible here because the rule lived in JSX attributes and `npm test`
 * has no DOM. The fix was to give the property somewhere to be checked rather
 * than to write a cleverer assertion — the same move as splitting `reclaim_stalled`
 * so its guard had a seam to be driven through.
 */

import { describe, expect, it } from "vitest";

import { BLANK_REQUIREMENT, WEIGHT_BOUNDS, weightIsValid } from "./requirements";

describe("the weight a new requirement starts with", () => {
  it("is one the browser will actually submit", () => {
    // The whole bug, in one line. This fails against `step: 0.5`.
    expect(weightIsValid(BLANK_REQUIREMENT.weight)).toBe(true);
  });

  it("is within the bounds as well as on a step", () => {
    expect(BLANK_REQUIREMENT.weight).toBeGreaterThanOrEqual(WEIGHT_BOUNDS.min);
    expect(BLANK_REQUIREMENT.weight).toBeLessThanOrEqual(WEIGHT_BOUNDS.max);
  });
});

describe("weightIsValid", () => {
  it("accepts the whole numbers people actually type", () => {
    // Every one of these was refused by the browser under `step: 0.5`.
    for (const weight of [1, 2, 3, 5, 10, 20, 100]) {
      expect(weightIsValid(weight), `weight ${weight}`).toBe(true);
    }
  });

  it("accepts one decimal place, which is what the step is for", () => {
    for (const weight of [0.1, 0.5, 1.5, 2.7, 99.9]) {
      expect(weightIsValid(weight), `weight ${weight}`).toBe(true);
    }
  });

  it("survives floating point, which is why there is a tolerance", () => {
    // Not a hypothetical. `(20 - 0.1) / 0.1` is 198.99999999999997, and 20 is the
    // weight M3's own live run used to demonstrate the must-have gate. An exact
    // equality check here would refuse it and reintroduce the bug in a subtler
    // form — whole numbers rejected, one-decimal values accepted.
    const steps = (20 - WEIGHT_BOUNDS.min) / WEIGHT_BOUNDS.step;
    expect(Number.isInteger(steps)).toBe(false);
    expect(weightIsValid(20)).toBe(true);
  });

  it("refuses a weight outside the bounds", () => {
    // The server agrees: `weight` is `gt=0, le=100`, and there is a check
    // constraint behind it. This is the client saying so before the round trip.
    expect(weightIsValid(0)).toBe(false);
    expect(weightIsValid(-1)).toBe(false);
    expect(weightIsValid(100.5)).toBe(false);
  });

  it("refuses a value between steps", () => {
    expect(weightIsValid(1.05)).toBe(false);
  });
});
