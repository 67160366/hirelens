"use client";

import { useCallback, useEffect, useState } from "react";

import { DocumentPane, EvidenceSelectionProvider } from "@/components/DocumentPane";
import { ProfileView } from "@/components/ProfileView";
import { ApiError, api, type ProfileResponse } from "@/lib/api";

// M1 keeps the access token in localStorage, which is readable by any script on
// the page. Acceptable while the API and web app are separate dev origins; the
// production answer is an httpOnly, SameSite cookie issued by the API.
const TOKEN_KEY = "hirelens.access_token";

type Mode = "login" | "register";

function AuthPanel({ onAuthenticated }: { onAuthenticated: (token: string) => void }) {
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
      const tokens = mode === "register" ? await api.register(email, password) : await api.login(email, password);
      onAuthenticated(tokens.access_token);
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

export default function Home() {
  const [token, setToken] = useState<string | null>(null);
  const [ready, setReady] = useState(false);
  const [result, setResult] = useState<ProfileResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    setToken(localStorage.getItem(TOKEN_KEY));
    setReady(true);
  }, []);

  const authenticate = useCallback((next: string) => {
    localStorage.setItem(TOKEN_KEY, next);
    setToken(next);
  }, []);

  const signOut = useCallback(() => {
    localStorage.removeItem(TOKEN_KEY);
    setToken(null);
    setResult(null);
  }, []);

  async function upload(file: File) {
    if (!token) return;
    setError(null);
    setBusy(true);
    setResult(null);
    try {
      const resume = await api.uploadResume(file, token);
      setResult(await api.getProfile(resume.id, token));
    } catch (caught) {
      if (caught instanceof ApiError && caught.status === 401) {
        signOut();
        setError("Your session expired. Sign in again.");
      } else {
        setError(caught instanceof ApiError ? caught.message : "Upload failed");
      }
    } finally {
      setBusy(false);
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

      {!ready ? null : !token ? (
        <AuthPanel onAuthenticated={authenticate} />
      ) : (
        <div className="space-y-6">
          <div className="flex items-center justify-between gap-4 rounded-lg border border-stone-200 bg-white p-4 dark:border-stone-800 dark:bg-stone-900">
            <label className="flex-1 text-sm">
              <span className="font-medium">Upload a resume</span>
              <span className="mt-0.5 block text-xs text-stone-500 dark:text-stone-400">
                PDF, up to 10 MB. Re-uploading the same file returns the existing result.
              </span>
              <input
                type="file"
                accept="application/pdf,.pdf"
                disabled={busy}
                onChange={(event) => {
                  const file = event.target.files?.[0];
                  // Reset so selecting the same file twice still fires a change.
                  event.target.value = "";
                  if (file) void upload(file);
                }}
                className="mt-2 block w-full text-xs file:mr-3 file:rounded-md file:border-0 file:bg-stone-900 file:px-3 file:py-1.5 file:text-xs file:font-medium file:text-white dark:file:bg-stone-100 dark:file:text-stone-900"
              />
            </label>
            <button
              type="button"
              onClick={signOut}
              className="self-start text-xs text-stone-500 underline-offset-2 hover:underline dark:text-stone-400"
            >
              Sign out
            </button>
          </div>

          {busy && (
            <p className="text-sm text-stone-500 dark:text-stone-400">
              Parsing and verifying evidence…
            </p>
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
                  <DocumentPane text={result.document_text} profile={result.profile} />
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
