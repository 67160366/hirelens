"use client";

import { useState } from "react";

import { ApiError, api, type SelfServiceRole, type TokenPair } from "@/lib/api";

type Mode = "login" | "register";

/** What each self-service role gets, in the terms someone choosing would use. */
const ROLE_CHOICES: { value: SelfServiceRole; label: string; blurb: string }[] = [
  { value: "candidate", label: "I'm looking for work", blurb: "Upload a CV and apply to postings." },
  { value: "recruiter", label: "I'm hiring", blurb: "Post jobs and screen the people who apply." },
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
export function AuthPanel({ onAuthenticated }: { onAuthenticated: (tokens: TokenPair) => void }) {
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
      const tokens =
        mode === "register"
          ? await api.register(email, password, role)
          : await api.login(email, password);
      onAuthenticated(tokens);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Something went wrong");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form
      onSubmit={submit}
      className="mx-auto w-full max-w-sm space-y-3 rounded-lg border border-stone-200 bg-white p-5 dark:border-stone-800 dark:bg-stone-900"
    >
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
        className="w-full rounded-md border border-stone-300 bg-white px-3 py-2 text-sm outline-none focus:border-stone-500 dark:border-stone-700 dark:bg-stone-950"
      />
      <input
        type="password"
        required
        minLength={8}
        value={password}
        onChange={(event) => setPassword(event.target.value)}
        placeholder="At least 8 characters"
        autoComplete={mode === "register" ? "new-password" : "current-password"}
        className="w-full rounded-md border border-stone-300 bg-white px-3 py-2 text-sm outline-none focus:border-stone-500 dark:border-stone-700 dark:bg-stone-950"
      />
      {mode === "register" && (
        <fieldset className="space-y-1.5">
          <legend className="mb-1 text-xs text-stone-600 dark:text-stone-400">
            What brings you here?
          </legend>
          {ROLE_CHOICES.map((choice) => (
            <label
              key={choice.value}
              className="flex cursor-pointer items-start gap-2 rounded-md border border-stone-200 px-2.5 py-2 hover:bg-stone-50 dark:border-stone-800 dark:hover:bg-stone-800/50"
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
                <span className="block text-[11px] text-stone-500 dark:text-stone-400">
                  {choice.blurb}
                </span>
              </span>
            </label>
          ))}
          {/* The limitation is stated rather than papered over with a check that
              proves nothing — the same wording `README.md` and `SelfServiceRole`
              carry. Someone choosing "I'm hiring" should know it is taken on
              trust. */}
          {role === "recruiter" && (
            <p className="text-[11px] text-stone-500 dark:text-stone-400">
              Nothing here verifies that you represent an employer. That is a known
              limitation, not a claim that it has been checked.
            </p>
          )}
        </fieldset>
      )}
      {error && <p className="text-xs text-red-600 dark:text-red-400">{error}</p>}
      <button
        type="submit"
        disabled={busy}
        className="w-full rounded-md bg-stone-900 px-3 py-2 text-sm font-medium text-white disabled:opacity-50 dark:bg-stone-100 dark:text-stone-900"
      >
        {busy ? "Working…" : mode === "register" ? "Create account" : "Sign in"}
      </button>
      <button
        type="button"
        onClick={() => {
          setMode(mode === "register" ? "login" : "register");
          setError(null);
        }}
        className="w-full text-xs text-stone-500 underline-offset-2 hover:underline dark:text-stone-400"
      >
        {mode === "register" ? "I already have an account" : "I need an account"}
      </button>
    </form>
  );
}
