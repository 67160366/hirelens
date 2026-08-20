/**
 * The judgment-shaped logic the ranking screen runs on.
 *
 * Pure functions in their own module so they can be tested without a DOM. `web/`
 * has vitest and no React testing library, and `npm test` needing no browser is the
 * same property the Python suite protects by running without a server — worth
 * keeping rather than trading for component tests nobody asked for.
 */

import type {
  EvidenceRef,
  ExcludedEntry,
  RankedEntry,
  RequirementJudgment,
  RequirementPatch,
  ScreeningStatus,
} from "@/lib/api";

/**
 * Editing one of these makes every existing screening stale.
 *
 * They are exactly what the judge was shown — `requirements_fingerprint` on the
 * server hashes kind, label, detail and their order. `must_have` and `weight` are
 * absent on purpose: they never reach the prompt, they are ranking's inputs, and
 * excluding them is what lets a weight edit reorder the list without re-billing a
 * single screening (docs/HANDOFF.md §5).
 */
export const STALENING_FIELDS = ["kind", "label", "detail"] as const;

/** Whether a pending edit will invalidate the screenings that already ran. */
export function makesScreeningsStale(patch: RequirementPatch): boolean {
  return STALENING_FIELDS.some((field) => field in patch);
}

/**
 * Every citation behind one candidate's verdicts, for the document pane.
 *
 * Filtered on the **verdict**, not just flattened. The server derives `met` from
 * what it could locate and sends an empty list otherwise, so on the contract the
 * two are the same thing — but this side did not build that JSON, and the rule it
 * has to keep is that nothing is highlighted unless it produced a verdict. Reading
 * the verdict makes that local and checkable here rather than assumed of upstream;
 * flattening blindly would be correct only for as long as the payload is.
 */
export function collectJudgmentEvidence(requirements: RequirementJudgment[]): EvidenceRef[] {
  return requirements
    .filter((requirement) => requirement.verdict === "met")
    .flatMap((requirement) => requirement.evidence);
}

/** How a verdict is worded to a user. */
export function verdictLabel(requirement: RequirementJudgment): string {
  return requirement.verdict === "met" ? "Met" : "No citable evidence";
}

/**
 * Why a `not_evidenced` requirement is not a claim about the candidate.
 *
 * The system cannot tell "the candidate lacks this" from "the resume does not
 * mention it", so it says neither. This string is the `not_met` refusal
 * (docs/HANDOFF.md §5) reaching the screen, and softening it into "does not have"
 * would turn the product into a scoring system whose numbers nobody can check.
 */
export const NOT_EVIDENCED_EXPLANATION =
  "Nothing in this resume could be quoted to show it. That is not the same as the candidate lacking it.";

/** Why a screening is not in the ranked list, in the user's terms. */
export function exclusionMessage(entry: ExcludedEntry): string {
  switch (entry.reason) {
    case "stale":
      return "The requirements changed after this ran, so it answers an older question. Screen it again to bring it back.";
    case "not_completed":
      return NOT_COMPLETED_MESSAGES[entry.status] ?? `Not finished — status is ${entry.status}.`;
    case "malformed":
      return "The stored result does not line up with the job's current requirements, so it was left out rather than matched against the wrong ones.";
  }
}

const NOT_COMPLETED_MESSAGES: Record<string, string> = {
  pending: "Queued — waiting for a worker.",
  processing: "Being judged right now.",
  failed: "This screening cannot be produced. Check the reason on the screening itself.",
  dead_lettered: "Stopped after retrying. Worth replaying once the cause is fixed.",
};

/**
 * What to call the resume behind a ranking entry.
 *
 * The name is **served** on the entry (`api/app/schemas/ranking.py`) rather than
 * joined client-side against `GET /resumes`, which returns only the caller's own
 * uploads — a join that is correct right up to the moment an applicant's resume
 * enters the ranking, and then quietly answers an id prefix instead. A null is
 * shortened to an id rather than invented: an id is visibly not a filename, so
 * nothing downstream mistakes it for one. `canRenderOriginal` then declines the
 * original-document tab for it, which is the failing-closed behaviour it was
 * written for.
 */
export function resumeLabel(entry: RankedEntry | ExcludedEntry): string {
  return entry.resume_filename ?? entry.resume_id.slice(0, 8);
}

/** The weighted share of requirements met, as a percentage for display. */
export function scorePercent(entry: RankedEntry): string {
  return `${(entry.score * 100).toFixed(1)}%`;
}

/**
 * How many screenings a stalening edit would actually cost to reproduce.
 *
 * Not `screenings.length`. `GET /jobs/{id}/screenings` is the *raw* list and its
 * docstring says so — "including the ones still running and the ones that failed"
 * (`api/app/api/routes/screenings.py:275-277`) — so the plain count includes rows
 * that have spent no model call and rows that never produced a result. The
 * confirmation built on it says "N screenings become stale and have to be run
 * again — one model call each", and only a **completed** screening holds a result
 * that a requirement edit invalidates and that a re-run would have to buy back.
 *
 * A number in this product is a claim, and this one was over-counting the price of
 * a destructive action. Its own module rather than inline in the page for the
 * reason `droppedNote` is: a sentence built in JSX is somewhere `web/`'s no-DOM
 * vitest cannot reach, and that is exactly how "1 claims dropped" shipped.
 */
export function countCompletedScreenings(screenings: readonly { status: ScreeningStatus }[]): number {
  return screenings.filter((screening) => screening.status === "completed").length;
}
