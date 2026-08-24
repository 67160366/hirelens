"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { AuthPanel } from "@/components/AuthPanel";
import { Badge } from "@/components/ui/Badge";
import { Banner } from "@/components/ui/Banner";
import { Button } from "@/components/ui/Button";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { EvidenceSelectionProvider, collectEvidence } from "@/components/DocumentPane";
import { DocumentViewer } from "@/components/DocumentViewer";
import { ProfileView } from "@/components/ProfileView";
import { api, type ConsentTerms, type ProfileResponse, type Resume } from "@/lib/api";
import { errorMessage, useAuth } from "@/lib/auth";
import { documentState, documentSummary } from "@/lib/documents";

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

/**
 * The CV library: every document this account has uploaded, and one of them open.
 *
 * **This screen was an upload form at a new address until now.** `GET /resumes`
 * has returned the whole list since M1 and the only thing on screen was whatever
 * had just been uploaded — so a document from last week was reachable by
 * uploading the same file again and letting deduplication find it, which is a
 * feature standing in for a screen.
 *
 * Two rules carried from the screens that came before it:
 *
 * - **Nothing belonging to another session is ever on screen.** The list and the
 *   open document each carry the account id they were fetched for, and the render
 *   derives from it rather than an effect clearing state after the fact —
 *   `useAuth`'s rewrite bought that rule, and a resume is exactly the kind of thing
 *   that must not outlive its session.
 * - **A late answer for a document nobody is looking at any more is dropped**, the
 *   way the ranking's `requestedScreeningId` guard does it. Two quick clicks would
 *   otherwise pair one document's verdicts with another's text.
 */
export default function DocumentsPage() {
  const { session, ready, authenticate, authorized } = useAuth();
  const [result, setResult] = useState<ProfileResponse | null>(null);
  // Which account the result on screen belongs to.
  //
  // Sign out moved into the app shell, so this page no longer has a click to
  // clear the result on — and deriving it is stronger than clearing ever was.
  // The old handler covered the button and nothing else, while a session can
  // also end without one: an access token expiring, a sign-out in another tab,
  // a password change on another device. In every one of those the previous
  // account's resume stayed on screen for whoever signed in next.
  const [resultOwner, setResultOwner] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  // The last state the progress stream reported, which is what the waiting
  // message is written from.
  const [progress, setProgress] = useState<Resume | null>(null);
  // The consent terms come from the server rather than being written here, so the
  // wording somebody agreed to is the wording they were shown.
  const [consent, setConsent] = useState<ConsentTerms | null>(null);
  const [consented, setConsented] = useState(false);

  // The library, carrying the account it was fetched for. One object rather than
  // two pieces of state, so the rows and their owner cannot get out of step.
  const [library, setLibrary] = useState<{ owner: string; resumes: Resume[] } | null>(null);
  const [libraryError, setLibraryError] = useState<string | null>(null);
  const [openId, setOpenId] = useState<string | null>(null);
  const requested = useRef<string | null>(null);

  const owner = session?.id ?? null;

  useEffect(() => {
    // Unauthenticated, so it loads whether or not anyone is signed in.
    api
      .getConsent()
      .then(setConsent)
      .catch(() => setConsent(null));
  }, []);

  /**
   * Read the library into state, tagged with whose it is.
   *
   * The fetch is expressed as a promise chain rather than an `await` in an effect
   * body, which is the shape `app/careers/[id]` settled on: the state is written
   * from a callback, so the effect never sets state synchronously, and
   * `set-state-in-effect` stays satisfied honestly rather than with a suppression.
   */
  const loadLibrary = useCallback(
    (accountId: string) =>
      authorized(() => api.listResumes())
        .then((resumes) => {
          setLibrary({ owner: accountId, resumes });
          setLibraryError(null);
        })
        .catch((caught) => {
          // Named rather than left as an empty list: "you have uploaded nothing"
          // and "we could not ask" look identical on screen, and only one of them
          // is worth pressing a button about.
          setLibraryError(errorMessage(caught, "Your documents could not be loaded"));
        }),
    [authorized],
  );

  useEffect(() => {
    if (!owner) return;
    void loadLibrary(owner);
  }, [owner, loadLibrary]);

  // Nothing is rendered unless it belongs to the session asking for it.
  const shown = result !== null && resultOwner === session?.id ? result : null;
  const mine = library && library.owner === owner ? library.resumes : [];

  /** Show a result together with whose it is. Never call `setResult` directly:
   *  a result with no owner is one that outlives its session. */
  function showResult(value: ProfileResponse | null) {
    setResult(value);
    setResultOwner(value === null ? null : (session?.id ?? null));
  }

  /** Open one document from the library. */
  async function open(id: string) {
    setError(null);
    setOpenId(id);
    requested.current = id;
    try {
      const profile = await authorized(() => api.getProfile(id));
      // The guard the ranking table needed for the same reason: a slow answer for
      // a document the reader has already navigated away from would otherwise
      // land, pairing one document's claims with another's text.
      if (requested.current !== id) return;
      showResult(profile);
    } catch (caught) {
      if (requested.current !== id) return;
      setError(errorMessage(caught, "That document could not be opened"));
    }
  }

  /** Replay a resume the worker gave up on, and wait for the new run. */
  async function retry(id: string) {
    setError(null);
    setBusy(true);
    try {
      await authorized(async () => {
        setProgress(await api.retryResume(id));
        const profile = await api.waitForProfile(id, setProgress);
        setOpenId(id);
        requested.current = id;
        showResult(profile);
      });
      if (owner) await loadLibrary(owner);
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
    showResult(null);
    setProgress(null);
    try {
      // Upload only stores the file and queues the work, so the result has to be
      // waited for rather than read straight out of the response.
      const uploaded = await authorized(async () => {
        const resume = await api.uploadResume(file, consented);
        setProgress(resume);
        return api.waitForProfile(resume.id, setProgress);
      });
      setOpenId(uploaded.resume.id);
      requested.current = uploaded.resume.id;
      showResult(uploaded);
      // The row has to appear in the library too, and re-reading the list is what
      // keeps a re-upload of an existing file from adding a second row for it:
      // the API answers with the original row, so the list is the truth here.
      if (owner) await loadLibrary(owner);
    } catch (caught) {
      setError(errorMessage(caught, "Upload failed"));
    } finally {
      setBusy(false);
      setProgress(null);
    }
  }

  return (
    <div className="mx-auto max-w-6xl px-5 py-10">
      <header className="mb-8">
        <h1 className="text-2xl font-semibold tracking-tight">Your documents</h1>
        <p className="mt-1.5 max-w-xl text-sm text-ink-muted">
          Every CV you have uploaded, and what the system could read in it. Each claim cites
          the exact text it came from; anything the model cannot point to in the document is
          dropped and reported instead of shown.
        </p>
      </header>

      {!ready ? null : !session ? (
        <AuthPanel onAuthenticated={authenticate} />
      ) : (
        <div className="space-y-6">
          <div className="card flex items-center justify-between gap-4 p-4">
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
              <p id="resume-file-hint" className="mt-0.5 text-xs text-ink-muted">
                PDF or Word (.docx), up to 10 MB. Re-uploading the same file returns the
                existing result. A .docx has no page breaks until Word renders it, so its
                citations all report page 1 rather than inventing a number.
              </p>
              {/* The wording comes from the server, so what was agreed to and what
                  was shown cannot drift apart. The file input stays disabled until
                  the box is ticked: a consent you have to un-tick is not one. */}
              <label
                htmlFor="upload-consent"
                className="mt-2.5 flex cursor-pointer items-start gap-2 rounded-control bg-surface-sunken p-2.5 text-xs text-ink-muted"
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
                // The `file:` pseudo-element cannot take a `btn-primary` class — it is
                // not an element a class can be put on — so this is the one button in
                // the app that restates the recipe. It restates it in tokens.
                className="mt-2 block w-full text-xs file:mr-3 file:cursor-pointer file:rounded-control file:border-0 file:bg-accent file:px-3 file:py-1.5 file:text-xs file:font-medium file:text-on-accent hover:file:bg-accent-hover disabled:opacity-50"
              />
            </div>
          </div>

          {/* Live, because the API streams every state change rather than making
              the page ask. A retry waiting out its backoff says so here. */}
          {busy && <p className="text-sm text-ink-muted">{progressMessage(progress)}</p>}
          {error && <Banner tone="danger">{error}</Banner>}

          <Card>
            <CardHeader
              title="Library"
              caption={
                mine.length === 0
                  ? "Nothing uploaded yet"
                  : `${mine.length} ${mine.length === 1 ? "document" : "documents"}, newest first`
              }
            />
            <CardBody padded={false}>
              {libraryError ? (
                <div className="space-y-3 px-4 py-4">
                  <Banner tone="danger">{libraryError}</Banner>
                  <Button onClick={() => owner && void loadLibrary(owner)}>Try again</Button>
                </div>
              ) : mine.length === 0 ? (
                <p className="px-4 py-4 text-sm text-ink-muted">
                  Upload one above. Nothing is shared with anybody until you apply to a
                  posting with it.
                </p>
              ) : (
                <ul className="divide-y divide-line">
                  {mine.map((resume) => {
                    const state = documentState(resume.status);
                    const open_ = openId === resume.id;
                    return (
                      <li key={resume.id}>
                        <div
                          className={`flex flex-wrap items-center gap-3 px-4 py-3 ${
                            // `accent`, because being the row you opened is a
                            // control state — never `cited`, which says something
                            // about the document (docs/DESIGN.md §1).
                            open_ ? "bg-accent-wash" : ""
                          }`}
                        >
                          <button
                            type="button"
                            onClick={() => void open(resume.id)}
                            aria-expanded={open_}
                            className="ring-focus min-w-0 flex-1 rounded-control text-left"
                          >
                            <span className="block truncate text-sm font-medium text-ink">
                              {resume.filename}
                            </span>
                            <span className="mt-0.5 block text-micro text-ink-faint">
                              {documentSummary(resume)}
                            </span>
                          </button>

                          <Badge tone={state.tone} title={state.detail}>
                            {state.label}
                          </Badge>

                          {resume.can_retry && (
                            <Button disabled={busy} onClick={() => void retry(resume.id)}>
                              Try again
                            </Button>
                          )}
                        </div>
                      </li>
                    );
                  })}
                </ul>
              )}
            </CardBody>
          </Card>

          {/* The document pane only appears when there is text to point into. A
              failed parse has no offsets, so citations stay non-interactive. */}
          {shown &&
            (shown.document_text ? (
              <EvidenceSelectionProvider>
                <div className="grid items-start gap-5 lg:grid-cols-2">
                  <ProfileView resume={shown.resume} profile={shown.profile} />
                  <DocumentViewer
                    key={shown.resume.id}
                    resumeId={shown.resume.id}
                    filename={shown.resume.filename}
                    text={shown.document_text}
                    references={shown.profile ? collectEvidence(shown.profile) : []}
                    authorized={authorized}
                  />
                </div>
              </EvidenceSelectionProvider>
            ) : (
              <ProfileView resume={shown.resume} profile={shown.profile} />
            ))}
        </div>
      )}
    </div>
  );
}
