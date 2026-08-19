"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { AuthPanel } from "@/components/AuthPanel";
import { EvidenceSelectionProvider, collectEvidence } from "@/components/DocumentPane";
import { DocumentViewer } from "@/components/DocumentViewer";
import { ProfileView } from "@/components/ProfileView";
import { api, type ConsentTerms, type ProfileResponse, type Resume } from "@/lib/api";
import { errorMessage, useAuth } from "@/lib/auth";

/**
 * What is happening to the resume right now, in the user's terms.
 *
 * `pending` carrying a reason is a failed attempt waiting out its backoff — the
 * state polling could not tell apart from "just queued", because the status is
 * the same one it started at and only the reason underneath it moved.
 */
function progressMessage(resume: Resume | null): string {
  if (!resume) return "Uploading…";
  if (resume.status === "processing") return "Parsing and verifying evidence…";
  if (resume.failure_reason) return resume.failure_reason;
  return "Queued — waiting for a worker…";
}

export default function Home() {
  const { session, ready, authenticate, signOut, authorized } = useAuth();
  const [result, setResult] = useState<ProfileResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  // The last state the progress stream reported, which is what the waiting
  // message is written from.
  const [progress, setProgress] = useState<Resume | null>(null);
  // The consent terms come from the server rather than being written here, so the
  // wording somebody agreed to is the wording they were shown.
  const [consent, setConsent] = useState<ConsentTerms | null>(null);
  const [consented, setConsented] = useState(false);

  useEffect(() => {
    // Unauthenticated, so it loads whether or not anyone is signed in.
    api.getConsent().then(setConsent).catch(() => setConsent(null));
  }, []);

  /** Replay a resume the worker gave up on, and wait for the new run. */
  async function retry() {
    if (!result) return;
    setError(null);
    setBusy(true);
    try {
      await authorized(async () => {
        setProgress(await api.retryResume(result.resume.id));
        setResult(await api.waitForProfile(result.resume.id, setProgress));
      });
    } catch (caught) {
      setError(errorMessage(caught, "Could not retry"));
    } finally {
      setBusy(false);
      setProgress(null);
    }
  }

  async function upload(file: File) {
    setError(null);
    setBusy(true);
    setResult(null);
    setProgress(null);
    try {
      // Upload only stores the file and queues the work, so the result has to be
      // waited for rather than read straight out of the response.
      const uploaded = await authorized(async () => {
        const resume = await api.uploadResume(file, consented);
        setProgress(resume);
        return api.waitForProfile(resume.id, setProgress);
      });
      setResult(uploaded);
    } catch (caught) {
      setError(errorMessage(caught, "Upload failed"));
    } finally {
      setBusy(false);
      setProgress(null);
    }
  }

  return (
    <main className="mx-auto max-w-6xl px-5 py-12">
      <header className="mb-8">
        <h1 className="text-2xl font-semibold tracking-tight">HireLens</h1>
        <p className="mt-1.5 max-w-xl text-sm text-stone-600 dark:text-stone-400">
          Resume screening where every claim cites the exact text it came from. Anything the model
          cannot point to in the document is dropped and reported instead of shown.
        </p>
      </header>

      {!ready ? null : !session ? (
        <AuthPanel onAuthenticated={authenticate} />
      ) : (
        <div className="space-y-6">
          <div className="flex items-center justify-between gap-4 rounded-lg border border-stone-200 bg-white p-4 dark:border-stone-800 dark:bg-stone-900">
            {/* A <div>, not a <label>. One label used to wrap both the consent
                checkbox and the file input, and a label's control is its *first*
                labelable descendant — so the checkbox answered to the whole
                paragraph, the file input had no accessible name at all, and
                clicking the words "Upload a resume" silently toggled a PDPA
                agreement. Each control gets its own label below. */}
            <div className="flex-1 text-sm">
              <h2 className="font-medium">
                <label htmlFor="resume-file">Upload a resume</label>
              </h2>
              <p id="resume-file-hint" className="mt-0.5 text-xs text-stone-500 dark:text-stone-400">
                PDF or Word (.docx), up to 10 MB. Re-uploading the same file returns the
                existing result. A .docx has no page breaks until Word renders it, so its
                citations all report page 1 rather than inventing a number.
              </p>
              {/* The wording comes from the server, so what was agreed to and what
                  was shown cannot drift apart. The file input stays disabled until
                  the box is ticked: a consent you have to un-tick is not one. */}
              <label
                htmlFor="upload-consent"
                className="mt-2.5 flex cursor-pointer items-start gap-2 rounded-md bg-stone-50 p-2.5 text-xs text-stone-600 dark:bg-stone-800/60 dark:text-stone-300"
              >
                <input
                  id="upload-consent"
                  type="checkbox"
                  checked={consented}
                  disabled={busy}
                  onChange={(event) => setConsented(event.target.checked)}
                  className="mt-0.5 shrink-0"
                />
                <span>{consent?.text ?? "Loading the consent terms…"}</span>
              </label>
              <input
                id="resume-file"
                type="file"
                aria-describedby="resume-file-hint"
                // The API registers both signatures and refuses a relabelled file on
                // the bytes (`api/app/api/routes/resumes.py`), so the picker was the
                // only thing turning a Word CV away — the common case.
                accept="application/pdf,.pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,.docx"
                disabled={busy || !consented}
                onChange={(event) => {
                  const file = event.target.files?.[0];
                  // Reset so selecting the same file twice still fires a change.
                  event.target.value = "";
                  if (file) void upload(file);
                }}
                className="mt-2 block w-full text-xs file:mr-3 file:rounded-md file:border-0 file:bg-stone-900 file:px-3 file:py-1.5 file:text-xs file:font-medium file:text-white disabled:opacity-50 dark:file:bg-stone-100 dark:file:text-stone-900"
              />
            </div>
            <div className="flex flex-col items-end gap-2 self-start">
              <Link
                href="/jobs"
                className="rounded-md border border-stone-300 px-3 py-1.5 text-xs font-medium hover:bg-stone-50 dark:border-stone-700 dark:hover:bg-stone-800"
              >
                Jobs and ranking →
              </Link>
              <Link
                href="/applications"
                className="rounded-md border border-stone-300 px-3 py-1.5 text-xs font-medium hover:bg-stone-50 dark:border-stone-700 dark:hover:bg-stone-800"
              >
                Your applications →
              </Link>
              <Link
                href="/metrics"
                className="rounded-md border border-stone-300 px-3 py-1.5 text-xs font-medium hover:bg-stone-50 dark:border-stone-700 dark:hover:bg-stone-800"
              >
                Usage and quality →
              </Link>
              <button
                type="button"
                onClick={() => {
                  // Drop the result with the session: signing back in as someone
                  // else must not find the previous account's resume still on screen.
                  setResult(null);
                  // `void`, not `await`: signing out now reaches the API to revoke
                  // the session, and the screen must not wait on a network call to
                  // stop showing a signed-in state. The local clear happens either
                  // way — see `signOut` in `lib/auth.ts`.
                  void signOut();
                }}
                className="text-xs text-stone-500 underline-offset-2 hover:underline dark:text-stone-400"
              >
                Sign out
              </button>
            </div>
          </div>

          {/* Live, because the API streams every state change rather than making
              the page ask. A retry waiting out its backoff says so here. */}
          {busy && (
            <p className="text-sm text-stone-500 dark:text-stone-400">{progressMessage(progress)}</p>
          )}
          {/* A resume the worker gave up on after retrying is kept rather than
              discarded, so it can be run again once the cause is fixed. */}
          {result?.resume.can_retry && !busy && (
            <div className="flex items-center gap-3 rounded-lg border border-amber-300 bg-amber-50 px-4 py-2.5 text-sm dark:border-amber-900/60 dark:bg-amber-950/30">
              <span className="text-amber-900 dark:text-amber-300">
                Stopped after {result.resume.attempts}{" "}
                {result.resume.attempts === 1 ? "attempt" : "attempts"}.
              </span>
              <button
                type="button"
                onClick={() => void retry()}
                className="rounded-md bg-amber-900 px-3 py-1 text-xs font-medium text-white dark:bg-amber-200 dark:text-amber-950"
              >
                Try again
              </button>
            </div>
          )}
          {error && (
            <p className="rounded-lg border border-red-300 bg-red-50 px-4 py-2.5 text-sm text-red-800 dark:border-red-900/60 dark:bg-red-950/30 dark:text-red-400">
              {error}
            </p>
          )}

          {/* The document pane only appears when there is text to point into. A
              failed parse has no offsets, so citations stay non-interactive. */}
          {result &&
            (result.document_text ? (
              <EvidenceSelectionProvider>
                <div className="grid items-start gap-5 lg:grid-cols-2">
                  <ProfileView resume={result.resume} profile={result.profile} />
                  <DocumentViewer
                    resumeId={result.resume.id}
                    filename={result.resume.filename}
                    text={result.document_text}
                    references={result.profile ? collectEvidence(result.profile) : []}
                    authorized={authorized}
                  />
                </div>
              </EvidenceSelectionProvider>
            ) : (
              <ProfileView resume={result.resume} profile={result.profile} />
            ))}
        </div>
      )}
    </main>
  );
}
