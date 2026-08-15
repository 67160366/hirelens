/**
 * Tests for the session store.
 *
 * The session moved out of `useState` and into an external store that React
 * subscribes to, which made it reachable by a suite that has no DOM — the same move
 * `lib/evidence.ts` and `lib/metrics.ts` made for their components. What is worth
 * pinning here is the half that fails *silently*:
 *
 *   * **A write that does not notify.** `writeSession` and `clearSession` are the only
 *     things that tell React the session changed. Drop the `emit()` from either and
 *     nothing throws — the tab simply goes on rendering the previous token until
 *     something else happens to re-render it, which is the exact stale-copy bug the
 *     rewrite exists to remove.
 *   * **An unsubscribe that does not unsubscribe.** A listener left in the set keeps a
 *     dead component subscribed, and the `storage` listener leaks onto `window`.
 *   * **The 401 path.** One renewal and one retry; a failed renewal must clear the
 *     session rather than leave a token that will 401 forever.
 *
 * `localStorage` and `window` are two hand-written stubs rather than jsdom. `web/`
 * keeps vitest DOM-free on purpose, and this needed exactly two objects with four
 * methods between them — which is the bar for reaching for a stub instead of a
 * framework.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, api, type TokenPair } from "./api";
import {
  SessionExpired,
  authorized,
  clearSession,
  readAccessToken,
  subscribeToSession,
  writeSession,
} from "./auth";

const TOKEN_KEY = "hirelens.access_token";
const REFRESH_KEY = "hirelens.refresh_token";

function fakeStorage() {
  const entries = new Map<string, string>();
  return {
    getItem: (key: string) => entries.get(key) ?? null,
    setItem: (key: string, value: string) => void entries.set(key, value),
    removeItem: (key: string) => void entries.delete(key),
    clear: () => entries.clear(),
    size: () => entries.size,
  };
}

/** Just enough `window` for the cross-tab listener, and a way to fire the event. */
function fakeWindow() {
  const handlers = new Set<() => void>();
  return {
    addEventListener: (type: string, handler: () => void) => {
      if (type === "storage") handlers.add(handler);
    },
    removeEventListener: (type: string, handler: () => void) => {
      if (type === "storage") handlers.delete(handler);
    },
    /** What another tab writing to localStorage looks like from in here. */
    fireStorageEvent: () => handlers.forEach((handler) => handler()),
    listenerCount: () => handlers.size,
  };
}

let storage: ReturnType<typeof fakeStorage>;
let win: ReturnType<typeof fakeWindow>;

const PAIR: TokenPair = {
  access_token: "access-1",
  refresh_token: "refresh-1",
  token_type: "bearer",
};
const RENEWED: TokenPair = {
  access_token: "access-2",
  refresh_token: "refresh-2",
  token_type: "bearer",
};

beforeEach(() => {
  storage = fakeStorage();
  win = fakeWindow();
  vi.stubGlobal("localStorage", storage);
  vi.stubGlobal("window", win);
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("reading the session", () => {
  it("is null before anything is stored", () => {
    expect(readAccessToken()).toBeNull();
  });

  it("reflects a stored pair", () => {
    writeSession(PAIR);
    expect(readAccessToken()).toBe("access-1");
    expect(storage.getItem(REFRESH_KEY)).toBe("refresh-1");
  });

  it("reads through to storage rather than caching", () => {
    writeSession(PAIR);
    // A second tab, or a renewal from inside `authorized`, writes the key directly.
    storage.setItem(TOKEN_KEY, "written-elsewhere");
    expect(readAccessToken()).toBe("written-elsewhere");
  });

  it("is null once the session is cleared, and keeps no refresh token behind", () => {
    writeSession(PAIR);
    clearSession();
    expect(readAccessToken()).toBeNull();
    expect(storage.getItem(REFRESH_KEY)).toBeNull();
    expect(storage.size()).toBe(0);
  });
});

describe("notifying React", () => {
  // Each of these fails silently if the `emit()` is dropped: no throw, no error,
  // just a component that goes on showing a session that has changed underneath it.

  it("wakes subscribers when a session is written", () => {
    const listener = vi.fn();
    subscribeToSession(listener);
    writeSession(PAIR);
    expect(listener).toHaveBeenCalledTimes(1);
  });

  it("wakes subscribers when a session is cleared", () => {
    const listener = vi.fn();
    subscribeToSession(listener);
    clearSession();
    expect(listener).toHaveBeenCalledTimes(1);
  });

  it("wakes every subscriber, not just the first", () => {
    // The bug the rewrite fixes: two components on one page holding different ideas
    // of who is signed in.
    const [a, b] = [vi.fn(), vi.fn()];
    subscribeToSession(a);
    subscribeToSession(b);
    writeSession(PAIR);
    expect(a).toHaveBeenCalledTimes(1);
    expect(b).toHaveBeenCalledTimes(1);
  });

  it("stops waking a listener once it unsubscribes", () => {
    const listener = vi.fn();
    const unsubscribe = subscribeToSession(listener);
    unsubscribe();
    writeSession(PAIR);
    expect(listener).not.toHaveBeenCalled();
  });

  it("takes its storage listener off window when it unsubscribes", () => {
    const unsubscribe = subscribeToSession(vi.fn());
    expect(win.listenerCount()).toBe(1);
    unsubscribe();
    expect(win.listenerCount()).toBe(0);
  });

  it("wakes subscribers when another tab changes the session", () => {
    // The half `emit` cannot see: `storage` fires only in the tabs that did not write.
    const listener = vi.fn();
    subscribeToSession(listener);
    win.fireStorageEvent();
    expect(listener).toHaveBeenCalledTimes(1);
  });
});

describe("authorized", () => {
  it("refuses without a session rather than calling with an empty token", async () => {
    const call = vi.fn();
    await expect(authorized(call)).rejects.toBeInstanceOf(SessionExpired);
    expect(call).not.toHaveBeenCalled();
  });

  it("passes the stored token through and returns the result", async () => {
    writeSession(PAIR);
    const call = vi.fn(async (token: string) => `called with ${token}`);
    await expect(authorized(call)).resolves.toBe("called with access-1");
    expect(call).toHaveBeenCalledTimes(1);
  });

  it("renews once and retries when the token has expired", async () => {
    writeSession(PAIR);
    vi.spyOn(api, "refresh").mockResolvedValue(RENEWED);

    const call = vi
      .fn<(token: string) => Promise<string>>()
      .mockRejectedValueOnce(new ApiError(401, "expired"))
      .mockResolvedValueOnce("ok");

    await expect(authorized(call)).resolves.toBe("ok");
    expect(call).toHaveBeenNthCalledWith(1, "access-1");
    expect(call).toHaveBeenNthCalledWith(2, "access-2");
    // The renewed pair is stored, or the next call would 401 all over again.
    expect(readAccessToken()).toBe("access-2");
  });

  it("clears the session when the renewal fails, instead of keeping a dead token", async () => {
    writeSession(PAIR);
    vi.spyOn(api, "refresh").mockRejectedValue(new ApiError(401, "no"));

    const call = vi.fn().mockRejectedValue(new ApiError(401, "expired"));

    await expect(authorized(call)).rejects.toBeInstanceOf(SessionExpired);
    expect(readAccessToken()).toBeNull();
  });

  it("does not try to renew when there is no refresh token", async () => {
    storage.setItem(TOKEN_KEY, "access-only");
    const refresh = vi.spyOn(api, "refresh");
    const call = vi.fn().mockRejectedValue(new ApiError(401, "expired"));

    await expect(authorized(call)).rejects.toBeInstanceOf(SessionExpired);
    expect(refresh).not.toHaveBeenCalled();
  });

  it("rethrows anything that is not a 401, without renewing", async () => {
    // A 403 is an answer about the caller's role, not their token. Renewing on it
    // would spend a refresh and retry a call that will fail identically.
    writeSession(PAIR);
    const refresh = vi.spyOn(api, "refresh");
    const forbidden = new ApiError(403, "not your row");
    const call = vi.fn().mockRejectedValue(forbidden);

    await expect(authorized(call)).rejects.toBe(forbidden);
    expect(refresh).not.toHaveBeenCalled();
    expect(call).toHaveBeenCalledTimes(1);
    expect(readAccessToken()).toBe("access-1");
  });

  it("rethrows a non-ApiError untouched", async () => {
    writeSession(PAIR);
    const boom = new TypeError("network down");
    await expect(authorized(vi.fn().mockRejectedValue(boom))).rejects.toBe(boom);
  });
});
