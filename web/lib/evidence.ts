/**
 * How the guardrail's own evidence is worded to a user.
 *
 * Extraction and judging share one `DroppedClaim` shape and one hallucination rate
 * — `api/app/schemas/judgment.py` imports `DroppedClaim` and `EvidenceStats` from
 * `schemas/profile.py` rather than declaring its own, which is what makes the metric
 * cover judging for free. They share one vocabulary here for the same reason: a
 * second copy of these sentences is the one that drifts.
 *
 * It lives in `lib/` because `web/` has vitest and no DOM, so a label defined inside
 * a component is a label no test can reach. That is not hypothetical here — the
 * `unknown_requirement` wording sat in `ProfileView`'s private map for two
 * milestones, correct and unreachable, because only *judging* can produce that
 * reason and judging renders on a different screen.
 */

import type { DroppedClaim, EvidenceStats, RejectReason } from "@/lib/api";

/**
 * Why a claim could not be traced to the document.
 *
 * Typed as a total `Record`, so adding a reason to `RejectReason` fails the build
 * here rather than rendering `undefined` at somebody's screen.
 */
const REJECT_LABEL: Record<RejectReason, string> = {
  not_found: "no matching text in the document",
  too_short: "quote too short to identify a source",
  empty: "no quote supplied",
  // Judging's, and unreachable from an extraction: pointing at a requirement that
  // does not exist is the same class of claim as quoting text that is not there,
  // so it lands in the same `dropped` list and the same hallucination rate.
  unknown_requirement: "aimed at a requirement that does not exist",
};

/** Every reason the server can send, derived from the map so the two cannot diverge. */
export const REJECT_REASONS = Object.keys(REJECT_LABEL) as RejectReason[];

export function droppedReasonLabel(reason: RejectReason): string {
  return REJECT_LABEL[reason];
}

/**
 * The heading over the dropped claims.
 *
 * "Excluded" rather than "rejected" or "errors": these are claims the *system*
 * refused to repeat, not mistakes the candidate made. Nothing here is a statement
 * about a person, and the wording has to keep it that way.
 */
export function droppedPanelTitle(count: number): string {
  return `Excluded — could not be traced to the document (${count})`;
}

/** Why the panel exists at all: the alternative is discarding these in silence. */
export const DROPPED_PANEL_EXPLANATION =
  "The model asserted these, but the text it cited is not in the file. They are shown here rather than silently discarded.";

/** Whether a set of claims came through with nothing dropped. */
export function isClean(stats: EvidenceStats): boolean {
  return stats.dropped === 0;
}

/** The hallucination rate as a percentage, at the precision the metric is stored to. */
export function unverifiablePercent(stats: EvidenceStats): string {
  return `${(stats.hallucination_rate * 100).toFixed(1)}%`;
}

/**
 * How many model calls the result cost.
 *
 * `EvidenceStats.attempts` counts **model calls** — the re-ask loop's attempts.
 * `Screening.attempts` and `Resume.attempts` are the *job* counters and mean
 * something else entirely, so read this figure from the stats and never from the
 * row that happens to spell it the same way.
 */
export function modelCallCount(stats: EvidenceStats): string {
  return `${stats.attempts} model ${stats.attempts === 1 ? "call" : "calls"}`;
}

/** Nothing to report is not the same as nothing to say — the caller decides. */
export function hasDropped(dropped: DroppedClaim[] | undefined): boolean {
  return (dropped?.length ?? 0) > 0;
}
