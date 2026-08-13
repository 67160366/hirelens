import type { DroppedClaim } from "@/lib/api";
import { DROPPED_PANEL_EXPLANATION, droppedPanelTitle, droppedReasonLabel } from "@/lib/evidence";

/**
 * What the model claimed and the system refused to repeat.
 *
 * Shared by the profile view and the screening view, because the server puts both
 * kinds of fabrication in the same list: a quote that is not in the document and a
 * quote aimed at a requirement that does not exist are the same class of claim, and
 * both are counted in the same hallucination rate.
 *
 * Renders nothing when nothing was dropped — an empty panel would read as a finding.
 */
export function DroppedClaims({ dropped }: { dropped: DroppedClaim[] }) {
  if (dropped.length === 0) return null;

  return (
    <section className="rounded-lg border border-amber-300 bg-amber-50/70 p-4 dark:border-amber-900/60 dark:bg-amber-950/30">
      <h3 className="text-sm font-semibold text-amber-900 dark:text-amber-300">
        {droppedPanelTitle(dropped.length)}
      </h3>
      <p className="mt-1 text-xs text-amber-800/80 dark:text-amber-400/80">
        {DROPPED_PANEL_EXPLANATION}
      </p>
      <ul className="mt-3 space-y-2.5">
        {dropped.map((claim, index) => (
          <li key={`${claim.field}-${index}`} className="text-sm">
            <span className="font-mono text-[11px] text-amber-700 dark:text-amber-500">
              {claim.field}
            </span>{" "}
            <span className="font-medium">{claim.value || "(no value)"}</span>
            <span className="ml-1.5 text-xs text-amber-700/80 dark:text-amber-500/80">
              — {droppedReasonLabel(claim.reason)}
            </span>
            {claim.quote && (
              <p className="evidence-quote mt-0.5 text-amber-800/70 line-through dark:text-amber-500/60">
                claimed: &ldquo;{claim.quote}&rdquo;
              </p>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}
