"use client";

import { useState } from "react";

import { api, type SelfServiceRole } from "@/lib/api";
import { Banner } from "@/components/ui/Banner";
import { Button } from "@/components/ui/Button";
import { errorMessage, establishSession, type Session } from "@/lib/auth";

type Mode = "login" | "register";

/** What each self-service role gets, in the terms someone choosing would use. */
const ROLE_CHOICES: { value: SelfServiceRole; label: string; blurb: string }[] = [
  {
    value: "candidate",
    label: "I'm looking for work",
    blurb: "Upload a CV and apply to postings.",
  },
  {
    value: "recruiter",
    label: "I'm hiring",
    blurb: "Post jobs and screen the people who apply.",
  },
];

/**
 * Sign in or create an account.
 *
 * Lifted out of `app/page.tsx` when a second route appeared: every page needs the
 * same panel when there is no session, and duplicating a login form is how two of
 * them drift apart.
 *
 * **Registration asks for a role**, because there is no other way to become a
 * recruiter — M4 slice 2 made it a registration field for exactly that reason, and
 * this panel not offering it meant a browser could only ever create candidates.
 * Every recruiter screen was therefore unreachable without going around the UI.
 * `admin` is not offered, and `SelfServiceRole` is why it cannot be.
 */
export function AuthPanel({
  onAuthenticated,
}: {
  onAuthenticated: (session: Session) => void;
}) {
  const [mode, setMode] = useState<Mode>("register");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<SelfServiceRole>("candidate");
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
        mode === "register" ? api.register(email, password, role) : api.login(email, password),
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
      {mode === "register" && (
        <fieldset className="space-y-1.5">
          <legend className="mb-1 text-xs text-ink-muted">What brings you here?</legend>
          {ROLE_CHOICES.map((choice) => (
            <label
              key={choice.value}
              className="flex cursor-pointer items-start gap-2 rounded-control border border-line px-2.5 py-2 hover:bg-surface-sunken"
            >
              <input
                type="radio"
                name="role"
                value={choice.value}
                checked={role === choice.value}
                onChange={() => setRole(choice.value)}
                className="mt-0.5"
              />
              <span className="min-w-0">
                <span className="block text-xs font-medium">{choice.label}</span>
                <span className="block text-micro text-ink-muted">{choice.blurb}</span>
              </span>
            </label>
          ))}
          {/* The limitation is stated rather than papered over with a check that
              proves nothing — the same wording `README.md` and `SelfServiceRole`
              carry. Someone choosing "I'm hiring" should know it is taken on
              trust. */}
          {role === "recruiter" && (
            <p className="text-micro text-ink-muted">
              Nothing here verifies that you represent an employer. That is a known limitation,
              not a claim that it has been checked.
            </p>
          )}
        </fieldset>
      )}
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
