"use client";

import { useCallback, useEffect, useState } from "react";

import { CountUp } from "@/components/CountUp";
import { Card } from "@/components/ui/Card";
import { cn } from "@/lib/cn";

import { AuthPanel } from "@/components/AuthPanel";
import { api, type CallBucket, type CallTotals, type UsageReport } from "@/lib/api";
import { errorMessage, useAuth } from "@/lib/auth";
import {
  bucketLabel,
  bucketNote,
  bucketsToShow,
  describeAttributionGap,
  describeCostGap,
  droppedNote,
  formatCost,
  formatLatency,
  formatParseSuccess,
  formatRate,
  formatTokens,
  isClean,
  isEmpty,
  parseSuccess,
  scopeNote,
  totalTokens,
} from "@/lib/metrics";

/**
 * The usage and quality dashboard (M5 slice 2).
 *
 * Every number here is a query over rows the system already wrote while doing its
 * work, and **nothing on this screen spends a model call** — refresh it as often as
 * you like. That is the milestone's organizing idea: cite your source, applied to
 * metrics.
 *
 * It was specified as a *cost* dashboard and respecified with the owner on 2026-08-15,
 * because there is no cost: every model maps to the free tier, so a cost screen would
 * have been a wall of zeroes that reads as a bug. The cost *rule* is still here in
 * full — an unknown price renders as "unknown" and never as $0.00 — waiting for the
 * day a paid provider lands.
 */
export default function MetricsPage() {
  const { session, ready, authenticate, authorized } = useAuth();
  const [report, setReport] = useState<UsageReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setReport(await authorized(() => api.getUsage()));
      setError(null);
    } catch (caught) {
      setError(errorMessage(caught, "Could not load your usage"));
    } finally {
      setLoading(false);
    }
  }, [authorized]);

  useEffect(() => {
    // A false positive: `load` is async and every `setState` in it runs after an
    // `await`, so nothing is set synchronously in this effect body.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    if (session) void load();
  }, [session, load]);

  if (!ready) return null;
  if (!session) {
    return (
      <div className="mx-auto max-w-4xl px-5 py-10">
        <AuthPanel onAuthenticated={authenticate} />
      </div>
    );
  }

  const attributionGap = report ? describeAttributionGap(report) : null;
  const costGap = report ? describeCostGap(report.totals) : null;

  return (
    <div className="mx-auto max-w-4xl px-5 py-10">
      <header className="mb-8 flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Usage and quality</h1>
          <p className="mt-1.5 text-sm text-ink-muted">
            Every figure is a query over rows already written. Reading this page costs a query
            and never a model call.
          </p>
          {report ? (
            <p className="mt-1 text-xs text-ink-muted">{scopeNote(report.scope)}</p>
          ) : null}
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <button
            type="button"
            onClick={() => void load()}
            disabled={loading}
            className="btn btn-secondary ring-focus"
          >
            {loading ? "Refreshing…" : "Refresh — free"}
          </button>
        </div>
      </header>

      {error ? (
        <p
          role="alert"
          className="mb-6 rounded-control border border-dropped/40 bg-dropped-wash p-3 text-sm text-dropped"
        >
          {error}
        </p>
      ) : null}

      {report === null ? (
        <p className="text-sm text-ink-muted">Loading…</p>
      ) : isEmpty(report) ? (
        <p className="card px-4 py-8 text-center text-sm text-ink-muted">
          Nothing to report yet. Upload a resume, or screen one against a job, and the figures
          will appear here.
        </p>
      ) : (
        <div className="space-y-8">
          {/* The anomaly banner comes first, because every split below it is only
              trustworthy if every call could be attributed. `resume_id` xor
              `screening_id` is a docstring rather than a constraint, so this can
              genuinely fire. */}
          {attributionGap ? (
            // `ambiguous`, and it earns it: an unattributed call is one the system
            // cannot say which document or screening it belongs to, so every split
            // below it is uncertain in exactly the way that token names.
            <p className="rounded-control border border-ambiguous/40 bg-ambiguous-wash p-3 text-sm text-ambiguous">
              <strong className="font-semibold">Some calls could not be attributed.</strong>{" "}
              {attributionGap}
            </p>
          ) : null}

          <section className="grid gap-3 sm:grid-cols-4">
            <Stat label="Model calls" value={formatTokens(report.totals.calls)} />
            <Stat label="Tokens" value={formatTokens(totalTokens(report.totals))} />
            <Stat label="Mean latency" value={formatLatency(report.totals.latency_ms_mean)} />
            <Stat
              label="Cost"
              value={formatCost(report.totals)}
              note={costGap}
              muted={costGap !== null}
            />
          </section>

          <Panel
            title="What the calls were for"
            caption="Extraction is billed to the resume, judging to the screening. Keeping them apart is what makes each separately answerable."
          >
            <ul className="divide-y divide-line">
              {bucketsToShow(report).map((bucket) => (
                <BucketRow key={bucket} bucket={bucket} totals={report.by_bucket[bucket]} />
              ))}
            </ul>
          </Panel>

          <Panel
            title="How well the guardrail held"
            caption="Produced on every document at no extra cost — verification already happens."
          >
            <div className="grid gap-3 px-4 py-3 sm:grid-cols-4">
              <Stat label="Profiles" value={formatTokens(report.quality.profiles)} bare />
              <Stat
                label="Claims verified"
                value={formatTokens(report.quality.claims_verified)}
                bare
              />
              <Stat
                label="Unverifiable"
                value={formatRate(report.quality.hallucination_rate)}
                bare
                tone={isClean(report.quality) ? "good" : "warn"}
                note={droppedNote(report.quality)}
              />
              <Stat
                label="Re-ask attempts"
                value={formatTokens(report.quality.extraction_attempts_total)}
                bare
              />
            </div>
          </Panel>

          <Panel
            title="Documents"
            caption={`${parseSuccess(report.parse_outcomes).extracted} of ${parseSuccess(report.parse_outcomes).total} reached a verified profile — ${formatParseSuccess(report.parse_outcomes)}.`}
          >
            <ul className="divide-y divide-line">
              {report.parse_outcomes.map((outcome) => (
                <li
                  key={outcome.status}
                  className="flex items-baseline justify-between px-4 py-2.5 text-sm"
                >
                  <span className="capitalize">{outcome.status.replace(/_/g, " ")}</span>
                  <span className="tabular-nums">{formatTokens(outcome.resumes)}</span>
                </li>
              ))}
            </ul>
          </Panel>

          <Panel
            title="By provider and prompt"
            caption="prompt_version is stored on every call so comparing prompt revisions is a query rather than guesswork."
          >
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="text-left text-micro uppercase tracking-wide text-ink-faint">
                  <tr className="border-b border-line">
                    <th className="px-4 py-2 font-medium">Provider / model</th>
                    <th className="px-4 py-2 font-medium">Prompt</th>
                    <th className="px-4 py-2 text-right font-medium">Calls</th>
                    <th className="px-4 py-2 text-right font-medium">In</th>
                    <th className="px-4 py-2 text-right font-medium">Out</th>
                    <th className="px-4 py-2 text-right font-medium">Mean</th>
                    <th className="px-4 py-2 text-right font-medium">Cost</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-line">
                  {report.by_group.map((group) => (
                    <tr
                      key={`${group.provider}-${group.model}-${group.prompt_version}-${group.bucket}`}
                    >
                      <td className="px-4 py-2">
                        {group.provider}
                        <span className="text-ink-faint"> / {group.model}</span>
                      </td>
                      <td className="px-4 py-2 font-mono text-xs">{group.prompt_version}</td>
                      <td className="px-4 py-2 text-right tabular-nums">
                        {group.totals.calls}
                      </td>
                      <td className="px-4 py-2 text-right tabular-nums">
                        {formatTokens(group.totals.input_tokens)}
                      </td>
                      <td className="px-4 py-2 text-right tabular-nums">
                        {formatTokens(group.totals.output_tokens)}
                      </td>
                      <td className="px-4 py-2 text-right tabular-nums">
                        {formatLatency(group.totals.latency_ms_mean)}
                      </td>
                      <td className="px-4 py-2 text-right tabular-nums">
                        {formatCost(group.totals)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Panel>
        </div>
      )}
    </div>
  );
}

function Stat({
  label,
  value,
  note,
  muted,
  bare,
  tone,
}: {
  label: string;
  value: string;
  note?: string | null;
  muted?: boolean;
  bare?: boolean;
  tone?: "good" | "warn";
}) {
  // `good` and `warn` were emerald and amber. They are `cited` and `dropped` now,
  // which is not a rename: this figure is the hallucination rate, and the two states
  // it has are exactly *a claim the application located* and *a claim it could not*.
  // Those are the tokens' own definitions, so here the meaning palette is being used
  // for what it is reserved for rather than borrowed for emphasis.
  const figureTone = tone === "warn" ? "dropped" : tone === "good" ? "cited" : "neutral";
  return (
    <div className={bare ? "" : "card px-4 py-3"}>
      <p className="text-xs text-ink-muted">{label}</p>
      <p
        className={cn(
          "mt-0.5 font-mono text-xl font-semibold tabular-nums",
          muted && "text-ink-faint",
          !muted && figureTone === "cited" && "text-cited",
          !muted && figureTone === "dropped" && "text-dropped",
        )}
      >
        {/* Motion 4. `CountUp` renders anything with no digits in it — `unknown`,
            `—` — exactly as given, which is what stops a refusal to state a figure
            from being animated into an assertion. */}
        <CountUp value={value} />
      </p>
      {note ? <p className="mt-0.5 text-xs text-ink-muted">{note}</p> : null}
    </div>
  );
}

function Panel({
  title,
  caption,
  children,
}: {
  title: string;
  caption?: string;
  children: React.ReactNode;
}) {
  return (
    <Card>
      <div className="border-b border-line px-4 py-3">
        <h2 className="text-section font-semibold">{title}</h2>
        {caption ? <p className="mt-0.5 text-xs text-ink-muted">{caption}</p> : null}
      </div>
      {children}
    </Card>
  );
}

function BucketRow({ bucket, totals }: { bucket: CallBucket; totals: CallTotals }) {
  const note = bucketNote(bucket);
  const costGap = describeCostGap(totals);
  return (
    <li className="px-4 py-3">
      <div className="flex items-baseline justify-between gap-4">
        <span className="text-sm font-medium">{bucketLabel(bucket)}</span>
        <span className="shrink-0 text-sm tabular-nums">
          {formatTokens(totals.calls)} {totals.calls === 1 ? "call" : "calls"}
          <span className="text-ink-faint">
            {" · "}
            {formatTokens(totalTokens(totals))} tokens
            {" · "}
            {formatLatency(totals.latency_ms_mean)}
            {" · "}
            {formatCost(totals)}
          </span>
        </span>
      </div>
      {note ? <p className="mt-0.5 text-xs text-ink-muted">{note}</p> : null}
      {costGap ? <p className="mt-0.5 text-xs text-ink-muted">{costGap}</p> : null}
    </li>
  );
}
