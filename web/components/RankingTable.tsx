"use client";

import type { Ranking } from "@/lib/api";
import { exclusionMessage, resumeLabel, scorePercent } from "@/lib/screening";

/**
 * A job's candidates in order, and the ones that could not take part.
 *
 * `excluded` is a section of its own rather than something the table filters away.
 * A stale screening drops out of the ranked list on purpose — it answers an older
 * set of requirements — and a UI that silently omitted it would recreate exactly
 * the confusion the list exists to prevent (docs/HANDOFF.md §9).
 *
 * The whole thing is recomputed from one query. No model call is involved, so a
 * caller may re-fetch it on every weight edit without spending anything.
 */
export function RankingTable({
  ranking,
  selectedScreeningId,
  onSelect,
  onScreenAgain,
  busyResumeId,
}: {
  ranking: Ranking;
  selectedScreeningId: string | null;
  onSelect: (screeningId: string) => void;
  onScreenAgain: (resumeId: string) => void;
  busyResumeId: string | null;
}) {
  return (
    <div className="space-y-5">
      <section className="overflow-hidden rounded-lg border border-stone-200 bg-white dark:border-stone-800 dark:bg-stone-900">
        <header className="flex items-baseline justify-between gap-3 border-b border-stone-200 px-4 py-2.5 dark:border-stone-800">
          <h2 className="text-sm font-semibold">Ranking</h2>
          <p className="text-[11px] text-stone-400 dark:text-stone-500">
            Costs one query — adjusting a weight reorders this without re-judging anyone
          </p>
        </header>

        {ranking.ranked.length === 0 ? (
          <p className="px-4 py-4 text-sm text-stone-500 dark:text-stone-400">
            Nothing ranked yet. Screen a resume against this job to see it here.
          </p>
        ) : (
          // Scrolls rather than clips. `overflow-hidden` on the section is what gives
          // the card its rounded corners, and it was also cutting the Must-have column
          // off below ~640px — the hard gate that decides whether somebody ranks at
          // all, unreachable on a phone with no indication it was there.
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <caption className="sr-only">
                Candidates in ranked order. Choose a resume to read the requirement-level
                verdicts and the quotes behind them.
              </caption>
              <thead>
                <tr className="border-b border-stone-100 text-left text-[11px] uppercase tracking-wide text-stone-400 dark:border-stone-800 dark:text-stone-500">
                  <th scope="col" className="px-4 py-2 font-medium">#</th>
                  <th scope="col" className="px-2 py-2 font-medium">Resume</th>
                  <th scope="col" className="px-2 py-2 font-medium">Score</th>
                  <th scope="col" className="px-2 py-2 font-medium">Met</th>
                  <th scope="col" className="px-4 py-2 font-medium">Must-have</th>
                </tr>
              </thead>
              <tbody>
                {ranking.ranked.map((entry) => (
                  <tr
                    key={entry.screening_id}
                    onClick={() => onSelect(entry.screening_id)}
                    aria-current={entry.screening_id === selectedScreeningId ? "true" : undefined}
                    className={`cursor-pointer border-b border-stone-100 last:border-0 dark:border-stone-800 ${
                      entry.screening_id === selectedScreeningId
                        ? "bg-emerald-50 dark:bg-emerald-500/10"
                        : "hover:bg-stone-50 dark:hover:bg-stone-800/60"
                    }`}
                  >
                    <td className="px-4 py-2.5 font-mono text-xs text-stone-400">{entry.rank}</td>
                    <td className="px-2 py-2.5 font-medium">
                      {/* The row keeps its click for the mouse; this is the only way in
                          from a keyboard. Everything the product is for — the verdicts,
                          the citations, the dropped claims, the document pane — sits
                          behind this one interaction, and it used to be a bare
                          `<tr onClick>` with no tabIndex and no key handler. */}
                      <button
                        type="button"
                        onClick={(event) => {
                          // Or the row's own handler fires straight after this one and
                          // `select` runs twice for one press.
                          event.stopPropagation();
                          onSelect(entry.screening_id);
                        }}
                        aria-expanded={entry.screening_id === selectedScreeningId}
                        className="rounded-sm text-left underline-offset-2 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-stone-500"
                      >
                        {resumeLabel(entry)}
                      </button>
                    </td>
                    <td className="px-2 py-2.5 font-mono text-xs">{scorePercent(entry)}</td>
                    <td className="px-2 py-2.5 text-xs text-stone-600 dark:text-stone-400">
                      {entry.requirements_met}/{entry.requirements_total}
                    </td>
                    <td className="px-4 py-2.5 text-xs">
                      {entry.must_haves_total === 0 ? (
                        <span className="text-stone-400 dark:text-stone-500">—</span>
                      ) : entry.gate_passed ? (
                        <span className="text-emerald-700 dark:text-emerald-400">
                          {entry.must_haves_met}/{entry.must_haves_total}
                        </span>
                      ) : (
                        <span
                          className="text-amber-700 dark:text-amber-500"
                          title="Ranks below every candidate that has them all, however well it scores elsewhere."
                        >
                          {entry.must_haves_met}/{entry.must_haves_total} — gate not passed
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {ranking.excluded.length > 0 && (
        <section className="rounded-lg border border-amber-300 bg-amber-50 dark:border-amber-900/60 dark:bg-amber-950/20">
          <header className="border-b border-amber-200 px-4 py-2.5 dark:border-amber-900/60">
            <h2 className="text-sm font-semibold text-amber-900 dark:text-amber-300">
              Not in the ranking ({ranking.excluded.length})
            </h2>
            <p className="mt-0.5 text-[11px] text-amber-800/80 dark:text-amber-400/80">
              Shown rather than hidden — a ranking that quietly mixed answers to two
              different questions would be meaningless
            </p>
          </header>

          <ul className="divide-y divide-amber-200 dark:divide-amber-900/60">
            {ranking.excluded.map((entry) => (
              <li
                key={entry.screening_id}
                className="flex items-start justify-between gap-4 px-4 py-3"
              >
                <div>
                  <p className="text-sm font-medium text-amber-900 dark:text-amber-300">
                    {resumeLabel(entry)}
                  </p>
                  <p className="mt-0.5 text-xs text-amber-800/90 dark:text-amber-400/90">
                    {exclusionMessage(entry)}
                  </p>
                </div>
                {entry.reason === "stale" && (
                  <button
                    type="button"
                    onClick={() => onScreenAgain(entry.resume_id)}
                    disabled={busyResumeId === entry.resume_id}
                    className="shrink-0 rounded-md bg-amber-900 px-3 py-1 text-xs font-medium text-white disabled:opacity-50 dark:bg-amber-200 dark:text-amber-950"
                  >
                    {busyResumeId === entry.resume_id ? "Screening…" : "Screen again — 1 model call"}
                  </button>
                )}
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
