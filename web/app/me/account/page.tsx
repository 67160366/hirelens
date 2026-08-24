"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { AuthPanel } from "@/components/AuthPanel";
import { Badge } from "@/components/ui/Badge";
import { Banner } from "@/components/ui/Banner";
import { Button } from "@/components/ui/Button";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { PASSWORD_CHANGE_NOTICE, erasureConsequences, exportFilename } from "@/lib/account";
import { api, type Erasure } from "@/lib/api";
import { clearSession, errorMessage, establishSession, useAuth } from "@/lib/auth";

/**
 * The account screen: take a copy, change the password, or leave.
 *
 * **Every route behind it has existed since M4's PDPA slice**, and until now the
 * only way to reach two of them was `curl`. A right to a copy and a right to be
 * forgotten that need a terminal are rights the people they were written for do
 * not have — which is the same argument the screening receipt makes one floor up.
 *
 * Three things are said before they happen rather than after:
 *
 * - **A password change ends every other session**, on devices this server has no
 *   record of. Somebody who has not been told reads the sign-in screen on their
 *   phone as a fault.
 * - **Erasure deletes files before rows**, so what is gone is gone in an order that
 *   cannot leave an unreachable object behind.
 * - **A recruiter's erasure takes other people's history**, because their postings
 *   go and every application to them goes with them. That sentence is not about
 *   the person pressing the button, which is exactly why it has to be on screen.
 *
 * The export is handed over verbatim. Rendering a summary of it would make the
 * right to a copy decorative — `privacy_service` deliberately puts `document_text`
 * and the verified profiles in there, and a screen that showed counts instead
 * would be quietly withholding the substance.
 */
export default function AccountPage() {
  const { session, ready, authenticate, signOut, authorized } = useAuth();
  const router = useRouter();

  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [passwordBusy, setPasswordBusy] = useState(false);
  const [passwordError, setPasswordError] = useState<string | null>(null);
  const [passwordDone, setPasswordDone] = useState(false);

  const [exportBusy, setExportBusy] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);

  const [confirming, setConfirming] = useState(false);
  const [eraseBusy, setEraseBusy] = useState(false);
  const [eraseError, setEraseError] = useState<string | null>(null);
  const [erased, setErased] = useState<Erasure | null>(null);

  if (!ready) return null;

  // **Before the signed-out branch, and that order is the whole point.** Erasing
  // clears the session, so `session` is already null by the time this renders —
  // asking about it first put the sign-in form on screen instead of the receipt,
  // and somebody who had just destroyed their account was shown a form inviting
  // them to make another. Watched happening, which is the only way it shows up:
  // every gate was green and the API had done exactly the right thing.
  //
  // The one screen that can outlive its own account. Rendered instead of the
  // controls rather than beside them, because every control below now belongs to
  // something that does not exist.
  if (erased) {
    return (
      <div className="mx-auto max-w-3xl px-5 py-12">
        <h1 className="text-2xl font-semibold tracking-tight text-ink">Account erased</h1>
        <Banner tone="success" className="mt-4">
          {erased.message} {erased.stored_files_removed} stored{" "}
          {erased.stored_files_removed === 1 ? "file was" : "files were"} deleted.
        </Banner>
        <Button
          variant="primary"
          size="lg"
          className="mt-6"
          onClick={() => router.push("/")}
        >
          Back to the site
        </Button>
      </div>
    );
  }

  if (!session) {
    return (
      <div className="mx-auto max-w-3xl px-5 py-12">
        <AuthPanel onAuthenticated={authenticate} />
      </div>
    );
  }

  async function changePassword(event: React.FormEvent) {
    event.preventDefault();
    setPasswordError(null);
    setPasswordDone(false);
    setPasswordBusy(true);
    try {
      // Through `establishSession`, not as a bare call: the route answers with a
      // fresh pair in new cookies, and asking who we are afterwards is what proves
      // this tab kept its session rather than assuming it. The identity marker is
      // rewritten by the same step, so the other tabs follow through `storage`.
      await establishSession(() => api.changePassword(current, next));
      setCurrent("");
      setNext("");
      setPasswordDone(true);
    } catch (caught) {
      setPasswordError(errorMessage(caught, "The password could not be changed"));
    } finally {
      setPasswordBusy(false);
    }
  }

  async function downloadExport() {
    setExportError(null);
    setExportBusy(true);
    try {
      const data = await authorized(() => api.exportMe());
      // Handed over exactly as it arrived, pretty-printed only so it can be read
      // by the person it is about — which is the whole point of the route.
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = exportFilename(session!.id);
      // In the document, and revoked a tick later. Chrome downloads from a
      // detached anchor and revoking immediately happened to work here, but both
      // are engine-dependent — and the failure mode is the quietest one on this
      // screen: the button looks like it worked and no file arrives.
      document.body.append(link);
      link.click();
      link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 0);
    } catch (caught) {
      setExportError(errorMessage(caught, "The copy could not be downloaded"));
    } finally {
      setExportBusy(false);
    }
  }

  async function erase() {
    setEraseError(null);
    setEraseBusy(true);
    try {
      const receipt = await authorized(() => api.eraseMe());
      // The tokens authenticate nothing once the row is gone — the server answers
      // 401 for a valid signature over an account that does not exist — but the
      // marker in this browser would still say somebody is signed in.
      clearSession();
      setErased(receipt);
    } catch (caught) {
      setEraseError(errorMessage(caught, "The account could not be erased"));
      setEraseBusy(false);
    }
  }

  return (
    <div className="mx-auto max-w-3xl px-5 py-12">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-ink">Account</h1>
          <p className="mt-1 text-sm text-ink-muted">{session.email}</p>
        </div>
        <Badge tone="neutral">{session.role}</Badge>
      </header>

      <Card className="mt-8">
        <CardHeader
          title="Take a copy"
          caption="Everything this system holds about you, as one JSON file"
        />
        <CardBody className="space-y-3">
          <p className="text-sm leading-relaxed text-ink-muted">
            It carries the substance rather than a summary: the text of every document you
            uploaded, the verified profile read out of it, what each screening concluded, and
            what those model calls cost. Nothing about it is logged.
          </p>
          {exportError && <Banner tone="danger">{exportError}</Banner>}
          <Button variant="secondary" size="lg" disabled={exportBusy} onClick={downloadExport}>
            {exportBusy ? "Preparing…" : "Download my data"}
          </Button>
        </CardBody>
      </Card>

      <Card className="mt-4">
        <CardHeader title="Change password" caption="You will need the current one" />
        <CardBody>
          <form onSubmit={changePassword} className="max-w-sm space-y-3">
            <input
              type="password"
              required
              value={current}
              onChange={(event) => setCurrent(event.target.value)}
              placeholder="Current password"
              autoComplete="current-password"
              aria-label="Current password"
              className="field"
            />
            <input
              type="password"
              required
              minLength={8}
              value={next}
              onChange={(event) => setNext(event.target.value)}
              placeholder="New password, at least 8 characters"
              autoComplete="new-password"
              aria-label="New password"
              className="field"
            />
            <p className="text-xs leading-relaxed text-ink-muted">{PASSWORD_CHANGE_NOTICE}</p>
            {passwordError && <Banner tone="danger">{passwordError}</Banner>}
            {passwordDone && (
              <Banner tone="success">
                Password changed. Every other session has ended; this tab is still signed in.
              </Banner>
            )}
            <Button type="submit" variant="primary" size="lg" disabled={passwordBusy}>
              {passwordBusy ? "Changing…" : "Change password"}
            </Button>
          </form>
        </CardBody>
      </Card>

      <Card className="mt-4">
        <CardHeader title="Sign out" caption="Ends this session on the server, not only here" />
        <CardBody>
          <Button variant="secondary" size="lg" onClick={() => void signOut()}>
            Sign out
          </Button>
        </CardBody>
      </Card>

      {/* The one destructive control on the screen, and the only place `dropped`
          is spent on something that is not a claim about a document —
          `docs/DESIGN.md` §1's single sanctioned exception, because refusing a
          claim and destroying a row read as the same red: this cannot be undone. */}
      <section className="mt-10 rounded-card border border-dropped/40 bg-dropped-wash p-5">
        <h2 className="text-section font-semibold text-dropped">Erase this account</h2>
        <p className="mt-1 text-sm text-ink-muted">
          There is no undo, and no copy kept. Take yours above first if you want one.
        </p>
        <ul className="mt-3 list-disc space-y-1.5 pl-5 text-sm leading-relaxed text-ink-muted">
          {erasureConsequences(session.role).map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ul>

        {eraseError && (
          <Banner tone="danger" className="mt-4">
            {eraseError}
          </Banner>
        )}

        {/* Two steps, the same shape as deleting a requirement: the first press
            says what is about to happen, the second does it. */}
        {!confirming ? (
          <Button variant="danger" size="lg" className="mt-4" onClick={() => setConfirming(true)}>
            Erase my account
          </Button>
        ) : (
          <div className="mt-4 flex flex-wrap items-center gap-3">
            <Button variant="danger" size="lg" disabled={eraseBusy} onClick={erase}>
              {eraseBusy ? "Erasing…" : "Yes, erase everything"}
            </Button>
            <Button
              variant="secondary"
              size="lg"
              disabled={eraseBusy}
              onClick={() => setConfirming(false)}
            >
              Cancel
            </Button>
          </div>
        )}
      </section>
    </div>
  );
}
