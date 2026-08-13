"use client";

/**
 * The session, shared by every page.
 *
 * This lived inside `app/page.tsx` while there was only one page. Three routes
 * cannot share component state, and each of them needs the same three things: the
 * current token, a way to sign out, and the refresh-once-on-401 dance that keeps a
 * long-lived tab working after the access token expires.
 *
 * Tokens stay in `localStorage`, which is readable by any script on the page. That
 * is a known trade recorded since M1: the production answer is an httpOnly,
 * SameSite cookie issued by the API, and it belongs with M5's deploy work rather
 * than inside a UI slice.
 */

import { useCallback, useEffect, useState } from "react";

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

export interface Auth {
  token: string | null;
  /** False until `localStorage` has been read, which cannot happen during SSR. */
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

export function useAuth(): Auth {
  const [token, setToken] = useState<string | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    // `localStorage` does not exist during SSR, so the stored session can only be
    // read after mount, and `ready` is the flag every page waits on before deciding
    // it is signed out. The rule is right that this is a cascading render; it is one
    // render, once, and the alternative is rendering a signed-out page to a signed-in
    // user. `useSyncExternalStore` is the proper fix, and it changes the hook every
    // route depends on — so it is its own commit with its own browser check, not a
    // passenger on a version bump.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setToken(localStorage.getItem(TOKEN_KEY));
    setReady(true);
  }, []);

  const authenticate = useCallback((tokens: TokenPair) => {
    localStorage.setItem(TOKEN_KEY, tokens.access_token);
    localStorage.setItem(REFRESH_KEY, tokens.refresh_token);
    setToken(tokens.access_token);
  }, []);

  const signOut = useCallback(() => {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(REFRESH_KEY);
    setToken(null);
  }, []);

  /** Trade the refresh token for a new pair; null means the session is over. */
  const tryRefresh = useCallback(async (): Promise<string | null> => {
    const stored = localStorage.getItem(REFRESH_KEY);
    if (!stored) return null;
    try {
      const tokens = await api.refresh(stored);
      localStorage.setItem(TOKEN_KEY, tokens.access_token);
      localStorage.setItem(REFRESH_KEY, tokens.refresh_token);
      setToken(tokens.access_token);
      return tokens.access_token;
    } catch {
      return null;
    }
  }, []);

  const authorized = useCallback(
    async <T,>(call: (token: string) => Promise<T>): Promise<T> => {
      // Read through to storage rather than trusting state: a call fired from an
      // event handler can still be holding the token from the render it closed over.
      const current = token ?? localStorage.getItem(TOKEN_KEY);
      if (!current) throw new SessionExpired();

      try {
        return await call(current);
      } catch (caught) {
        if (!(caught instanceof ApiError) || caught.status !== 401) throw caught;

        // The access token expires long before the refresh token does, so one
        // renewal and one retry is the difference between a working tab and a
        // sign-in prompt the user did not need.
        const fresh = await tryRefresh();
        if (!fresh) {
          signOut();
          throw new SessionExpired();
        }
        return call(fresh);
      }
    },
    [token, tryRefresh, signOut],
  );

  return { token, ready, authenticate, signOut, authorized };
}

/** What to show the user for anything a call can throw. */
export function errorMessage(caught: unknown, fallback: string): string {
  if (caught instanceof SessionExpired) return caught.message;
  if (caught instanceof ApiError) return caught.message;
  return fallback;
}
