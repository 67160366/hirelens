/**
 * The application-shaped logic the journey screens run on.
 *
 * Pure functions in their own module, the same call `lib/screening.ts` makes: `web/`
 * has vitest and no React testing library, and `npm test` needing no browser is the
 * same property the Python suite protects by running without a server.
 *
 * **What this module is not.** It does not decide whether a move is allowed — the
 * server does, in `app/applications.py`, and it answers 409 with a sentence written
 * for a person. Duplicating those rules here would create a second place for them to
 * be wrong, and the client's copy would be the one nobody notices drifting. What
 * lives here is which buttons to *offer*, which is a different question: offering a
 * move the server will refuse is a bad afternoon, whereas re-deciding whether a
 * shortlist has evidence behind it is how a guarantee gets quietly forked.
 */

import type { Application, ApplicationEvent, ApplicationState, Role } from "@/lib/api";

/** No further move is possible from here, for anyone. */
export const TERMINAL_STATES: readonly ApplicationState[] = ["rejected", "withdrawn"];

export function isTerminal(state: ApplicationState): boolean {
  return TERMINAL_STATES.includes(state);
}

/** What each state means, in the applicant's terms rather than the schema's. */
export const STATE_LABELS: Record<ApplicationState, string> = {
  applied: "Applied",
  screening: "Being screened",
  screened: "Screened",
  shortlisted: "Shortlisted",
  rejected: "Not proceeding",
  withdrawn: "Withdrawn",
};

/**
 * The one line of explanation each state deserves.
 *
 * `screened` says what it does and does not mean on purpose: a completed screening
 * is evidence to read, not a decision anyone has made.
 */
export const STATE_EXPLANATIONS: Record<ApplicationState, string> = {
  applied: "Waiting for the employer to screen it.",
  screening: "A screening is running. Nobody has looked yet.",
  screened: "There are cited verdicts to read. No decision has been made.",
  shortlisted: "The employer wants to take this further.",
  rejected: "The employer decided against it, with a reason.",
  withdrawn: "You took this out of consideration.",
};

/** A move the UI is willing to offer, and what to call it. */
export interface Move {
  to: ApplicationState;
  label: string;
  /** The server refuses this one without a reason, so the form has to ask for it. */
  needsReason: boolean;
  /** Shown instead of the button when the move is not available yet, and why. */
  blockedBecause?: string;
}

/**
 * Which moves to put in front of this viewer, for an application in this state.
 *
 * Mirrors the server's table rather than reimplementing its reasoning — the two
 * guarantees it will not let you skip (a shortlist rests on a screening, a rejection
 * carries a reason) are enforced there and only *surfaced* here. When they disagree,
 * the server wins and the 409 says so.
 *
 * `shortlisted` is returned **blocked rather than hidden** before a screening. A
 * missing button is indistinguishable from a bug; a disabled one that says why is
 * the thing that teaches somebody the rule.
 */
export function availableMoves(
  application: Application,
  viewer: { id: string; role: Role },
  jobOwnerId: string | null,
): Move[] {
  if (isTerminal(application.state)) return [];

  const isApplicant = application.candidate_id === viewer.id;
  const isOwner = jobOwnerId !== null && jobOwnerId === viewer.id;
  // Matches `Actor.of`: owning the job is the wider role, and an admin holds it.
  const asOwner = isOwner || viewer.role === "admin";

  if (asOwner) {
    const moves: Move[] = [];
    if (application.state === "screened") {
      moves.push({ to: "shortlisted", label: "Shortlist", needsReason: false });
    } else {
      moves.push({
        to: "shortlisted",
        label: "Shortlist",
        needsReason: false,
        blockedBecause:
          "Screen this candidate first, so the decision rests on cited evidence.",
      });
    }
    moves.push({ to: "rejected", label: "Reject", needsReason: true });
    return moves;
  }

  if (isApplicant) {
    return [{ to: "withdrawn", label: "Withdraw", needsReason: false }];
  }
  return [];
}

/**
 * One line describing an entry in the log, for a reader rather than an auditor.
 *
 * The system's moves say so. Attributing them to a person would be a small lie in
 * the one place that exists to be accurate about who did what.
 */
export function describeEvent(event: ApplicationEvent): string {
  const to = STATE_LABELS[event.to_state].toLowerCase();
  const who = event.actor_id === null ? "The system" : actorName(event.actor_role);
  if (event.from_state === null) return `${who} applied`;
  return `${who} moved it to ${to}`;
}

function actorName(role: Role | null): string {
  if (role === "recruiter" || role === "admin") return "The employer";
  if (role === "candidate") return "The candidate";
  return "Someone";
}

/**
 * Whether this entry rests on a screening, which is what makes it checkable.
 *
 * Surfaced because "shortlisted" with nothing behind it is exactly the unaccountable
 * claim the event log exists to prevent — so the log should show that there *is*
 * something behind it.
 */
export function restsOnEvidence(event: ApplicationEvent): boolean {
  return event.screening_id !== null;
}

/** Applications grouped by state, in the order a recruiter reads them. */
export const PIPELINE_ORDER: readonly ApplicationState[] = [
  "screened",
  "shortlisted",
  "applied",
  "screening",
  "rejected",
  "withdrawn",
];

export function groupByState(
  applications: Application[],
): { state: ApplicationState; applications: Application[] }[] {
  return PIPELINE_ORDER.map((state) => ({
    state,
    applications: applications.filter((application) => application.state === state),
  })).filter((group) => group.applications.length > 0);
}
