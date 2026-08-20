"use client";

import { Evidence } from "@/components/Evidence";
import { Badge } from "@/components/ui/Badge";
import { Card, CardHeader } from "@/components/ui/Card";
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
export function JudgmentView({
  entry,
  resumeName,
}: {
  entry: RankedEntry;
  resumeName: string;
}) {
  return (
    <Card>
      <CardHeader
        title={resumeName}
        caption={
          <>
            {entry.requirements_met}/{entry.requirements_total} requirements evidenced
            {entry.must_haves_total > 0 && (
              <>
                {" · "}
                {/* A failed gate renders grey and says so in words. It is a fact
                    about what the posting asks for, not a warning about the person,
                    and amber here was the `ambiguous` hue spent on something that is
                    not ambiguous at all — docs/DESIGN.md §1. */}
                <span className={entry.gate_passed ? undefined : "text-ink-muted"}>
                  {entry.must_haves_met}/{entry.must_haves_total} must-have
                  {entry.gate_passed ? "" : " — gate not passed"}
                </span>
              </>
            )}
          </>
        }
        action={
          <span className="font-mono text-xs tabular-nums text-ink-muted">
            #{entry.rank} · {scorePercent(entry)}
          </span>
        }
      />

      {/* Motion 3 of `docs/DESIGN.md` §4: the verdicts land in list order with a
          short stagger, so a reader sees they were decided one requirement at a
          time rather than handed down as a block. That is the mechanism — each
          requirement is judged on its own quotes and its own verdict is derived
          from what resolved — and it is the kind of thing the screen would
          otherwise merely assert.

          The delay is capped, because a screening may carry thirty requirements
          and a strictly proportional stagger would make the last one arrive two
          seconds after the first. It is inline rather than a utility because the
          value is per-index; `animate-fade-up` carries the rest, and `both` in
          that recipe is what holds each row invisible until its turn.

          Not load-bearing: every row's resting state is the finished picture, and
          the block at the bottom of `globals.css` neutralises all of it under
          `prefers-reduced-motion`. */}
      <ul className="divide-y divide-line">
        {entry.requirements.map((requirement, index) => (
          <li
            key={requirement.requirement_id}
            className="animate-fade-up px-4 py-3"
            style={{ animationDelay: `${Math.min(index, 8) * 60}ms` }}
          >
            <RequirementRow requirement={requirement} />
          </li>
        ))}
      </ul>
    </Card>
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
            <Badge
              tone="neutral"
              className="ml-1.5 align-middle uppercase tracking-wide"
              title="A hard gate: missing it ranks this candidate below everyone who has them all."
            >
              must have
            </Badge>
          )}
        </p>
        {/* `cited` for a met verdict, because a met verdict *is* a located quote.
            Unevidenced is neutral rather than a tone of its own: the system is not
            saying anything about the candidate, and a colour here would be it
            saying something. */}
        <Badge tone={met ? "cited" : "neutral"} className="shrink-0">
          {met ? "Met" : "No citable evidence"}
        </Badge>
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
        <p className="mt-1 text-xs text-ink-muted">{NOT_EVIDENCED_EXPLANATION}</p>
      )}
    </>
  );
}
