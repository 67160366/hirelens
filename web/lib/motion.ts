"use client";

/**
 * Whether this reader has asked for less motion.
 *
 * `globals.css` already neutralises every CSS animation under
 * `prefers-reduced-motion: reduce`, and that covers three of the four motions in
 * `docs/DESIGN.md` §4. It cannot cover the fourth: a figure counting up is a **text
 * substitution**, and no `animation-duration` override reaches a number being retyped
 * sixty times a second. So that one has to ask.
 *
 * It is an external store rather than an effect for the reason `lib/auth.ts` and
 * `lib/theme.ts` are: `useSyncExternalStore` gives a value during render, so a component
 * can *decide* whether to animate instead of rendering the animated form and then
 * correcting itself. That is what keeps `react-hooks/set-state-in-effect` satisfied
 * honestly rather than with a suppression — this repo removed its last genuine one when
 * `useAuth` moved onto the same primitive, and adding one back for a decoration would be
 * a poor trade.
 *
 * The server snapshot is **true**: with no way to ask, the answer is the one that moves
 * nothing.
 */

import { useSyncExternalStore } from "react";

const QUERY = "(prefers-reduced-motion: reduce)";

function media(): MediaQueryList | null {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") return null;
  return window.matchMedia(QUERY);
}

export function subscribeToMotionPreference(listener: () => void): () => void {
  const query = media();
  query?.addEventListener("change", listener);
  return () => query?.removeEventListener("change", listener);
}

/** Does this reader want motion kept to a minimum? */
export function readsReducedMotion(): boolean {
  return media()?.matches ?? true;
}

/** The same question where there is nothing to ask — answered so nothing moves. */
function reducedOnServer(): boolean {
  return true;
}

export function usePrefersReducedMotion(): boolean {
  return useSyncExternalStore(
    subscribeToMotionPreference,
    readsReducedMotion,
    reducedOnServer,
  );
}
