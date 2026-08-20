import { Card } from "@/components/ui/Card";
import type { EvidenceStats } from "@/lib/api";
import { isClean, modelCallCount, unverifiablePercent } from "@/lib/evidence";
import { cn } from "@/lib/cn";

/**
 * The verification counters for one result — a profile or a judgment.
 *
 * The same bar serves both because the server produces one `EvidenceStats` for
 * both: judging reuses extraction's counters unchanged, which is what makes the
 * hallucination rate cover it for free (docs/HANDOFF.md §5).
 *
 * The unverifiable figure is `dropped`, not `ambiguous`. It counts claims the
 * system **refused**, and a screen can show both states at once — a citation that
 * matched in two places sits a few centimetres above this bar. Rendering them the
 * same amber made the product's two different answers look like one.
 */
export function EvidenceStatsBar({ stats }: { stats: EvidenceStats }) {
  return (
    <Card className="flex flex-wrap items-center gap-x-5 gap-y-2 px-4 py-3 text-sm">
      <span>
        <strong className="tabular-nums">
          {stats.verified}/{stats.total_claims}
        </strong>{" "}
        <span className="text-ink-muted">claims verified</span>
      </span>
      <span className={cn(isClean(stats) ? "text-cited" : "text-dropped")}>
        <strong className="tabular-nums">{unverifiablePercent(stats)}</strong> unverifiable
      </span>
      <span className="text-ink-muted">{modelCallCount(stats)}</span>
    </Card>
  );
}
