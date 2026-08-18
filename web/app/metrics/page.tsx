"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

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
  const { session, ready, authenticate, signOut, authorized } = useAuth();
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
      <main className="mx-auto max-w-4xl px-5 py-12">
        <AuthPanel onAuthenticated={authenticate} />
      </main>
    );
  }

  const attributionGap = report ? describeAttributionGap(report) : null;
  const costGap = report ? describeCostGap(report.totals) : null;

  return (
    <main className="mx-auto max-w-4xl px-5 py-12">
      <header className="mb-8 flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Usage and quality</h1>
          <p className="mt-1.5 text-sm text-stone-600 dark:text-stone-400">
            Every figure is a query over rows already written. Reading this page costs a
            query and never a model call.
          </p>
          {report ? (
            <p className="mt-1 text-xs text-stone-500 dark:text-stone-400">
              {scopeNote(report.scope)}
            </p>
          ) : null}
        </div>
        <div className="flex shrink-0 flex-col items-end gap-2">
          <Link
            href="/"
            className="rounded-md border border-stone-300 px-3 py-1.5 text-xs font-medium hover:bg-stone-50 dark:border-stone-700 dark:hover:bg-stone-800"
          >
            ← Resumes
          </Link>
          <button
            type="button"
            onClick={() => void load()}
            disabled={loading}
            className="rounded-md border border-stone-300 px-3 py-1.5 text-xs font-medium hover:bg-stone-50 disabled:opacity-50 dark:border-stone-700 dark:hover:bg-stone-800"
          >
            {loading ? "Refreshing…" : "Refresh — free"}
          </button>
          <button
            type="button"
            onClick={() => void signOut()}
            className="text-xs text-stone-500 underline dark:text-stone-400"
          >
            Sign out
          </button>
        </div>
      </header>

      {error ? (
        <p
          role="alert"
          className="mb-6 rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-800 dark:border-red-900 dark:bg-red-950 dark:text-red-200"
        >
          {error}
        </p>
      ) : null}

      {report === null ? (
        <p className="text-sm text-stone-500 dark:text-stone-400">Loading…</p>
      ) : isEmpty(report) ? (
        <p className="rounded-lg border border-stone-200 bg-white px-4 py-8 text-center text-sm text-stone-500 dark:border-stone-800 dark:bg-stone-900 dark:text-stone-400">
          Nothing to report yet. Upload a resume, or screen one against a job, and the
          figures will appear here.
        </p>
      ) : (
        <div className="space-y-8">
          {/* The anomaly banner comes first, because every split below it is only
              trustworthy if every call could be attributed. `resume_id` xor
              `screening_id` is a docstring rather than a constraint, so this can
              genuinely fire. */}
          {attributionGap ? (
            <p className="rounded-md border border-amber-300 bg-amber-50/70 p-3 text-sm text-amber-900 dark:border-amber-900/60 dark:bg-amber-950/30 dark:text-amber-300">
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
            <ul className="divide-y divide-stone-100 dark:divide-stone-800">
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
            <ul className="divide-y divide-stone-100 dark:divide-stone-800">
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
                <thead className="text-left text-xs uppercase tracking-wide text-stone-500 dark:text-stone-400">
                  <tr className="border-b border-stone-200 dark:border-stone-800">
                    <th className="px-4 py-2 font-medium">Provider / model</th>
                    <th className="px-4 py-2 font-medium">Prompt</th>
                    <th className="px-4 py-2 text-right font-medium">Calls</th>
                    <th className="px-4 py-2 text-right font-medium">In</th>
                    <th className="px-4 py-2 text-right font-medium">Out</th>
                    <th className="px-4 py-2 text-right font-medium">Mean</th>
                    <th className="px-4 py-2 text-right font-medium">Cost</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-stone-100 dark:divide-stone-800">
                  {report.by_group.map((group) => (
                    <tr key={`${group.provider}-${group.model}-${group.prompt_version}-${group.bucket}`}>
                      <td className="px-4 py-2">
                        {group.provider}
                        <span className="text-stone-400 dark:text-stone-500"> / {group.model}</span>
                      </td>
                      <td className="px-4 py-2 font-mono text-xs">{group.prompt_version}</td>
                      <td className="px-4 py-2 text-right tabular-nums">{group.totals.calls}</td>
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
    </main>
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
  const toneClass =
    tone === "warn"
      ? "text-amber-700 dark:text-amber-400"
      : tone === "good"
        ? "text-emerald-700 dark:text-emerald-400"
        : "";
  return (
    <div
      className={
        bare
          ? ""
          : "rounded-lg border border-stone-200 bg-white px-4 py-3 dark:border-stone-800 dark:bg-stone-900"
      }
    >
      <p className="text-xs text-stone-500 dark:text-stone-400">{label}</p>
      <p
        className={`mt-0.5 text-xl font-semibold tabular-nums ${muted ? "text-stone-400 dark:text-stone-500" : toneClass}`}
      >
        {value}
      </p>
      {note ? <p className="mt-0.5 text-xs text-stone-500 dark:text-stone-400">{note}</p> : null}
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
    <section className="rounded-lg border border-stone-200 bg-white dark:border-stone-800 dark:bg-stone-900">
      <div className="border-b border-stone-200 px-4 py-3 dark:border-stone-800">
        <h2 className="text-sm font-semibold">{title}</h2>
        {caption ? (
          <p className="mt-0.5 text-xs text-stone-500 dark:text-stone-400">{caption}</p>
        ) : null}
      </div>
      {children}
    </section>
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
          <span className="text-stone-400 dark:text-stone-500">
            {" · "}
            {formatTokens(totalTokens(totals))} tokens
            {" · "}
            {formatLatency(totals.latency_ms_mean)}
            {" · "}
            {formatCost(totals)}
          </span>
        </span>
      </div>
      {note ? <p className="mt-0.5 text-xs text-stone-500 dark:text-stone-400">{note}</p> : null}
      {costGap ? (
        <p className="mt-0.5 text-xs text-stone-500 dark:text-stone-400">{costGap}</p>
      ) : null}
    </li>
  );
}
