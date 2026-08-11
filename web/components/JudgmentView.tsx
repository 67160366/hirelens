"use client";

import { Evidence } from "@/components/Evidence";
import type { RankedEntry, RequirementJudgment } from "@/lib/api";
import { NOT_EVIDENCED_EXPLANATION, scorePercent } from "@/lib/screening";

/**
 * One candidate's verdicts, and the citations behind each one.
 *
 * Rendered from the **ranking entry**, never from `GET /screenings/{id}`'s stored
 * judgment. The stored JSON froze `must_have` and `weight` at judging time and
 * neither is part of the screening's fingerprint, so a weight edit leaves the
 * screening current while the stored numbers go quietly out of date. Ranking
 * re-keys both against the job's current requirements — reading them from the
 * detail route would make weight edits appear to do nothing, with no error and no
 * stale flag to notice it by.
 */
export function JudgmentView({ entry, resumeName }: { entry: RankedEntry; resumeName: string }) {
  return (
    <section className="rounded-lg border border-stone-200 bg-white dark:border-stone-800 dark:bg-stone-900">
      <header className="border-b border-stone-200 px-4 py-3 dark:border-stone-800">
        <div className="flex items-baseline justify-between gap-3">
          <h3 className="text-sm font-semibold">{resumeName}</h3>
          <span className="font-mono text-xs text-stone-500 dark:text-stone-400">
            #{entry.rank} · {scorePercent(entry)}
          </span>
        </div>
        <p className="mt-1 text-xs text-stone-500 dark:text-stone-400">
          {entry.requirements_met}/{entry.requirements_total} requirements evidenced
          {entry.must_haves_total > 0 && (
            <>
              {" · "}
              <span className={entry.gate_passed ? "" : "text-amber-600 dark:text-amber-500"}>
                {entry.must_haves_met}/{entry.must_haves_total} must-have
              </span>
            </>
          )}
        </p>
      </header>

      <ul className="divide-y divide-stone-100 dark:divide-stone-800">
        {entry.requirements.map((requirement) => (
          <li key={requirement.requirement_id} className="px-4 py-3">
            <RequirementRow requirement={requirement} />
          </li>
        ))}
      </ul>
    </section>
  );
}

function RequirementRow({ requirement }: { requirement: RequirementJudgment }) {
  const met = requirement.verdict === "met";

  return (
    <>
      <div className="flex items-baseline justify-between gap-3">
        <p className="text-sm font-medium">
          {requirement.label}
          {requirement.must_have && (
            <span
              className="ml-1.5 rounded bg-stone-200 px-1.5 py-0.5 align-middle text-[10px] font-medium uppercase tracking-wide text-stone-600 dark:bg-stone-800 dark:text-stone-400"
              title="A hard gate: missing it ranks this candidate below everyone who has them all."
            >
              must have
            </span>
          )}
        </p>
        <span
          className={`shrink-0 rounded px-1.5 py-0.5 text-[11px] font-medium ${
            met
              ? "bg-emerald-100 text-emerald-800 dark:bg-emerald-500/15 dark:text-emerald-300"
              : "bg-stone-100 text-stone-600 dark:bg-stone-800 dark:text-stone-400"
          }`}
        >
          {met ? "Met" : "No citable evidence"}
        </span>
      </div>

      {/* A met requirement is shown only because a quote for it was located in the
          document; an unevidenced one asserts nothing at all. The system cannot
          tell "the candidate lacks this" from "the resume does not mention it",
          so it says neither — see docs/HANDOFF.md §5. */}
      {met ? (
        requirement.evidence.map((reference, index) => (
          <Evidence key={index} reference={reference} />
        ))
      ) : (
        <p className="mt-1 text-xs text-stone-500 dark:text-stone-500">
          {NOT_EVIDENCED_EXPLANATION}
        </p>
      )}
    </>
  );
}
