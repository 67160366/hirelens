"use client";

/**
 * The session, shared by every page.
 *
 * This lived inside `app/page.tsx` while there was only one page. Five routes cannot
 * share component state, and each of them needs the same three things: the current
 * token, a way to sign out, and the refresh-once-on-401 dance that keeps a long-lived
 * tab working after the access token expires.
 *
 * **The session is an external store, not component state.** `localStorage` is the
 * thing that actually holds it, so React subscribes to it through
 * `useSyncExternalStore` rather than copying it into `useState` on mount. The old
 * shape read storage in an effect and called `setToken`, which meant a cascading
 * render on every route and carried this project's one genuine
 * `react-hooks/set-state-in-effect` suppression. Three things fall out of the change,
 * and only the first was the reason for it:
 *
 *   * **The suppression is gone**, because nothing sets state in an effect any more.
 *   * **Two components on one page now agree.** Every `useAuth()` call used to own a
 *     private copy of the token, so a sign-in in one component left any other
 *     component on that page still holding `null` until something re-mounted it.
 *     Today only `AuthPanel` and its page do this, which is why nobody has seen it —
 *     but `DocumentViewer` already takes `authorized` as a prop for exactly this
 *     reason, and the next component that reaches for the hook directly would have
 *     found the bug rather than the seam.
 *   * **Tabs stay in step.** Signing out in one tab now signs out the others, because
 *     the store also listens for the `storage` event. A revoked session that stays
 *     live in a second tab is the kind of thing nobody tests and everybody assumes.
 *
 * Tokens stay in `localStorage`, which is readable by any script on the page. That is
 * a known trade recorded since M1, and it is *still* the trade: the production answer
 * is an httpOnly, SameSite cookie issued by the API, which drags in the refresh-token
 * denylist and is its own piece of work. Moving to `useSyncExternalStore` does not
 * change where the token lives — it changes who is allowed to believe a stale copy of
 * it.
 */

import { useSyncExternalStore } from "react";

import { ApiError, api, type TokenPair } from "@/lib/api";

const TOKEN_KEY = "hirelens.access_token";
const REFRESH_KEY = "hirelens.refresh_token";

/**
 * The session ended and could not be renewed.
 *
 * Distinct from `ApiError` on purpose: a caller wants to say "sign in again"
 * rather than surface whatever the API said about a token the user never saw.
 */
export class SessionExpired extends Error {
  constructor() {
    super("Your session expired. Sign in again.");
    this.name = "SessionExpired";
  }
}

// --- the store -------------------------------------------------------------
//
// Exported rather than hidden because it *is* the logic, and `npm test` runs with no
// DOM by design — the same move as `lib/applications.ts` and `lib/metrics.ts`. The
// hook below is a four-line adapter over this.

type Listener = () => void;

const listeners = new Set<Listener>();

/** Tell React the stored session changed. */
function emit(): void {
  for (const listener of listeners) listener();
}

/**
 * Register interest in the session.
 *
 * The listener set covers writes made *by this tab*; the `storage` event covers
 * writes made by every other one, and fires only there — which is precisely the case
 * `emit` cannot see. A spurious wake-up costs nothing, because React re-reads the
 * snapshot and compares it before re-rendering, so the event is not filtered by key.
 *
 * `window` is guarded because this module is imported by pages that render on the
 * server and by a test suite that runs with no DOM. The cross-tab half is the
 * optional half; the listener set is the half that must always work.
 */
export function subscribeToSession(listener: Listener): () => void {
  listeners.add(listener);
  if (typeof window !== "undefined") window.addEventListener("storage", listener);
  return () => {
    listeners.delete(listener);
    if (typeof window !== "undefined") window.removeEventListener("storage", listener);
  };
}

/**
 * The current access token, or null.
 *
 * Read straight from storage every time rather than cached: `useSyncExternalStore`
 * compares snapshots itself, and a string or null compares by value, so there is no
 * identity to keep stable and no cache to go stale.
 */
export function readAccessToken(): string | null {
  if (typeof localStorage === "undefined") return null;
  return localStorage.getItem(TOKEN_KEY);
}

function readRefreshToken(): string | null {
  if (typeof localStorage === "undefined") return null;
  return localStorage.getItem(REFRESH_KEY);
}

/** There is no session during SSR, because there is no storage to read one from. */
function noSessionOnServer(): null {
  return null;
}

/** Store a freshly issued pair and wake everything reading it. */
export function writeSession(tokens: TokenPair): void {
  localStorage.setItem(TOKEN_KEY, tokens.access_token);
  localStorage.setItem(REFRESH_KEY, tokens.refresh_token);
  emit();
}

/** Forget the session and wake everything reading it. */
export function clearSession(): void {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(REFRESH_KEY);
  emit();
}

/** Trade the refresh token for a new pair; null means the session is over. */
async function tryRefresh(): Promise<string | null> {
  const stored = readRefreshToken();
  if (!stored) return null;
  try {
    const tokens = await api.refresh(stored);
    writeSession(tokens);
    return tokens.access_token;
  } catch {
    return null;
  }
}

/**
 * Run an authenticated call, renewing once and retrying if the token has expired.
 *
 * A module function rather than a `useCallback`, because it closes over nothing: it
 * reads the token out of storage, which is the same place the rendered value comes
 * from. The old version took `token` from state and then read through to storage
 * anyway, to defend against a handler holding the token from the render it closed
 * over — that defence is what the external store makes unnecessary.
 */
export async function authorized<T>(call: (token: string) => Promise<T>): Promise<T> {
  const current = readAccessToken();
  if (!current) throw new SessionExpired();

  try {
    return await call(current);
  } catch (caught) {
    if (!(caught instanceof ApiError) || caught.status !== 401) throw caught;

    // The access token expires long before the refresh token does, so one renewal
    // and one retry is the difference between a working tab and a sign-in prompt
    // the user did not need.
    const fresh = await tryRefresh();
    if (!fresh) {
      clearSession();
      throw new SessionExpired();
    }
    return call(fresh);
  }
}

// --- the hook --------------------------------------------------------------

export interface Auth {
  token: string | null;
  /** False until the client has hydrated, since SSR has no storage to read. */
  ready: boolean;
  authenticate: (tokens: TokenPair) => void;
  signOut: () => void;
  /**
   * Run an authenticated call, trading the refresh token for a new pair and
   * retrying once if the access token has expired.
   *
   * Every page goes through this rather than reimplementing the retry, and a
   * session that cannot be renewed raises `SessionExpired` instead of a bare 401.
   */
  authorized: <T>(call: (token: string) => Promise<T>) => Promise<T>;
}

/** Client-side snapshot of "has this hydrated yet". */
function hydrated(): boolean {
  return true;
}

/** Server-side snapshot of the same. */
function notHydrated(): boolean {
  return false;
}

export function useAuth(): Auth {
  const token = useSyncExternalStore(subscribeToSession, readAccessToken, noSessionOnServer);
  // `ready` is the same question `useSyncExternalStore` already answers for the token
  // — "are we past hydration" — asked separately because every page branches on it
  // before deciding somebody is signed out. React returns the server snapshot during
  // hydration and re-renders with the client one after, which is the transition the
  // old effect was hand-rolling.
  const ready = useSyncExternalStore(subscribeToSession, hydrated, notHydrated);

  return { token, ready, authenticate: writeSession, signOut: clearSession, authorized };
}

/** What to show the user for anything a call can throw. */
export function errorMessage(caught: unknown, fallback: string): string {
  if (caught instanceof SessionExpired) return caught.message;
  if (caught instanceof ApiError) return caught.message;
  return fallback;
}
