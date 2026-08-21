import type { ReactNode } from "react";

/**
 * The application's screens are in English; the public site is in Thai.
 *
 * `docs/DESIGN.md` §8: Thai-first governs the **public** pages, and the screens
 * that existed before the careers site keep their English copy, because folding a
 * translation into a screen's migration makes it two changes at once. Next allows
 * exactly one `<html>`, and it is `lang="th"` in `app/layout.tsx` — so the
 * exception is declared here, on the segment, rather than by leaving the document
 * lying about half of itself.
 *
 * This is not styling. A screen reader picks its voice from `lang`, and Thai
 * synthesis reading English copy is unintelligible rather than merely wrong.
 */
export default function Layout({ children }: { children: ReactNode }) {
  return <div lang="en">{children}</div>;
}
