import type { EvidenceStats } from "@/lib/api";
import { isClean, modelCallCount, unverifiablePercent } from "@/lib/evidence";

/**
 * The verification counters for one result — a profile or a judgment.
 *
 * The same bar serves both because the server produces one `EvidenceStats` for
 * both: judging reuses extraction's counters unchanged, which is what makes the
 * hallucination rate cover it for free (docs/HANDOFF.md §5).
 */
export function EvidenceStatsBar({ stats }: { stats: EvidenceStats }) {
  return (
    <div className="flex flex-wrap items-center gap-x-5 gap-y-2 rounded-lg border border-stone-200 bg-white px-4 py-3 text-sm dark:border-stone-800 dark:bg-stone-900">
      <span>
        <strong className="tabular-nums">
          {stats.verified}/{stats.total_claims}
        </strong>{" "}
        <span className="text-stone-500 dark:text-stone-400">claims verified</span>
      </span>
      <span
        className={
          isClean(stats)
            ? "text-emerald-700 dark:text-emerald-400"
            : "text-amber-700 dark:text-amber-400"
        }
      >
        <strong className="tabular-nums">{unverifiablePercent(stats)}</strong> unverifiable
      </span>
      <span className="text-stone-500 dark:text-stone-400">{modelCallCount(stats)}</span>
    </div>
  );
}
