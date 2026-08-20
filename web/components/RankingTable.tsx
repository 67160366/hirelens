"use client";

import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import type { Ranking } from "@/lib/api";
import { cn } from "@/lib/cn";
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
 *
 * **This file is where direction C's two rules were written from**, because it was
 * breaking both of them on the day the direction was chosen (`docs/DESIGN.md` §1):
 *
 *   * **A selected row is tinted `accent`, never `cited`.** It was
 *     `bg-emerald-50 dark:bg-emerald-500/10` — the hue reserved for "a quote the
 *     application located in the source document", spent on "you clicked this". Both
 *     appear in one viewport: the `Met` badges in the pane below are the real thing.
 *   * **A failed must-have gate is grey, never a warning colour.** It was
 *     `text-amber-700`, which is `ambiguous` — "a quote that matched in more than one
 *     place" — for something that is not ambiguous at all. A failed gate is a fact
 *     about the posting's requirements, not a warning about the person.
 *
 * **The score bar takes `accent`, and that is deliberate rather than convenient.**
 * The score is arithmetic over weights the recruiter typed (`pipeline/ranking.py`),
 * not a claim about the candidate — no model call produces it, and deleting it would
 * change no verdict — so it may wear the interface hue. The moment the gate fails the
 * number stops meaning "how well they rank", and the bar says so by losing its colour
 * rather than by turning red at somebody.
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
      <Card>
        <CardHeader
          title="Ranking"
          caption="Costs one query — adjusting a weight reorders this without re-judging anyone"
        />

        {ranking.ranked.length === 0 ? (
          <CardBody>
            <p className="text-sm text-ink-muted">
              Nothing ranked yet. Screen a resume against this job to see it here.
            </p>
          </CardBody>
        ) : (
          // Scrolls rather than clips. `overflow-hidden` on the card is what gives it
          // its rounded corners, and it was also cutting the Must-have column off
          // below ~640px — the hard gate that decides whether somebody ranks at all,
          // unreachable on a phone with no indication it was there.
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <caption className="sr-only">
                Candidates in ranked order. Choose a resume to read the requirement-level
                verdicts and the quotes behind them.
              </caption>
              <thead>
                <tr className="border-b border-line text-left text-micro uppercase tracking-wide text-ink-faint">
                  <th scope="col" className="px-4 py-2 font-medium">
                    #
                  </th>
                  <th scope="col" className="px-2 py-2 font-medium">
                    Resume
                  </th>
                  <th scope="col" className="px-2 py-2 font-medium">
                    Score
                  </th>
                  <th scope="col" className="px-2 py-2 font-medium">
                    Met
                  </th>
                  <th scope="col" className="px-4 py-2 font-medium">
                    Must-have
                  </th>
                </tr>
              </thead>
              <tbody>
                {ranking.ranked.map((entry) => {
                  const selected = entry.screening_id === selectedScreeningId;
                  return (
                    <tr
                      key={entry.screening_id}
                      onClick={() => onSelect(entry.screening_id)}
                      aria-current={selected ? "true" : undefined}
                      className={cn(
                        "cursor-pointer border-b border-line transition-colors last:border-0",
                        selected ? "bg-accent-wash" : "hover:bg-surface-sunken",
                      )}
                    >
                      <td className="px-4 py-2.5 font-mono text-xs tabular-nums text-ink-faint">
                        {entry.rank}
                      </td>
                      <td className="px-2 py-2.5 font-medium">
                        {/* The row keeps its click for the mouse; this is the only way
                            in from a keyboard. Everything the product is for — the
                            verdicts, the citations, the dropped claims, the document
                            pane — sits behind this one interaction, and it used to be
                            a bare row handler with no tabIndex and no key handler. */}
                        <button
                          type="button"
                          onClick={(event) => {
                            // Or the row's own handler fires straight after this one
                            // and `select` runs twice for one press.
                            event.stopPropagation();
                            onSelect(entry.screening_id);
                          }}
                          aria-expanded={selected}
                          className={cn(
                            "ring-focus rounded-control text-left underline-offset-2 hover:underline",
                            selected && "text-accent",
                          )}
                        >
                          {resumeLabel(entry)}
                        </button>
                      </td>
                      <td className="px-2 py-2.5">
                        <span className="font-mono text-xs tabular-nums">
                          {scorePercent(entry)}
                        </span>
                        {/* `aria-hidden` because the figure beside it already says
                            this, in a form a screen reader can use. The bar is what
                            makes a column of near-identical percentages scannable —
                            it is never the only signal. */}
                        <span
                          aria-hidden="true"
                          className="mt-1 block h-1 w-16 overflow-hidden rounded-full bg-surface-sunken"
                        >
                          <span
                            className={cn(
                              "block h-full rounded-full",
                              entry.gate_passed ? "bg-accent" : "bg-line-strong",
                            )}
                            style={{
                              width: `${Math.round(entry.score * 100)}%`,
                            }}
                          />
                        </span>
                      </td>
                      <td className="px-2 py-2.5 text-xs tabular-nums text-ink-muted">
                        {entry.requirements_met}/{entry.requirements_total}
                      </td>
                      <td className="px-4 py-2.5 text-xs">
                        {entry.must_haves_total === 0 ? (
                          <span className="text-ink-faint">—</span>
                        ) : entry.gate_passed ? (
                          <span className="tabular-nums text-ink-muted">
                            {entry.must_haves_met}/{entry.must_haves_total}
                          </span>
                        ) : (
                          <span
                            className="tabular-nums text-ink-muted"
                            title="Ranks below every candidate that has them all, however well it scores elsewhere."
                          >
                            {entry.must_haves_met}/{entry.must_haves_total} — gate not passed
                          </span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {ranking.excluded.length > 0 && (
        // Neutral, where this used to be an amber panel end to end. Amber is
        // `ambiguous`, which means one specific thing — a quote that matched in more
        // than one place — and a screening left behind by an edited requirement is not
        // that. The same correction the dropped-claims panel needed one slice earlier,
        // and the heading plus each row's own sentence carry the meaning without a hue.
        <Card>
          <CardHeader
            title={`Not in the ranking (${ranking.excluded.length})`}
            caption="Shown rather than hidden — a ranking that quietly mixed answers to two different questions would be meaningless"
          />

          <ul className="divide-y divide-line">
            {ranking.excluded.map((entry) => (
              <li
                key={entry.screening_id}
                className="flex items-start justify-between gap-4 px-4 py-3"
              >
                <div className="min-w-0">
                  <p className="flex items-center gap-2 text-sm font-medium">
                    {resumeLabel(entry)}
                    <Badge tone="neutral">{entry.reason}</Badge>
                  </p>
                  <p className="mt-0.5 text-xs text-ink-muted">{exclusionMessage(entry)}</p>
                </div>
                {entry.reason === "stale" && (
                  <Button
                    onClick={() => onScreenAgain(entry.resume_id)}
                    disabled={busyResumeId === entry.resume_id}
                    className="shrink-0"
                  >
                    {busyResumeId === entry.resume_id
                      ? "Screening…"
                      : "Screen again — 1 model call"}
                  </Button>
                )}
              </li>
            ))}
          </ul>
        </Card>
      )}
    </div>
  );
}
