/**
 * How the usage and quality dashboard is worded (M5 slice 2).
 *
 * It lives in `lib/` for the reason `lib/evidence.ts` does: `web/` has vitest and no
 * DOM, so a rule expressed inside a component is a rule no test can reach. Everything
 * here is a pure function of the server's payload.
 *
 * The distinction this module exists to protect: **"we spent nothing" and "we do not
 * know what we spent" are different sentences, and only one of them is safe to render
 * as a number.** `cost_usd` is null when any call in a group has no known price, and
 * showing that as `$0.00` would be the same silent corruption as a stale price table —
 * a hazard `CLAUDE.md` names. Today every call is free-tier and genuinely costs 0.00,
 * which is exactly when the two are easiest to confuse and the confusion is invisible.
 */

import type {
  CallBucket,
  CallTotals,
  ParseOutcome,
  QualitySummary,
  UsageReport,
  UsageScope,
} from "@/lib/api";

/** What a figure reads as when the data cannot support one. */
export const UNKNOWN = "unknown";

/** What a figure reads as when there is simply nothing yet. */
export const NOTHING_YET = "—";

/**
 * Money, or an honest refusal to name it.
 *
 * Never returns "$0.00" for an unknown cost. That is the entire job.
 */
export function formatCost(totals: CallTotals): string {
  if (totals.cost_usd === null) return UNKNOWN;
  return `$${totals.cost_usd.toFixed(4)}`;
}

/**
 * Why a cost is unknown, in words, or null when it is not.
 *
 * A bare "unknown" invites the reader to assume a bug. Naming the rows behind it —
 * the organizing idea of this milestone — makes it a measurement instead.
 */
export function describeCostGap(totals: CallTotals): string | null {
  if (totals.cost_usd !== null) return null;
  const unpriced = totals.calls - totals.calls_priced;
  return `${unpriced} of ${totals.calls} ${totals.calls === 1 ? "call has" : "calls have"} no known price`;
}

/** Whether every call behind a figure carried a price. */
export function costIsComplete(totals: CallTotals): boolean {
  return totals.cost_usd !== null;
}

export function formatTokens(count: number): string {
  return count.toLocaleString("en-US");
}

/** Total tokens in and out. Cached input is counted in `input_tokens` already. */
export function totalTokens(totals: CallTotals): number {
  return totals.input_tokens + totals.output_tokens;
}

/** Mean latency, or a dash — the mean of zero calls is not zero. */
export function formatLatency(ms: number | null): string {
  if (ms === null) return NOTHING_YET;
  if (ms < 1000) return `${Math.round(ms)} ms`;
  return `${(ms / 1000).toFixed(1)} s`;
}

/**
 * The hallucination rate as a percentage, or a dash when no claims exist.
 *
 * `0.0%` over zero claims would read as "nothing was fabricated", which is a claim
 * about data that is not there — the same mistake as a cost of $0.00 for an unknown
 * price, one column over.
 */
export function formatRate(rate: number | null): string {
  if (rate === null) return NOTHING_YET;
  return `${(rate * 100).toFixed(1)}%`;
}

/** Whether a quality summary came through with nothing dropped. */
export function isClean(quality: QualitySummary): boolean {
  return quality.claims_dropped === 0;
}

/**
 * How many claims were refused, or null when none were.
 *
 * Here rather than inline in the component for the reason everything else is: the
 * first version read `${n} claims dropped` and rendered "1 claims dropped" on the
 * screen, which no test could see because the sentence lived inside JSX.
 */
export function droppedNote(quality: QualitySummary): string | null {
  const dropped = quality.claims_dropped;
  if (dropped === 0) return null;
  return `${formatTokens(dropped)} ${dropped === 1 ? "claim" : "claims"} dropped`;
}

const BUCKET_LABEL: Record<CallBucket, string> = {
  extraction: "Extracting profiles",
  judging: "Judging against requirements",
  unattributed: "Unattributed",
  ambiguous: "Ambiguous",
};

export function bucketLabel(bucket: CallBucket): string {
  return BUCKET_LABEL[bucket];
}

const BUCKET_NOTE: Record<CallBucket, string | null> = {
  extraction: "Billed to the resume — what it cost to read a document.",
  judging: "Billed to the screening — what it cost to judge one against a job.",
  unattributed:
    "These calls name neither a resume nor a screening, so nobody owns them. They are shown because a row that cannot be attributed would otherwise vanish from every total.",
  ambiguous:
    "These calls name both a resume and a screening, so they would be counted twice. Shown for the same reason as the row above.",
};

export function bucketNote(bucket: CallBucket): string | null {
  return BUCKET_NOTE[bucket];
}

/** The two buckets that should always be empty. Non-zero means an invariant slipped. */
export const UNEXPECTED_BUCKETS: CallBucket[] = ["unattributed", "ambiguous"];

/**
 * Whether every call could be attributed to the work that paid for it.
 *
 * `llm_call_logs` sets `resume_id` xor `screening_id`, but nothing enforces it — both
 * columns are nullable with no CHECK. So this can be false on real data, and when it
 * is, the reader needs to know before trusting any split below it.
 */
export function attributionIsClean(report: UsageReport): boolean {
  return UNEXPECTED_BUCKETS.every((bucket) => report.by_bucket[bucket].calls === 0);
}

/** The sentence to show when it is not clean, or null when it is. */
export function describeAttributionGap(report: UsageReport): string | null {
  if (attributionIsClean(report)) return null;
  const parts = UNEXPECTED_BUCKETS.filter((bucket) => report.by_bucket[bucket].calls > 0).map(
    (bucket) => `${report.by_bucket[bucket].calls} ${bucketLabel(bucket).toLowerCase()}`,
  );
  return `${parts.join(" and ")}. Every call should name exactly one of a resume or a screening.`;
}

/**
 * The buckets worth rendering: the two real ones always, the two anomalies only when
 * they are non-empty.
 *
 * Hiding an empty anomaly is not the same as hiding a blocked action — there is no
 * decision here for a reader to be confused by, and a permanent pair of zeroes trains
 * people to skip the row that matters on the day it is not zero.
 */
export function bucketsToShow(report: UsageReport): CallBucket[] {
  const always: CallBucket[] = ["extraction", "judging"];
  return [...always, ...UNEXPECTED_BUCKETS.filter((b) => report.by_bucket[b].calls > 0)];
}

const SCOPE_NOTE: Record<UsageScope, string> = {
  own: "Your own rows only — the documents you uploaded and the screenings your postings paid for.",
  all: "Every row in the system, because this account is an admin.",
};

export function scopeNote(scope: UsageScope): string {
  return SCOPE_NOTE[scope];
}

/** How many documents reached a verified profile, over how many are accounted for. */
export function parseSuccess(outcomes: ParseOutcome[]): { extracted: number; total: number } {
  const total = outcomes.reduce((sum, outcome) => sum + outcome.resumes, 0);
  const extracted = outcomes.find((outcome) => outcome.status === "extracted")?.resumes ?? 0;
  return { extracted, total };
}

/** Parse success as a percentage, or a dash when nothing has been uploaded. */
export function formatParseSuccess(outcomes: ParseOutcome[]): string {
  const { extracted, total } = parseSuccess(outcomes);
  if (total === 0) return NOTHING_YET;
  return `${((extracted / total) * 100).toFixed(0)}%`;
}

/** Whether the report has anything at all to show. */
export function isEmpty(report: UsageReport): boolean {
  return report.totals.calls === 0 && report.quality.profiles === 0;
}
