/**
 * Join class names, dropping anything falsy.
 *
 * Deliberately not `clsx` or `tailwind-merge`: the primitives in `components/ui/`
 * take a `className` that is *appended*, so a caller's utility wins by CSS order
 * rather than by a merge algorithm nobody can predict from reading the call site.
 */
export function cn(...parts: (string | false | null | undefined)[]): string {
  return parts.filter(Boolean).join(" ");
}
