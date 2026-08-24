"use client";

/**
 * Reveal an element the first time it is scrolled into view.
 *
 * Written when `/how-we-screen` needed the same gesture the landing page already
 * had, and copying twenty lines of `IntersectionObserver` would have made the
 * next change two changes. It lives in `lib/` rather than in a component for the
 * reason the rest of this directory does: `web/` has vitest and no DOM, so
 * behaviour defined inside a page is behaviour nothing can reach.
 *
 * **The element is readable before this runs.** Arming happens in JS, so a reader
 * with JS disabled — or one whose observer never fires — gets the page rather
 * than a blank column. That order is the whole reason `reveal-armed` is added
 * here instead of being written into the markup.
 *
 * Reduced motion skips the arming entirely: the CSS block at the bottom of
 * `globals.css` collapses the animation, but an element that was armed and never
 * unarmed would stay invisible, which is a worse answer than no animation.
 */

import { useEffect } from "react";

import { readsReducedMotion } from "@/lib/motion";

/** Arms every `[data-reveal]` in the document and reveals each as it appears. */
export function useScrollReveal(): void {
  useEffect(() => {
    if (readsReducedMotion()) return;
    const targets = Array.from(document.querySelectorAll<HTMLElement>("[data-reveal]"));
    for (const target of targets) target.classList.add("reveal-armed");

    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (!entry.isIntersecting) continue;
          entry.target.classList.remove("reveal-armed");
          entry.target.classList.add("reveal-in");
          observer.unobserve(entry.target);
        }
      },
      { rootMargin: "0px 0px -12% 0px" },
    );
    for (const target of targets) observer.observe(target);
    return () => observer.disconnect();
  }, []);
}
