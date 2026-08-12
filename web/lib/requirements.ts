/**
 * The shape of a blank requirement, and the bounds its weight input enforces.
 *
 * Its own pure module for the reason `lib/applications.ts` and `lib/screening.ts`
 * are: `npm test` runs with no DOM and no React testing library, so a rule that
 * lives only in a component's JSX attributes is a rule nothing can check. This
 * file is what gives the one below somewhere to be checked.
 */

import type { RequirementInput } from "@/lib/api";

/**
 * What a new, empty requirement row starts as.
 *
 * Was defined identically in both `/jobs` and `/jobs/[id]`. That duplication is
 * what let the default and the input's bounds disagree without either copy
 * looking wrong on its own.
 */
export const BLANK_REQUIREMENT: RequirementInput = {
  kind: "skill",
  label: "",
  detail: null,
  must_have: false,
  weight: 1,
};

/**
 * The weight input's `min`, `max` and `step`.
 *
 * A browser treats a number input as valid only when `(value - min)` is a whole
 * multiple of `step`. These were `min=0.1, step=0.5`, making the valid values
 * 0.1, 0.6, 1.1 … — and **1, which is what `BLANK_REQUIREMENT` carries, was not
 * one of them.** So `Create job` silently refused to submit: no request, no error
 * of ours, just a native tooltip saying "the two nearest valid values are 0.6 and
 * 1.1". Present since the form was written and invisible to a suite with no DOM.
 *
 * 0.1 divides every weight anyone would type, including the default and whole
 * numbers.
 */
export const WEIGHT_BOUNDS = { min: 0.1, max: 100, step: 0.1 } as const;

/**
 * The same arithmetic a browser does before it will let the form submit.
 *
 * Written so the bounds are checked against the values that actually flow through
 * them, rather than against somebody's mental arithmetic — which is the step that
 * was missing.
 */
export function weightIsValid(weight: number): boolean {
  const { min, max, step } = WEIGHT_BOUNDS;
  if (weight < min || weight > max) return false;
  const steps = (weight - min) / step;
  // A browser allows a tolerance rather than demanding exact binary equality, and
  // so must this: `(20 - 0.1) / 0.1` is 198.99999999999997, and 20 is a weight
  // somebody really types. An exact check would refuse it.
  return Math.abs(steps - Math.round(steps)) < 1e-6;
}
