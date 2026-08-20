"use client";

import { useEffect, useState } from "react";

import { easeOutCubic, parseCountUp, renderCountUp } from "@/lib/countUp";
import { usePrefersReducedMotion } from "@/lib/motion";

/**
 * Motion 4 of `docs/DESIGN.md` §4 — a queried figure counts up from zero.
 *
 * M5's organizing idea is that **every number on an observability screen is a query over
 * rows the system already wrote**. A figure that is simply there looks like a constant;
 * one that climbs to its answer looks like the result of asking. That is why this motion
 * is on the list of four rather than being decoration.
 *
 * The arithmetic lives in `lib/countUp.ts` with its own tests, because `web/` has no DOM
 * and because the thing that must never happen is not a stutter — it is the animation
 * changing what the figure *says*. `unknown` and `—` are refusals to state a number, and
 * `parseCountUp` returns null for them, so they render untouched.
 *
 * **Nothing here sets state in an effect.** Whether to animate is decided during render,
 * from an external store (`usePrefersReducedMotion`) and from whether the text has digits
 * in it; the effect only advances a fraction from inside a `requestAnimationFrame`
 * callback. CSS cannot reach this motion — it is a text substitution, not an animation —
 * so the preference has to be asked rather than declared.
 */
export function CountUp({ value, durationMs = 620 }: { value: string; durationMs?: number }) {
  const spec = parseCountUp(value);
  const still = usePrefersReducedMotion();
  const animate = spec !== null && !still;

  const [fraction, setFraction] = useState(0);

  useEffect(() => {
    if (!animate) return;
    let frame = 0;
    let start: number | null = null;
    const step = (now: number) => {
      start ??= now;
      const through = (now - start) / durationMs;
      setFraction(through);
      if (through < 1) frame = requestAnimationFrame(step);
    };
    frame = requestAnimationFrame(step);
    return () => cancelAnimationFrame(frame);
    // Restarts when the text changes, so pressing Refresh counts the new figure rather
    // than snapping to it.
  }, [animate, value, durationMs]);

  if (!animate || spec === null) return <>{value}</>;
  return <>{renderCountUp(spec, easeOutCubic(fraction))}</>;
}
