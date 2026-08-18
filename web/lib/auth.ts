"use client";

/**
 * The session, shared by every page.
 *
 * This lived inside `app/page.tsx` while there was only one page. Five routes cannot
 * share component state, and each of them needs the same three things: who is signed
 * in, a way to sign out, and the refresh-once-on-401 dance that keeps a long-lived tab
 * working after the access token expires.
 *
 * **The browser no longer holds a token at all.** The API issues the pair as httpOnly
 * cookies, so the credential lives somewhere no script on this page can read — which
 * is the answer to the XSS half of the auth story, the one the refresh-token denylist
 * deliberately did not address. `authorized` therefore takes a call with no argument:
 * there is nothing to pass, and a signature that still handed a token around would be
 * describing a client that no longer exists.
 *
 * **What is in `localStorage` now is an identity, not a credential.** `id`, `email`
 * and `role` — exactly what `GET /auth/me` will tell anyone holding the session
 * anyway. It is here for two reasons and neither is authentication: React needs
 * something synchronous to render "signed in as" from, and the `storage` event is the
 * only way one tab learns that another signed out. A cookie fires no such event. So
 * XSS reading this marker learns a display name and gains no ability to act.
 *
 * **The session is an external store, not component state.** `useSyncExternalStore`
 * subscribes to that marker rather than copying it into `useState` on mount. Three
 * things fall out, and only the first was the reason for the change:
 *
 *   * **No `set-state-in-effect` suppression**, because nothing sets state in an
 *     effect.
 *   * **Two components on one page agree.** Every `useAuth()` call used to own a
 *     private copy, so a sign-in in one left another holding `null` until something
 *     re-mounted it. `DocumentViewer` takes `authorized` as a prop for exactly that
 *     reason.
 *   * **Tabs stay in step.** Signing out in one signs out the others.
 *
 * The marker and the cookie can disagree — the cookie expires, or another browser
 * ends the session, or a password change bumps the account's token epoch. That is not
 * a flaw to design away: the marker is a hint about what to render, and the server is
 * the only thing that decides whether a request is allowed. `authorized` reconciles
 * them, by clearing the marker the moment a renewal fails.
 */

import { useSyncExternalStore } from "react";

import { ApiError, api, type Account } from "@/lib/api";

const SESSION_KEY = "hirelens.session";

/** Who is signed in, as far as this tab knows. Never a credential. */
export type Session = Account;

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

/**
 * Signing in worked and the session did not survive the round trip.
 *
 * Its own error because the cause is almost always one specific thing and the
 * symptom is baffling: the API answered 200, set its cookies, and the browser
 * declined to keep them. On this project that happens when the page is served from a
 * different *site* than the API — `127.0.0.1:3000` reaching `localhost:8000` is
 * cross-site however identical the two look, and `SameSite=Lax` withholds the cookie.
 * Both origins are in `CORS_ORIGINS`, so the request itself succeeds and only the
 * credential goes missing. Measured in a browser, not reasoned about.
 */
export class SessionNotStored extends Error {
  constructor() {
    super(
      "Signed in, but the browser did not keep the session. If this page is on " +
        "127.0.0.1, open it on localhost instead — the API treats them as different " +
        "sites and withholds the session cookie.",
    );
    this.name = "SessionNotStored";
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

// `useSyncExternalStore` re-renders whenever the snapshot is not `Object.is`-equal to
// the last one, so a getter that parsed the JSON afresh each call would hand React a
// new object every time and loop forever. The old store returned a string, which
// compares by value and needed none of this. Parsing is therefore memoised on the raw
// text: same text, same object identity.
let parsedFrom: string | null = null;
let parsed: Session | null = null;

/** Who this tab believes is signed in, or null. */
export function readSession(): Session | null {
  if (typeof localStorage === "undefined") return null;
  const raw = localStorage.getItem(SESSION_KEY);
  if (raw === parsedFrom) return parsed;
  parsedFrom = raw;
  parsed = raw ? (safeParse(raw) as Session | null) : null;
  return parsed;
}

/**
 * A marker written by an older version of this app, or by anything else, must not
 * take a page down. It is a rendering hint; the server decides what is allowed.
 */
function safeParse(raw: string): unknown {
  try {
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

/** There is no session during SSR, because there is no storage to read one from. */
function noSessionOnServer(): null {
  return null;
}

/** Record who signed in and wake everything reading it. */
export function writeSession(session: Session): void {
  localStorage.setItem(SESSION_KEY, JSON.stringify(session));
  emit();
}

/** Forget the session and wake everything reading it. */
export function clearSession(): void {
  localStorage.removeItem(SESSION_KEY);
  emit();
}

/**
 * Sign out for real, which now means telling the server.
 *
 * Under `localStorage` this was one line — drop the token and it was gone, because
 * the browser was the only place it lived. A cookie is not like that: forgetting the
 * marker leaves the credential sitting in the jar, still valid, still sent with every
 * request, and the next page load would sign you straight back in. So the route is
 * called, which revokes both tokens and clears both cookies.
 *
 * **The local clear happens whatever the call did.** A user who pressed Sign out has
 * to end up signed out on this screen; a network failure means the server-side
 * session outlives the click, which is a smaller wrong than a button that visibly
 * does nothing. The revocation is what makes it eventually true either way — the
 * access token expires in thirty minutes.
 */
export async function signOut(): Promise<void> {
  try {
    await api.logout();
  } catch {
    // Deliberately swallowed — see above.
  }
  clearSession();
}

/**
 * Sign in, then confirm the browser actually kept the session.
 *
 * The second call is not belt-and-braces. `/auth/login` answering 200 says the
 * password was right, not that the cookie was stored — and when it is not, every
 * later call 401s while the screen says you are signed in, which is the most
 * confusing state this client can be in. One round trip converts it into a sentence
 * naming the cause. It also supplies the identity, which the token pair does not
 * carry.
 */
export async function establishSession(signIn: () => Promise<unknown>): Promise<Session> {
  await signIn();
  let who: Session;
  try {
    who = await api.me();
  } catch (caught) {
    if (caught instanceof ApiError && caught.status === 401) throw new SessionNotStored();
    throw caught;
  }
  writeSession(who);
  return who;
}

// Concurrent renewals share one request. `authorized` is called independently by
// each of `DocumentViewer`'s two loads, so an expired access token produces two 401s
// within milliseconds of each other and two calls to renew.
//
// **That is not merely wasteful, it signs the user out.** A refresh token is
// single-use: the server revokes the presented one and issues a new pair. Whichever
// of the two racing requests arrives second presents a token that has just been
// revoked, gets a 401, and `authorized` reads that as a session it cannot renew —
// clearing the marker and throwing `SessionExpired` in the middle of a working
// session, moments after a renewal that actually succeeded.
//
// Watched rather than reasoned about: driven in a browser against a one-minute
// access token, both renewals happened to answer 200, because the first response
// updated the cookie jar before the second request left. That is timing, not a
// guarantee — and a bug that depends on which of two requests wins is the kind that
// never reproduces when somebody goes looking.
let renewal: Promise<boolean> | null = null;

/** Ask the API to rotate the session cookies. False means the session is over. */
function tryRefresh(): Promise<boolean> {
  renewal ??= (async () => {
    try {
      await api.refresh();
      return true;
    } catch {
      return false;
    } finally {
      // Cleared once this settles, so the *next* expiry renews again rather than
      // reusing a stale answer. Everyone who joined while it was in flight has
      // already taken the promise.
      renewal = null;
    }
  })();
  return renewal;
}

/**
 * Run an authenticated call, renewing once and retrying if the token has expired.
 *
 * A module function rather than a `useCallback`, because it closes over nothing —
 * the credential is a cookie the browser attaches, so there is no token to read, to
 * pass, or to hold stale from an earlier render.
 *
 * It still checks the marker first, and that check is a courtesy rather than a
 * gate: it turns "signed out" into `SessionExpired` without a round trip. A request
 * made anyway would simply 401, which is the same answer from the only authority
 * that has one.
 */
export async function authorized<T>(call: () => Promise<T>): Promise<T> {
  if (!readSession()) throw new SessionExpired();

  try {
    return await call();
  } catch (caught) {
    if (!(caught instanceof ApiError) || caught.status !== 401) throw caught;

    // The access token expires long before the refresh token does, so one renewal
    // and one retry is the difference between a working tab and a sign-in prompt
    // the user did not need.
    if (!(await tryRefresh())) {
      clearSession();
      throw new SessionExpired();
    }
    return call();
  }
}

// --- the hook --------------------------------------------------------------

export interface Auth {
  /** Who is signed in, as far as this tab knows, or null. */
  session: Session | null;
  /** False until the client has hydrated, since SSR has no storage to read. */
  ready: boolean;
  authenticate: (session: Session) => void;
  /** Ends the session on the server as well as in this tab — a cookie outlives a
   * cleared marker, so the local half alone would sign nobody out. */
  signOut: () => Promise<void>;
  /**
   * Run an authenticated call, rotating the session cookies and retrying once if
   * the access token has expired.
   *
   * Every page goes through this rather than reimplementing the retry, and a
   * session that cannot be renewed raises `SessionExpired` instead of a bare 401.
   */
  authorized: <T>(call: () => Promise<T>) => Promise<T>;
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
  const session = useSyncExternalStore(subscribeToSession, readSession, noSessionOnServer);
  // `ready` is the same question `useSyncExternalStore` already answers for the
  // session — "are we past hydration" — asked separately because every page branches
  // on it before deciding somebody is signed out. React returns the server snapshot
  // during hydration and re-renders with the client one after, which is the
  // transition the old effect was hand-rolling.
  const ready = useSyncExternalStore(subscribeToSession, hydrated, notHydrated);

  return { session, ready, authenticate: writeSession, signOut, authorized };
}

/** What to show the user for anything a call can throw. */
export function errorMessage(caught: unknown, fallback: string): string {
  if (caught instanceof SessionNotStored) return caught.message;
  if (caught instanceof SessionExpired) return caught.message;
  if (caught instanceof ApiError) return caught.message;
  return fallback;
}
