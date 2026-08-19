import type { ReactNode } from "react";

import { cn } from "@/lib/cn";

const TONES = {
  danger: "border-dropped/40 bg-dropped-wash text-dropped",
  warn: "border-ambiguous/40 bg-ambiguous-wash text-ambiguous",
  success: "border-cited/40 bg-cited-wash text-cited",
  info: "border-line bg-surface-sunken text-ink-muted",
} as const;

/**
 * A message about the state of the page.
 *
 * Eight incompatible recipes across three tones existed before this, and **six of
 * the eight error banners were silent to a screen reader** — two carried
 * `role="alert"` and the rest carried nothing, so a failed upload was announced to
 * nobody. The role is derived from the tone here rather than passed in, which is
 * what turns six separate omissions into one decision made once.
 *
 * `danger` is assertive because it reports something that already went wrong;
 * everything else is polite so it cannot interrupt what somebody is typing.
 */
export function Banner({
  tone,
  children,
  className,
}: {
  tone: keyof typeof TONES;
  children: ReactNode;
  className?: string;
}) {
  return (
    <div
      role={tone === "danger" ? "alert" : "status"}
      className={cn(
        "animate-fade-in rounded-control border px-4 py-2.5 text-sm",
        TONES[tone],
        className,
      )}
    >
      {children}
    </div>
  );
}

/**
 * A live region that exists before it has anything to say.
 *
 * An `aria-live` container mounted at the same moment as its text is not announced
 * — the region has to be in the accessibility tree first. That is why this renders
 * whether or not `children` is empty, and why upload progress goes through it.
 */
export function LiveRegion({ children, className }: { children?: ReactNode; className?: string }) {
  return (
    <p role="status" aria-live="polite" className={cn("text-sm text-ink-muted", className)}>
      {children}
    </p>
  );
}
