/**
 * Motion 4 of `docs/DESIGN.md` §4: a queried figure counts up from zero.
 *
 * The doctrine says motion explains the mechanism rather than decorating it, and the
 * mechanism here is that **every number on the dashboard is a query over rows the system
 * already wrote** — nothing on that screen re-asks a model, and nothing asserts a total
 * it did not count. A figure that arrives already settled looks like a constant. One that
 * climbs looks like an answer.
 *
 * The awkward part, and the reason this is a module with tests rather than three lines in
 * a component: `/metrics` hands its figures over **already formatted**, because the
 * formatting carries meaning that a raw number cannot. `$0.0000` is four decimals on
 * purpose, `9.7 s` and `412 ms` are different units chosen by magnitude, `unknown` means a
 * price nobody knows and `—` means a mean over zero calls. Animating any of those by
 * parsing a float and re-printing it would silently rewrite the thing the screen is most
 * careful about.
 *
 * So this splits a formatted string in place, leaving every non-digit character exactly
 * where the formatter put it, and only ever varies the digits. A string with no digits —
 * `unknown`, `—` — returns null and is rendered as it is, which is what stops the one case
 * that would actually mislead.
 */

/** A formatted figure, split so its digits can be varied and nothing else can. */
export interface CountUpSpec {
  /** Everything before the first digit: a currency symbol, a sign, nothing. */
  prefix: string;
  /** Everything after the last digit: a unit, a percent sign, nothing. */
  suffix: string;
  /** The number the string represents, ignoring any grouping separators. */
  value: number;
  /** How many digits sit after the decimal point, so the count keeps its precision. */
  decimals: number;
  /** Whether the formatter grouped thousands, so the count keeps its commas. */
  grouped: boolean;
}

const DIGITS = /[0-9]/;

/**
 * Split a formatted figure, or answer null when there is nothing to count.
 *
 * Null is the important half. `unknown` and `—` are answers this project is deliberate
 * about — a cost nobody knows, a mean over zero calls — and a figure that counted up to
 * one of them would be inventing a number where the screen is saying there isn't one.
 */
export function parseCountUp(text: string): CountUpSpec | null {
  const first = [...text].findIndex((character) => DIGITS.test(character));
  if (first === -1) return null;

  let last = first;
  for (let at = first; at < text.length; at += 1) {
    const character = text[at] ?? "";
    if (DIGITS.test(character) || character === "," || character === ".") last = at;
  }
  // A trailing separator belongs to the suffix, not to the number: "1.5 s." would
  // otherwise end mid-decimal.
  while (last > first && !DIGITS.test(text[last] ?? "")) last -= 1;

  const body = text.slice(first, last + 1);
  const bare = body.replace(/,/g, "");
  const value = Number(bare);
  if (!Number.isFinite(value)) return null;

  const point = bare.indexOf(".");
  return {
    prefix: text.slice(0, first),
    suffix: text.slice(last + 1),
    value,
    decimals: point === -1 ? 0 : bare.length - point - 1,
    grouped: body.includes(","),
  };
}

/**
 * Render the figure at `fraction` of the way to its value.
 *
 * `fraction` is clamped, so a caller that overshoots on the last animation frame prints
 * the real figure rather than one above it — a dashboard that flashes a number higher
 * than the truth, however briefly, is worse than one that does not move at all.
 */
export function renderCountUp(spec: CountUpSpec, fraction: number): string {
  const clamped = Math.min(1, Math.max(0, fraction));
  const at = spec.value * clamped;
  const digits = spec.grouped
    ? at.toLocaleString("en-US", {
        minimumFractionDigits: spec.decimals,
        maximumFractionDigits: spec.decimals,
      })
    : at.toFixed(spec.decimals);
  return `${spec.prefix}${digits}${spec.suffix}`;
}

/**
 * Ease-out, so the figure decelerates into its answer instead of stopping dead.
 *
 * Cubic rather than the quintic the tokens use for entrances: over a number, quintic
 * spends most of the duration on the last few units and reads as a stall.
 */
export function easeOutCubic(fraction: number): number {
  const clamped = Math.min(1, Math.max(0, fraction));
  return 1 - Math.pow(1 - clamped, 3);
}
