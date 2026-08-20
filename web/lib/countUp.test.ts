/**
 * Tests for Motion 4's arithmetic.
 *
 * The animation is decoration; **what it must never do is change what the figure says**,
 * and every case here is one way it could:
 *
 *   * **Counting up to a non-number.** `unknown` is what `/metrics` prints when a price is
 *     unknown, and `—` is a mean over zero calls. Both are deliberate refusals to state a
 *     figure, and an implementation that parsed a float out of them would animate to `0`
 *     or `NaN` and turn a refusal into an assertion.
 *   * **Losing precision.** `$0.0000` is four decimals because the cost rule needs them.
 *     A count that printed `$0` on the way would say something the row does not.
 *   * **Losing the unit.** `9.7 s` and `412 ms` are different units chosen by magnitude;
 *     re-formatting from a raw float would print one as the other.
 *   * **Losing the grouping.** `27,439` is grouped; `27439` mid-animation is a different
 *     column width and a harder number to read.
 *   * **Overshooting.** A dashboard that flashes a figure above the truth, even for one
 *     frame, is worse than one that does not move.
 */

import { describe, expect, it } from "vitest";

import { easeOutCubic, parseCountUp, renderCountUp } from "./countUp";

describe("splitting a formatted figure", () => {
  it("reads a plain integer", () => {
    expect(parseCountUp("711")).toEqual({
      prefix: "",
      suffix: "",
      value: 711,
      decimals: 0,
      grouped: false,
    });
  });

  it("keeps a currency prefix and its decimals", () => {
    expect(parseCountUp("$0.0000")).toEqual({
      prefix: "$",
      suffix: "",
      value: 0,
      decimals: 4,
      grouped: false,
    });
  });

  it("keeps a unit suffix", () => {
    expect(parseCountUp("9.7 s")).toEqual({
      prefix: "",
      suffix: " s",
      value: 9.7,
      decimals: 1,
      grouped: false,
    });
    expect(parseCountUp("412 ms")?.suffix).toBe(" ms");
  });

  it("notices a thousands separator", () => {
    const spec = parseCountUp("27,439");
    expect(spec?.value).toBe(27439);
    expect(spec?.grouped).toBe(true);
  });

  it("keeps a percent sign", () => {
    expect(parseCountUp("9.1%")).toEqual({
      prefix: "",
      suffix: "%",
      value: 9.1,
      decimals: 1,
      grouped: false,
    });
  });

  it("refuses anything with no digits in it", () => {
    // The two the screen actually prints, and the reason this function returns null at
    // all rather than defaulting to zero.
    expect(parseCountUp("unknown")).toBeNull();
    expect(parseCountUp("—")).toBeNull();
  });
});

describe("rendering a figure part-way", () => {
  it("starts at zero in the figure's own shape", () => {
    const spec = parseCountUp("$0.0000")!;
    expect(renderCountUp(spec, 0)).toBe("$0.0000");
    const tokens = parseCountUp("27,439")!;
    expect(renderCountUp(tokens, 0)).toBe("0");
  });

  it("arrives at exactly what it was given", () => {
    for (const text of ["711", "$0.0000", "9.7 s", "27,439", "9.1%", "412 ms"]) {
      expect(renderCountUp(parseCountUp(text)!, 1)).toBe(text);
    }
  });

  it("keeps the grouping and the precision on the way", () => {
    expect(renderCountUp(parseCountUp("27,439")!, 0.5)).toBe("13,720");
    // 9.7 / 2 is 4.85, which `toFixed(1)` renders as "4.8" — binary floating point
    // stores it a hair below the halfway point. Pinned as what it does rather than as
    // what the arithmetic looks like it should do.
    expect(renderCountUp(parseCountUp("9.7 s")!, 0.5)).toBe("4.8 s");
  });

  it("never prints more than the truth, however far a caller overshoots", () => {
    // The last frame of a requestAnimationFrame loop routinely lands past the end.
    expect(renderCountUp(parseCountUp("711")!, 1.4)).toBe("711");
    expect(renderCountUp(parseCountUp("711")!, -0.2)).toBe("0");
  });
});

describe("the easing", () => {
  it("runs from nothing to everything and decelerates", () => {
    expect(easeOutCubic(0)).toBe(0);
    expect(easeOutCubic(1)).toBe(1);
    // Past halfway by the time a third of the duration has run, which is what makes a
    // figure read as settling rather than as stalling near the end.
    expect(easeOutCubic(1 / 3)).toBeGreaterThan(0.5);
  });

  it("clamps rather than running past its answer", () => {
    expect(easeOutCubic(1.5)).toBe(1);
    expect(easeOutCubic(-1)).toBe(0);
  });
});
