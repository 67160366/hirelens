"use client";

import { useState } from "react";

import { api } from "@/lib/api";
import { Banner } from "@/components/ui/Banner";
import { Button } from "@/components/ui/Button";
import { errorMessage, establishSession, type Session } from "@/lib/auth";

type Mode = "login" | "register";

/**
 * Sign in or create an account.
 *
 * Lifted out of `app/page.tsx` when a second route appeared: every page needs the
 * same panel when there is no session, and duplicating a login form is how two of
 * them drift apart.
 *
 * **Registration no longer asks for a role, and the question is gone rather than
 * fixed to one answer.** It used to offer "I'm hiring", because a role was the only
 * way to become a recruiter. The site has one employer now, so that question has no
 * honest answer to give a stranger: everybody arriving at this panel from the public
 * site is an applicant, and the two people who are not are granted their role out of
 * band. A radio group with one option would still be asking.
 */
export function AuthPanel({
  onAuthenticated,
}: {
  onAuthenticated: (session: Session) => void;
}) {
  const [mode, setMode] = useState<Mode>("register");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    setBusy(true);
    try {
      // The panel no longer receives a token — the API puts the session in httpOnly
      // cookies the browser keeps and this page cannot read. `establishSession` then
      // asks who that is, which doubles as proof the cookie was actually stored:
      // signing in successfully and being unauthenticated a moment later is the most
      // confusing state this client has, and it names the cause instead.
      const session = await establishSession(() =>
        mode === "register" ? api.register(email, password) : api.login(email, password),
      );
      onAuthenticated(session);
    } catch (caught) {
      setError(errorMessage(caught, "Something went wrong"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="card mx-auto w-full max-w-sm space-y-3 p-5">
      <h2 className="text-sm font-semibold">
        {mode === "register" ? "Create an account" : "Sign in"}
      </h2>
      <input
        type="email"
        required
        value={email}
        onChange={(event) => setEmail(event.target.value)}
        placeholder="you@example.com"
        autoComplete="email"
        className="field"
      />
      <input
        type="password"
        required
        minLength={8}
        value={password}
        onChange={(event) => setPassword(event.target.value)}
        placeholder="At least 8 characters"
        autoComplete={mode === "register" ? "new-password" : "current-password"}
        className="field"
      />
      {error && <Banner tone="danger">{error}</Banner>}
      <Button type="submit" variant="primary" size="lg" disabled={busy} className="w-full">
        {busy ? "Working…" : mode === "register" ? "Create account" : "Sign in"}
      </Button>
      <button
        type="button"
        onClick={() => {
          setMode(mode === "register" ? "login" : "register");
          setError(null);
        }}
        className="ring-focus w-full rounded-control text-xs text-ink-muted underline-offset-2 hover:text-ink hover:underline"
      >
        {mode === "register" ? "I already have an account" : "I need an account"}
      </button>
    </form>
  );
}
