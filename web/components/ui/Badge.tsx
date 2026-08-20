import type { ReactNode } from "react";

import { cn } from "@/lib/cn";

const TONES = {
  cited: "border-cited/40 bg-cited-wash text-cited",
  ambiguous: "border-ambiguous/40 bg-ambiguous-wash text-ambiguous",
  dropped: "border-dropped/40 bg-dropped-wash text-dropped",
  accent: "border-accent/40 bg-accent-wash text-accent",
  neutral: "border-line bg-surface-sunken text-ink-muted",
} as const;

/**
 * A small state label.
 *
 * The tone is only ever half the message. Every caller must pass words too, because
 * status signalled by colour alone is unreadable to a colour-blind reader and
 * invisible to a screen reader — which is what the stats bar and the ranking gate
 * both did.
 */
export function Badge({
  tone = "neutral",
  children,
  className,
  title,
}: {
  tone?: keyof typeof TONES;
  children: ReactNode;
  className?: string;
  /** A hover explanation of the consequence, where the label alone cannot carry it
   *  — "must have" says what it is, not that missing it ranks you last. Named
   *  explicitly rather than spreading arbitrary attributes, so the next thing a
   *  caller wants to pass has to be argued for here rather than smuggled in. Never
   *  the only place a meaning lives: a tooltip reaches neither a keyboard nor a
   *  touchscreen. */
  title?: string;
}) {
  return (
    <span
      title={title}
      className={cn(
        "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-micro font-medium",
        TONES[tone],
        className,
      )}
    >
      {children}
    </span>
  );
}
