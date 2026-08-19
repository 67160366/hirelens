import type { ReactNode } from "react";

import { cn } from "@/lib/cn";

/**
 * One figure and what it means.
 *
 * A `<dl>` rather than two sibling `<p>` elements, so a screen reader ties "Model
 * calls" to its number instead of reading two unrelated strings — which is what the
 * metrics tiles did.
 *
 * `note` exists so a tone always arrives with a **word**: a figure that is amber
 * and says nothing has told a colour-blind reader nothing at all.
 */
export function Stat({
  label,
  value,
  note,
  tone = "neutral",
  className,
}: {
  label: ReactNode;
  value: ReactNode;
  note?: ReactNode;
  tone?: "neutral" | "cited" | "ambiguous" | "dropped";
  className?: string;
}) {
  return (
    <dl className={cn("card px-4 py-3", className)}>
      <dt className="text-micro font-medium uppercase tracking-wide text-ink-faint">{label}</dt>
      <dd
        className={cn(
          "mt-1 font-mono text-2xl tabular-nums",
          tone === "neutral" && "text-ink",
          tone === "cited" && "text-cited",
          tone === "ambiguous" && "text-ambiguous",
          tone === "dropped" && "text-dropped",
        )}
      >
        {value}
      </dd>
      {note ? <dd className="mt-0.5 text-micro text-ink-muted">{note}</dd> : null}
    </dl>
  );
}
