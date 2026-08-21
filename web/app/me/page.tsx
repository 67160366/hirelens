"use client";

import { useCallback, useEffect, useState } from "react";

import { ApplicationActions } from "@/components/ApplicationActions";
import { ApplicationTimeline } from "@/components/ApplicationTimeline";
import { AuthPanel } from "@/components/AuthPanel";
import { Badge } from "@/components/ui/Badge";
import {
  api,
  type Account,
  type Application,
  type ApplicationEvent,
  type ApplicationState,
  type Job,
  type Resume,
} from "@/lib/api";
// One neutral tone for every state, which is the decision here.
//
// They were emerald for shortlisted, amber for screening and sky for applied — two of
// the three colours `docs/DESIGN.md` §1 reserves for what the system says about a
// **document**, plus a hue that is not in the palette at all. An application's state
// is a position in a workflow about a person, not a verdict on evidence, and the green
// one was the sharpest: a green `shortlisted` beside the green `Met` badges of the
// screening that justified it says the two are the same kind of claim. They are not —
// one is a decision somebody made, the other is a quote the application located.
//
// Nothing is lost by it. The list is grouped under a heading per state and each row
// carries `STATE_EXPLANATIONS` beside the label, so the tone was reinforcing something
// the reader had already been told twice.
import { STATE_EXPLANATIONS, STATE_LABELS, isTerminal } from "@/lib/applications";
import { errorMessage, useAuth } from "@/lib/auth";

/**
 * The candidate's half of M4: apply to a posting, and watch what happens to it.
 *
 * The screen the milestone was for. Everything here already worked over HTTP after
 * slice 3, and a state machine nobody can see is the situation M3 slice 5 was
 * written to stop repeating.
 */
export default function ApplicationsPage() {
  const { session, ready, authenticate, authorized } = useAuth();
  const [me, setMe] = useState<Account | null>(null);
  const [applications, setApplications] = useState<Application[]>([]);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [resumes, setResumes] = useState<Resume[]>([]);
  const [openId, setOpenId] = useState<string | null>(null);
  /**
   * The audit log, **keyed by the application it belongs to**.
   *
   * It used to be one array for the whole page. `openHistory` sets `openId`
   * synchronously and then awaits, so between those two the newly opened row was
   * already rendering the *previous* row's timeline — and a failed request left it
   * there permanently, because the catch never cleared it. That put one person's
   * rejection reason under another person's job title, in the one artefact whose
   * whole purpose is saying who decided what and on what evidence.
   *
   * Keyed by id, a row can only ever render its own log or nothing at all.
   */
  const [events, setEvents] = useState<Record<string, ApplicationEvent[]>>({});
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const [account, mine, allJobs, myResumes] = await authorized(async () =>
        Promise.all([api.me(), api.listMyApplications(), api.listJobs(), api.listResumes()]),
      );
      setMe(account);
      setApplications(mine);
      setJobs(allJobs);
      setResumes(myResumes);
    } catch (caught) {
      setError(errorMessage(caught, "Could not load your applications"));
    }
  }, [authorized]);

  useEffect(() => {
    // A false positive: `load` is async and every `setState` in it runs after an
    // `await`, so nothing is set synchronously in this effect body — the rule's
    // analysis does not follow the await boundary. Fetch-on-mount is the job here.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    if (session) void load();
  }, [session, load]);

  async function openHistory(applicationId: string) {
    if (openId === applicationId) {
      setOpenId(null);
      return;
    }
    setOpenId(applicationId);
    try {
      const loaded = await authorized(() => api.listApplicationEvents(applicationId));
      setEvents((current) => ({ ...current, [applicationId]: loaded }));
    } catch (caught) {
      // Dropped rather than left stale: an empty slot renders "Loading the
      // history…", which is honest, where the previous occupant's log is not.
      setEvents((current) => {
        const next = { ...current };
        delete next[applicationId];
        return next;
      });
      setError(errorMessage(caught, "Could not load the history"));
    }
  }

  async function apply(jobId: string, resumeId: string) {
    setError(null);
    setBusy(true);
    try {
      await authorized(() => api.applyToJob(jobId, resumeId));
      await load();
    } catch (caught) {
      setError(errorMessage(caught, "Could not apply"));
    } finally {
      setBusy(false);
    }
  }

  async function move(applicationId: string, to: ApplicationState, reason?: string) {
    setError(null);
    setBusy(true);
    try {
      await authorized(() => api.moveApplication(applicationId, to, reason));
      await load();
      if (openId === applicationId) {
        const loaded = await authorized(() => api.listApplicationEvents(applicationId));
        setEvents((current) => ({ ...current, [applicationId]: loaded }));
      }
    } catch (caught) {
      // A 409 carries the server's own sentence, written for a person to read.
      // Showing it beats replacing it with a guess at what went wrong.
      setError(errorMessage(caught, "Could not move the application"));
    } finally {
      setBusy(false);
    }
  }

  const appliedJobIds = new Set(applications.map((a) => a.job_id));
  const openTo = jobs.filter((job) => !appliedJobIds.has(job.id));
  const extracted = resumes.filter((resume) => resume.status === "extracted");

  if (!ready) return null;
  if (!session) {
    return (
      <div className="mx-auto max-w-3xl px-5 py-10">
        <AuthPanel onAuthenticated={authenticate} />
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-3xl px-5 py-10">
      <header className="mb-8">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Your applications</h1>
          <p className="mt-1.5 text-sm text-ink-muted">
            Every move is recorded with who made it and what it rested on.
          </p>
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

      <section className="card mb-8">
        <div className="border-b border-line px-4 py-3">
          <h2 className="text-sm font-semibold">Apply to a job</h2>
        </div>
        <div className="px-4 py-3">
          {extracted.length === 0 ? (
            <p className="text-xs text-ink-muted">
              Upload a resume first — a document with no extracted text cannot be screened, so
              applying with one would only promise work that must fail.
            </p>
          ) : openTo.length === 0 ? (
            <p className="text-xs text-ink-muted">
              Nothing open that you have not already applied to.
            </p>
          ) : (
            <ul className="space-y-2">
              {openTo.map((job) => (
                <li
                  key={job.id}
                  className="flex flex-wrap items-center justify-between gap-2 rounded-control border border-line px-3 py-2"
                >
                  <span className="text-sm font-medium">{job.title}</span>
                  <span className="flex items-center gap-2">
                    <select
                      aria-label={`Resume to apply to ${job.title} with`}
                      defaultValue={extracted[0]?.id}
                      id={`resume-for-${job.id}`}
                      className="field py-1 text-xs"
                    >
                      {extracted.map((resume) => (
                        <option key={resume.id} value={resume.id}>
                          {resume.filename}
                        </option>
                      ))}
                    </select>
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() => {
                        const select = document.getElementById(
                          `resume-for-${job.id}`,
                        ) as HTMLSelectElement | null;
                        if (select) void apply(job.id, select.value);
                      }}
                      className="btn btn-primary ring-focus"
                    >
                      Apply
                    </button>
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>
      </section>

      <section className="card">
        <div className="border-b border-line px-4 py-3">
          <h2 className="text-sm font-semibold">Applied ({applications.length})</h2>
        </div>
        {applications.length === 0 ? (
          <p className="px-4 py-6 text-xs text-ink-muted">Nothing yet.</p>
        ) : (
          <ul className="divide-y divide-line">
            {applications.map((application) => (
              <li key={application.id} className="px-4 py-3">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="text-sm font-medium">{application.job_title}</p>
                    <p className="mt-0.5 text-xs text-ink-muted">
                      {application.resume_filename}
                    </p>
                    <p className="mt-1.5 text-xs">
                      <Badge tone="neutral">{STATE_LABELS[application.state]}</Badge>
                      <span className="ml-2 text-ink-muted">
                        {STATE_EXPLANATIONS[application.state]}
                      </span>
                    </p>
                  </div>
                  <button
                    type="button"
                    onClick={() => void openHistory(application.id)}
                    className="ring-focus shrink-0 rounded-control text-xs text-ink-muted underline underline-offset-2 hover:text-ink"
                  >
                    {openId === application.id ? "Hide history" : "History"}
                  </button>
                </div>

                {me && !isTerminal(application.state) ? (
                  <div className="mt-2.5">
                    <ApplicationActions
                      application={application}
                      viewer={{ id: me.id, role: me.role }}
                      // The applicant does not own the posting, so nothing here
                      // offers an employer's moves — `availableMoves` returns only
                      // "withdraw", which is theirs alone.
                      jobOwnerId={null}
                      busy={busy}
                      onMove={(to, reason) => void move(application.id, to, reason)}
                    />
                  </div>
                ) : null}

                {openId === application.id ? (
                  <div className="mt-3 rounded-control bg-surface-sunken p-3">
                    {application.id in events ? (
                      // `?? []` is unreachable — the key is only present once the log has
                      // landed — and is written rather than asserted away, because an
                      // empty timeline is a survivable render and a non-null assertion
                      // here would be a promise nothing checks.
                      <ApplicationTimeline events={events[application.id] ?? []} />
                    ) : (
                      <p className="text-xs text-ink-muted">Loading the history…</p>
                    )}
                  </div>
                ) : null}
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
