"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";

import { ApplicationActions } from "@/components/ApplicationActions";
import { ApplicationTimeline } from "@/components/ApplicationTimeline";
import { AuthPanel } from "@/components/AuthPanel";
import { DocumentPane, EvidenceSelectionProvider } from "@/components/DocumentPane";
import { JudgmentView } from "@/components/JudgmentView";
import { RankingTable } from "@/components/RankingTable";
import { RequirementEditor } from "@/components/RequirementEditor";
import { RequirementFields } from "@/components/RequirementFields";
import {
  MAX_REQUIREMENTS_PER_JOB,
  POLL_INTERVAL_MS,
  POLL_TIMEOUT_MS,
  api,
  isScreeningSettled,
  type Account,
  type Application,
  type ApplicationEvent,
  type ApplicationState,
  type Job,
  type Ranking,
  type Requirement,
  type RequirementInput,
  type RequirementPatch,
  type Resume,
  type Screening,
  type ScreeningDetail,
} from "@/lib/api";
import { errorMessage, useAuth } from "@/lib/auth";
import { STATE_LABELS, groupByState } from "@/lib/applications";
import { collectJudgmentEvidence } from "@/lib/screening";

const BLANK_REQUIREMENT: RequirementInput = {
  kind: "skill",
  label: "",
  detail: null,
  must_have: false,
  weight: 1,
};

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

export default function JobPage() {
  const jobId = String(useParams().id);
  const { token, ready, authenticate, signOut, authorized } = useAuth();

  const [job, setJob] = useState<Job | null>(null);
  const [me, setMe] = useState<Account | null>(null);
  const [applications, setApplications] = useState<Application[]>([]);
  const [openApplicationId, setOpenApplicationId] = useState<string | null>(null);
  const [applicationEvents, setApplicationEvents] = useState<ApplicationEvent[]>([]);
  const [resumes, setResumes] = useState<Resume[]>([]);
  const [screenings, setScreenings] = useState<Screening[]>([]);
  const [ranking, setRanking] = useState<Ranking | null>(null);

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<ScreeningDetail | null>(null);

  const [draft, setDraft] = useState<RequirementInput>({ ...BLANK_REQUIREMENT });
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busyResumeId, setBusyResumeId] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  /** Everything this screen reads. Six queries, none of which bills a model call. */
  const load = useCallback(async () => {
    try {
      await authorized(async (accessToken) => {
        const [
          loadedJob,
          loadedResumes,
          loadedScreenings,
          loadedRanking,
          loadedApplications,
          account,
        ] = await Promise.all([
          api.getJob(jobId, accessToken),
          api.listResumes(accessToken),
          api.listScreenings(jobId, accessToken),
          api.getRanking(jobId, accessToken),
          api.listJobApplications(jobId, accessToken),
          api.me(accessToken),
        ]);
        setJob(loadedJob);
        setResumes(loadedResumes);
        setScreenings(loadedScreenings);
        setRanking(loadedRanking);
        setApplications(loadedApplications);
        setMe(account);
      });
    } catch (caught) {
      setError(errorMessage(caught, "Could not load this job"));
    }
  }, [authorized, jobId]);

  /** Move an applicant through the pipeline. No model call — a row and an event. */
  async function moveApplication(
    applicationId: string,
    to: ApplicationState,
    reason?: string,
  ) {
    setError(null);
    setPending(true);
    try {
      await authorized((t) => api.moveApplication(applicationId, to, t, reason));
      setApplications(await authorized((t) => api.listJobApplications(jobId, t)));
      if (openApplicationId === applicationId) {
        setApplicationEvents(
          await authorized((t) => api.listApplicationEvents(applicationId, t)),
        );
      }
    } catch (caught) {
      // The server answers 409 with a sentence written for a person — "an
      // application can only be shortlisted once it has been screened, so there is
      // cited evidence behind the decision". Showing it beats guessing.
      setError(errorMessage(caught, "Could not move the application"));
    } finally {
      setPending(false);
    }
  }

  async function toggleApplicationHistory(applicationId: string) {
    if (openApplicationId === applicationId) {
      setOpenApplicationId(null);
      return;
    }
    setOpenApplicationId(applicationId);
    try {
      setApplicationEvents(
        await authorized((t) => api.listApplicationEvents(applicationId, t)),
      );
    } catch (caught) {
      setError(errorMessage(caught, "Could not load the history"));
    }
  }

  useEffect(() => {
    if (token) void load();
  }, [token, load]);

  /** Re-read only what a requirement edit can move. Still no model call. */
  const refreshAfterEdit = useCallback(async () => {
    await authorized(async (accessToken) => {
      const [loadedJob, loadedScreenings, loadedRanking] = await Promise.all([
        api.getJob(jobId, accessToken),
        api.listScreenings(jobId, accessToken),
        api.getRanking(jobId, accessToken),
      ]);
      setJob(loadedJob);
      setScreenings(loadedScreenings);
      setRanking(loadedRanking);
    });
  }, [authorized, jobId]);

  const resumeName = useCallback(
    (resumeId: string) =>
      resumes.find((resume) => resume.id === resumeId)?.filename ?? resumeId.slice(0, 8),
    [resumes],
  );

  /**
   * Wait for the worker to finish judging.
   *
   * Screenings have no progress stream — only resumes do — so this polls the list
   * rather than each row: one request covers every screening on the job, however
   * many are in flight.
   */
  const waitForScreenings = useCallback(async () => {
    const deadline = Date.now() + POLL_TIMEOUT_MS;
    for (;;) {
      const list = await authorized((accessToken) => api.listScreenings(jobId, accessToken));
      setScreenings(list);
      if (list.every((item) => isScreeningSettled(item.status))) return;
      if (Date.now() >= deadline) return;
      await sleep(POLL_INTERVAL_MS);
    }
  }, [authorized, jobId]);

  /**
   * Screen one resume — the only thing on this page that spends money.
   *
   * Always one resume, triggered by a button the user pressed. Nothing here loops
   * over the whole list on its own: a screening costs a model call per resume every
   * time a requirement's wording changes, and a refresh that quietly re-billed the
   * lot is exactly what the 202/200 split exists to make visible.
   */
  async function screen(resumeId: string) {
    setError(null);
    setNotice(null);
    setBusyResumeId(resumeId);
    try {
      const { queued } = await authorized((accessToken) =>
        api.createScreening(jobId, resumeId, accessToken),
      );
      setNotice(
        queued
          ? `Judging ${resumeName(resumeId)} — one model call.`
          : `${resumeName(resumeId)} is already screened against these requirements. Nothing was spent.`,
      );
      if (queued) await waitForScreenings();
      await authorized(async (accessToken) => {
        setRanking(await api.getRanking(jobId, accessToken));
        setScreenings(await api.listScreenings(jobId, accessToken));
      });
    } catch (caught) {
      setError(errorMessage(caught, "Could not screen this resume"));
    } finally {
      setBusyResumeId(null);
    }
  }

  async function saveRequirement(requirementId: string, patch: RequirementPatch) {
    setError(null);
    try {
      await authorized((accessToken) =>
        api.updateRequirement(jobId, requirementId, patch, accessToken),
      );
      await refreshAfterEdit();
    } catch (caught) {
      setError(errorMessage(caught, "Could not save the requirement"));
    }
  }

  async function removeRequirement(requirementId: string) {
    setError(null);
    try {
      await authorized((accessToken) => api.deleteRequirement(jobId, requirementId, accessToken));
      await refreshAfterEdit();
    } catch (caught) {
      setError(errorMessage(caught, "Could not delete the requirement"));
    }
  }

  async function addRequirement(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    setPending(true);
    try {
      await authorized((accessToken) => api.addRequirement(jobId, draft, accessToken));
      setDraft({ ...BLANK_REQUIREMENT });
      await refreshAfterEdit();
    } catch (caught) {
      setError(errorMessage(caught, "Could not add the requirement"));
    } finally {
      setPending(false);
    }
  }

  /** The document behind the selected candidate, for the highlighting pane. */
  async function select(screeningId: string) {
    setSelectedId(screeningId);
    setDetail(null);
    try {
      // Read for `document_text` only. The verdicts come from the ranking entry,
      // whose `must_have`/`weight` are re-keyed against the job's current
      // requirements — this route returns them frozen at judging time.
      setDetail(await authorized((accessToken) => api.getScreening(screeningId, accessToken)));
    } catch (caught) {
      setError(errorMessage(caught, "Could not load the screening"));
    }
  }

  const selected = useMemo(
    () => ranking?.ranked.find((entry) => entry.screening_id === selectedId) ?? null,
    [ranking, selectedId],
  );

  const screenedResumeIds = useMemo(
    () => new Set(screenings.map((item) => item.resume_id)),
    [screenings],
  );

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
      <header className="mb-6 flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">{job?.title ?? "Job"}</h1>
          {job?.description && (
            <p className="mt-1.5 max-w-2xl whitespace-pre-wrap text-sm text-stone-600 dark:text-stone-400">
              {job.description}
            </p>
          )}
        </div>
        <div className="flex flex-col items-end gap-2">
          <Link
            href="/jobs"
            className="rounded-md border border-stone-300 px-3 py-1.5 text-xs font-medium hover:bg-stone-50 dark:border-stone-700 dark:hover:bg-stone-800"
          >
            ← Jobs
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
      {notice && (
        <p className="mb-5 rounded-lg border border-stone-200 bg-white px-4 py-2.5 text-sm text-stone-600 dark:border-stone-800 dark:bg-stone-900 dark:text-stone-400">
          {notice}
        </p>
      )}

      <div className="space-y-6">
        {/* Requirements ---------------------------------------------------- */}
        <section className="rounded-lg border border-stone-200 bg-white dark:border-stone-800 dark:bg-stone-900">
          <header className="flex items-baseline justify-between gap-3 border-b border-stone-200 px-4 py-2.5 dark:border-stone-800">
            <h2 className="text-sm font-semibold">Requirements</h2>
            <p className="text-[11px] text-stone-400 dark:text-stone-500">
              {job?.requirements.length ?? 0} of {MAX_REQUIREMENTS_PER_JOB}
            </p>
          </header>

          <div className="divide-y divide-stone-100 dark:divide-stone-800">
            {job?.requirements.map((requirement: Requirement) => (
              <RequirementEditor
                key={requirement.id}
                requirement={requirement}
                onSave={(patch) => saveRequirement(requirement.id, patch)}
                onDelete={() => removeRequirement(requirement.id)}
              />
            ))}
          </div>

          <form
            onSubmit={addRequirement}
            className="flex items-start gap-2 border-t border-stone-200 px-4 py-3 dark:border-stone-800"
          >
            <div className="flex-1">
              <RequirementFields value={draft} onChange={setDraft} disabled={pending} />
            </div>
            <button
              type="submit"
              disabled={
                pending ||
                draft.label.trim() === "" ||
                (job?.requirements.length ?? 0) >= MAX_REQUIREMENTS_PER_JOB
              }
              className="mt-0.5 rounded-md bg-stone-900 px-3 py-1.5 text-xs font-medium text-white disabled:opacity-50 dark:bg-stone-100 dark:text-stone-900"
            >
              Add
            </button>
          </form>
        </section>

        {/* Applicants ------------------------------------------------------ */}
        <section className="rounded-lg border border-stone-200 bg-white dark:border-stone-800 dark:bg-stone-900">
          <header className="border-b border-stone-200 px-4 py-2.5 dark:border-stone-800">
            <h2 className="text-sm font-semibold">Applicants ({applications.length})</h2>
            <p className="mt-0.5 text-[11px] text-stone-400 dark:text-stone-500">
              Every move is recorded with who made it and what it rested on. Shortlisting
              needs a completed screening behind it; rejecting needs a reason.
            </p>
          </header>

          {applications.length === 0 ? (
            <p className="px-4 py-4 text-sm text-stone-500 dark:text-stone-400">
              Nobody has applied yet.
            </p>
          ) : (
            <div className="divide-y divide-stone-100 dark:divide-stone-800">
              {groupByState(applications).map((group) => (
                <div key={group.state} className="px-4 py-3">
                  <p className="mb-2 text-[11px] font-medium uppercase tracking-wide text-stone-400 dark:text-stone-500">
                    {STATE_LABELS[group.state]} ({group.applications.length})
                  </p>
                  <ul className="space-y-2.5">
                    {group.applications.map((application) => (
                      <li key={application.id}>
                        <div className="flex flex-wrap items-start justify-between gap-2">
                          <p className="text-sm font-medium">
                            {application.resume_filename}
                          </p>
                          <button
                            type="button"
                            onClick={() => void toggleApplicationHistory(application.id)}
                            className="text-xs text-stone-500 underline dark:text-stone-400"
                          >
                            {openApplicationId === application.id ? "Hide history" : "History"}
                          </button>
                        </div>
                        {me && job ? (
                          <div className="mt-1.5">
                            <ApplicationActions
                              application={application}
                              viewer={{ id: me.id, role: me.role }}
                              jobOwnerId={me.id}
                              busy={pending}
                              onMove={(to, reason) =>
                                void moveApplication(application.id, to, reason)
                              }
                            />
                          </div>
                        ) : null}
                        {openApplicationId === application.id ? (
                          <div className="mt-2 rounded-md bg-stone-50 p-3 dark:bg-stone-800/50">
                            <ApplicationTimeline events={applicationEvents} />
                          </div>
                        ) : null}
                      </li>
                    ))}
                  </ul>
                </div>
              ))}
            </div>
          )}
        </section>

        {/* Screening ------------------------------------------------------- */}
        <section className="rounded-lg border border-stone-200 bg-white dark:border-stone-800 dark:bg-stone-900">
          <header className="border-b border-stone-200 px-4 py-2.5 dark:border-stone-800">
            <h2 className="text-sm font-semibold">Screen a resume</h2>
            <p className="mt-0.5 text-[11px] text-stone-400 dark:text-stone-500">
              One model call each, per resume, when you press the button. Asking again for
              an answer that is still current costs nothing and says so.
            </p>
          </header>

          {resumes.length === 0 ? (
            <p className="px-4 py-4 text-sm text-stone-500 dark:text-stone-400">
              No resumes yet. <Link href="/" className="underline">Upload one first.</Link>
            </p>
          ) : (
            <ul className="divide-y divide-stone-100 dark:divide-stone-800">
              {resumes.map((resume) => {
                const screening = screenings.find((item) => item.resume_id === resume.id);
                // A resume with no verified text raises `NotScreenable` on the
                // worker, which the retry policy treats as permanent. Say so here
                // rather than offering a button that can only fail.
                const screenable = resume.status === "extracted";
                return (
                  <li
                    key={resume.id}
                    className="flex items-center justify-between gap-4 px-4 py-2.5"
                  >
                    <div className="min-w-0">
                      <p className="truncate text-sm font-medium">{resume.filename}</p>
                      <p className="text-[11px] text-stone-500 dark:text-stone-400">
                        {screenable
                          ? screening
                            ? `Screened · ${screening.status}${screening.is_stale ? " · needs re-screening" : ""}`
                            : "Not screened yet"
                          : `Cannot be screened — the resume is ${resume.status} and has no text to quote`}
                      </p>
                    </div>
                    <button
                      type="button"
                      onClick={() => void screen(resume.id)}
                      disabled={!screenable || busyResumeId !== null}
                      className="shrink-0 rounded-md border border-stone-300 px-3 py-1 text-xs font-medium hover:bg-stone-50 disabled:opacity-40 dark:border-stone-700 dark:hover:bg-stone-800"
                    >
                      {busyResumeId === resume.id
                        ? "Judging…"
                        : screenedResumeIds.has(resume.id)
                          ? "Screen again"
                          : "Screen"}
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </section>

        {/* Ranking --------------------------------------------------------- */}
        {ranking && (
          <RankingTable
            ranking={ranking}
            resumeName={resumeName}
            selectedScreeningId={selectedId}
            onSelect={(screeningId) => void select(screeningId)}
            onScreenAgain={(resumeId) => void screen(resumeId)}
            busyResumeId={busyResumeId}
          />
        )}

        {/* The rationale, beside the document it was quoted from ------------ */}
        {selected && (
          <EvidenceSelectionProvider>
            <div className="grid items-start gap-5 lg:grid-cols-2">
              <JudgmentView entry={selected} resumeName={resumeName(selected.resume_id)} />
              {detail?.document_text ? (
                <DocumentPane
                  text={detail.document_text}
                  references={collectJudgmentEvidence(selected.requirements)}
                />
              ) : (
                <p className="text-sm text-stone-500 dark:text-stone-400">
                  Loading the document…
                </p>
              )}
            </div>
          </EvidenceSelectionProvider>
        )}
      </div>
    </main>
  );
}
