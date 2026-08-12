"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { AuthPanel } from "@/components/AuthPanel";
import { RequirementFields } from "@/components/RequirementFields";
import {
  MAX_REQUIREMENTS_PER_JOB,
  api,
  type Job,
  type RequirementInput,
} from "@/lib/api";
import { errorMessage, useAuth } from "@/lib/auth";
import { BLANK_REQUIREMENT } from "@/lib/requirements";

export default function JobsPage() {
  const { token, ready, authenticate, signOut, authorized } = useAuth();
  const [jobs, setJobs] = useState<Job[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [drafts, setDrafts] = useState<RequirementInput[]>([{ ...BLANK_REQUIREMENT }]);

  const load = useCallback(async () => {
    try {
      setJobs(await authorized((accessToken) => api.listJobs(accessToken)));
    } catch (caught) {
      setError(errorMessage(caught, "Could not load jobs"));
    }
  }, [authorized]);

  useEffect(() => {
    if (token) void load();
  }, [token, load]);

  async function create(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    setBusy(true);
    try {
      // A requirement with no label is a row the user started and abandoned, not a
      // requirement. The API would refuse it; dropping it here keeps the form usable.
      const requirements = drafts.filter((draft) => draft.label.trim() !== "");
      const job = await authorized((accessToken) =>
        api.createJob(
          { title, description: description.trim() || null, requirements },
          accessToken,
        ),
      );
      setJobs((current) => [job, ...(current ?? [])]);
      setTitle("");
      setDescription("");
      setDrafts([{ ...BLANK_REQUIREMENT }]);
    } catch (caught) {
      setError(errorMessage(caught, "Could not create the job"));
    } finally {
      setBusy(false);
    }
  }

  if (!ready) return null;
  if (!token) {
    return (
      <main className="mx-auto max-w-6xl px-5 py-12">
        <AuthPanel onAuthenticated={authenticate} />
      </main>
    );
  }

  return (
    <main className="mx-auto max-w-6xl px-5 py-12">
      <header className="mb-8 flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Jobs</h1>
          <p className="mt-1.5 max-w-xl text-sm text-stone-600 dark:text-stone-400">
            A requirement is typed in, not decomposed out of a posting by a model — it is
            an input, not a claim about anyone. Candidates are then ranked by which of
            them their resumes can be quoted to prove.
          </p>
        </div>
        <div className="flex flex-col items-end gap-2">
          <Link
            href="/"
            className="rounded-md border border-stone-300 px-3 py-1.5 text-xs font-medium hover:bg-stone-50 dark:border-stone-700 dark:hover:bg-stone-800"
          >
            ← Resumes
          </Link>
          <button
            type="button"
            onClick={signOut}
            className="text-xs text-stone-500 underline-offset-2 hover:underline dark:text-stone-400"
          >
            Sign out
          </button>
        </div>
      </header>

      {error && (
        <p className="mb-5 rounded-lg border border-red-300 bg-red-50 px-4 py-2.5 text-sm text-red-800 dark:border-red-900/60 dark:bg-red-950/30 dark:text-red-400">
          {error}
        </p>
      )}

      <form
        onSubmit={create}
        className="mb-8 space-y-4 rounded-lg border border-stone-200 bg-white p-5 dark:border-stone-800 dark:bg-stone-900"
      >
        <h2 className="text-sm font-semibold">New job</h2>

        <input
          required
          value={title}
          onChange={(event) => setTitle(event.target.value)}
          placeholder="Job title"
          className="w-full rounded-md border border-stone-300 bg-white px-3 py-2 text-sm outline-none focus:border-stone-500 dark:border-stone-700 dark:bg-stone-950"
        />
        <textarea
          value={description}
          onChange={(event) => setDescription(event.target.value)}
          placeholder="The posting as written (optional). Kept for context and audit — nobody is judged against it, because a verdict on free text cannot say which part of a posting it answered."
          rows={3}
          className="w-full rounded-md border border-stone-300 bg-white px-3 py-2 text-sm outline-none focus:border-stone-500 dark:border-stone-700 dark:bg-stone-950"
        />

        <div className="space-y-2">
          <div className="flex items-baseline justify-between">
            <h3 className="text-xs font-medium uppercase tracking-wide text-stone-400 dark:text-stone-500">
              Requirements
            </h3>
            <p className="text-[11px] text-stone-400 dark:text-stone-500">
              {drafts.length} of {MAX_REQUIREMENTS_PER_JOB} — the whole list travels in one
              judging prompt, which is why there is a cap
            </p>
          </div>

          {drafts.map((draft, index) => (
            <div key={index} className="flex items-start gap-2">
              <div className="flex-1">
                <RequirementFields
                  value={draft}
                  onChange={(next) =>
                    setDrafts((current) =>
                      current.map((item, at) => (at === index ? next : item)),
                    )
                  }
                />
              </div>
              <button
                type="button"
                onClick={() => setDrafts((current) => current.filter((_, at) => at !== index))}
                disabled={drafts.length === 1}
                aria-label="Remove requirement"
                className="mt-1 px-1.5 text-sm text-stone-400 hover:text-red-600 disabled:opacity-30 dark:hover:text-red-400"
              >
                ×
              </button>
            </div>
          ))}

          <button
            type="button"
            onClick={() => setDrafts((current) => [...current, { ...BLANK_REQUIREMENT }])}
            disabled={drafts.length >= MAX_REQUIREMENTS_PER_JOB}
            className="text-xs text-stone-500 underline-offset-2 hover:underline disabled:opacity-40 dark:text-stone-400"
          >
            + Add a requirement
          </button>
        </div>

        <button
          type="submit"
          disabled={busy || title.trim() === ""}
          className="rounded-md bg-stone-900 px-3 py-2 text-sm font-medium text-white disabled:opacity-50 dark:bg-stone-100 dark:text-stone-900"
        >
          {busy ? "Creating…" : "Create job"}
        </button>
      </form>

      {jobs === null ? (
        <p className="text-sm text-stone-500 dark:text-stone-400">Loading…</p>
      ) : jobs.length === 0 ? (
        <p className="text-sm text-stone-500 dark:text-stone-400">
          No jobs yet. Create one above, then screen your uploaded resumes against it.
        </p>
      ) : (
        <ul className="space-y-2">
          {jobs.map((job) => (
            <li key={job.id}>
              <Link
                href={`/jobs/${job.id}`}
                className="flex items-baseline justify-between gap-4 rounded-lg border border-stone-200 bg-white px-4 py-3 hover:border-stone-400 dark:border-stone-800 dark:bg-stone-900 dark:hover:border-stone-600"
              >
                <span className="text-sm font-medium">{job.title}</span>
                <span className="text-xs text-stone-500 dark:text-stone-400">
                  {job.requirements.length}{" "}
                  {job.requirements.length === 1 ? "requirement" : "requirements"}
                  {job.requirements.some((item) => item.must_have) &&
                    ` · ${job.requirements.filter((item) => item.must_have).length} must-have`}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </main>
  );
}
