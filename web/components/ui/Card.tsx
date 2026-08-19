import type { ReactNode } from "react";

import { cn } from "@/lib/cn";

/**
 * The surface every panel in this app sits on.
 *
 * Written because the same card was hand-typed 21 times across nine different
 * padding recipes, and because two unrelated components were both called `Panel`.
 * A caller may still pass `className` — it lands after the base classes, so it
 * wins — but the border, radius, ground and shadow are decided here.
 */
export function Card({ children, className }: { children: ReactNode; className?: string }) {
  return <section className={cn("card", className)}>{children}</section>;
}

export function CardHeader({
  title,
  caption,
  action,
}: {
  title: ReactNode;
  /** One line under the title. Kept a slot rather than a string so a caption can
   *  carry a count, a token figure or a link without a second component. */
  caption?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <header className="flex items-start justify-between gap-3 border-b border-line px-4 py-3">
      <div className="min-w-0">
        <h2 className="text-section font-semibold">{title}</h2>
        {caption ? <p className="mt-0.5 text-micro text-ink-faint">{caption}</p> : null}
      </div>
      {action ? <div className="shrink-0">{action}</div> : null}
    </header>
  );
}

export function CardBody({
  children,
  padded = true,
  className,
}: {
  children: ReactNode;
  /** Off for a table or a divided list, which supply their own edges. */
  padded?: boolean;
  className?: string;
}) {
  return <div className={cn(padded && "px-4 py-3", className)}>{children}</div>;
}
