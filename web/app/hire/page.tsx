"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { AuthPanel } from "@/components/AuthPanel";
import { RequirementFields } from "@/components/RequirementFields";
import { Banner } from "@/components/ui/Banner";
import { Badge } from "@/components/ui/Badge";
import { MAX_REQUIREMENTS_PER_JOB, api, type Job, type RequirementInput } from "@/lib/api";
import { errorMessage, useAuth } from "@/lib/auth";
import { BLANK_REQUIREMENT } from "@/lib/requirements";
import { publicationNote } from "@/lib/screening";

export default function JobsPage() {
  const { session, ready, authenticate, authorized } = useAuth();
  const [jobs, setJobs] = useState<Job[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [drafts, setDrafts] = useState<RequirementInput[]>([{ ...BLANK_REQUIREMENT }]);

  /** Whether the last attempt to read the list failed, as opposed to not having
   *  finished. `jobs === null` alone could not tell those apart, so a failure left
   *  "Loading…" on screen forever with only a browser reload to recover. */
  const [loadFailed, setLoadFailed] = useState(false);

  const load = useCallback(async () => {
    // Cleared on every attempt: without this a banner from one transient failure
    // outlived every subsequent successful load.
    setError(null);
    setLoadFailed(false);
    try {
      setJobs(await authorized(() => api.listJobs()));
    } catch (caught) {
      setLoadFailed(true);
      setError(errorMessage(caught, "Could not load jobs"));
    }
  }, [authorized]);

  useEffect(() => {
    // A false positive: `load` is async and every `setState` in it runs after an
    // `await`, so nothing is set synchronously in this effect body — the rule's
    // analysis does not follow the await boundary. Fetch-on-mount is the job here.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    if (session) void load();
  }, [session, load]);

  async function create(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    setBusy(true);
    try {
      // A requirement with no label is a row the user started and abandoned, not a
      // requirement. The API would refuse it; dropping it here keeps the form usable.
      const requirements = drafts.filter((draft) => draft.label.trim() !== "");
      const job = await authorized(() =>
        api.createJob({ title, description: description.trim() || null, requirements }),
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
  if (!session) {
    return (
      <div className="mx-auto max-w-6xl px-5 py-10">
        <AuthPanel onAuthenticated={authenticate} />
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-6xl px-5 py-10">
      <header className="mb-8">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Jobs</h1>
          <p className="mt-1.5 max-w-xl text-sm text-ink-muted">
            A requirement is typed in, not decomposed out of a posting by a model — it is an
            input, not a claim about anyone. Candidates are then ranked by which of them their
            resumes can be quoted to prove.
          </p>
        </div>
      </header>

      {error && (
        <Banner tone="danger" className="mb-5">
          {error}
        </Banner>
      )}

      <form onSubmit={create} className="card mb-8 space-y-4 p-5">
        <h2 className="text-sm font-semibold">New job</h2>

        <input
          required
          value={title}
          onChange={(event) => setTitle(event.target.value)}
          placeholder="Job title"
          className="field"
        />
        <textarea
          value={description}
          onChange={(event) => setDescription(event.target.value)}
          placeholder="The posting as written (optional). Kept for context and audit — nobody is judged against it, because a verdict on free text cannot say which part of a posting it answered."
          rows={3}
          className="field"
        />

        <div className="space-y-2">
          {/* `gap` and `flex-wrap`, because at 375px the caption has to sit under the
              heading rather than beside it — with neither, the two ran together and
              the screen read "REQUIREMENTS1 of 30". Found in a browser at 375; a
              justify-between with no gap looks correct at every width that fits. */}
          <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
            <h3 className="text-micro font-medium uppercase tracking-wide text-ink-faint">
              Requirements
            </h3>
            <p className="text-micro tabular-nums text-ink-faint">
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
                className="ring-focus mt-1 inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-control text-sm text-ink-muted hover:text-dropped disabled:opacity-30"
              >
                ×
              </button>
            </div>
          ))}

          <button
            type="button"
            onClick={() => setDrafts((current) => [...current, { ...BLANK_REQUIREMENT }])}
            disabled={drafts.length >= MAX_REQUIREMENTS_PER_JOB}
            className="ring-focus rounded-control text-xs text-ink-muted underline-offset-2 hover:text-ink hover:underline disabled:opacity-40"
          >
            + Add a requirement
          </button>
        </div>

        <button
          type="submit"
          disabled={busy || title.trim() === ""}
          className="btn btn-primary ring-focus"
        >
          {busy ? "Creating…" : "Create job"}
        </button>
      </form>

      {jobs === null ? (
        // A list that has never loaded offers the retry. One that has stays on
        // screen and lets the banner above carry the failure — discarding a working
        // list over a transient blip helps nobody.
        loadFailed ? (
          <div className="flex items-center gap-3 rounded-card border border-line px-4 py-3 text-sm">
            <span className="text-ink-muted">The list of jobs could not be loaded.</span>
            <button
              type="button"
              onClick={() => void load()}
              className="btn btn-secondary ring-focus"
            >
              Try again
            </button>
          </div>
        ) : (
          <p className="text-sm text-ink-muted">Loading…</p>
        )
      ) : jobs.length === 0 ? (
        <p className="text-sm text-ink-muted">
          No jobs yet. Create one above, then screen your uploaded resumes against it.
        </p>
      ) : (
        <ul className="space-y-2">
          {jobs.map((job) => (
            <li key={job.id}>
              <Link
                href={`/hire/jobs/${job.id}`}
                className="ring-focus flex items-baseline justify-between gap-4 rounded-card border border-line bg-surface px-4 py-3 transition-colors hover:border-accent hover:bg-surface-sunken"
              >
                <span className="flex items-center gap-2 text-sm font-medium">
                  {job.title}
                  {/* Neutral, like every other workflow state: where a posting is
                      in its editorial life is not something the system found in a
                      document. The word carries it. */}
                  {job.status !== "published" ? (
                    <Badge tone="neutral" title={publicationNote(job.status)}>
                      {job.status}
                    </Badge>
                  ) : null}
                </span>
                <span className="text-xs text-ink-muted">
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
    </div>
  );
}
