/**
 * Tests for the session store.
 *
 * The session moved out of `useState` and into an external store that React
 * subscribes to, which made it reachable by a suite that has no DOM — the same move
 * `lib/evidence.ts` and `lib/metrics.ts` made for their components. Then the
 * credential moved out of the browser entirely, into httpOnly cookies, and what is
 * left here is a *marker*: who this tab believes is signed in. Neither change moved
 * what is worth pinning, because all of it fails silently:
 *
 *   * **A write that does not notify.** `writeSession` and `clearSession` are the only
 *     things that tell React the session changed. Drop the `emit()` from either and
 *     nothing throws — the tab goes on rendering the previous session until something
 *     else happens to re-render it, which is the stale-copy bug the store exists to
 *     remove.
 *   * **An unsubscribe that does not unsubscribe.** A listener left in the set keeps a
 *     dead component subscribed, and the `storage` listener leaks onto `window`.
 *   * **A snapshot with a new identity every call.** New since the marker became an
 *     object: `useSyncExternalStore` re-renders whenever the snapshot is not
 *     `Object.is`-equal to the last, so a getter that parsed the JSON afresh each time
 *     would loop forever. A string could not do this and never had to be checked.
 *   * **The 401 path.** One renewal and one retry; a failed renewal must clear the
 *     marker rather than leave a screen claiming a session the server has ended.
 *   * **A sign-out that only clears the marker.** New, and the sharpest of them: under
 *     `localStorage` dropping the token *was* signing out. A cookie survives it, so a
 *     sign-out that never calls the API leaves the session live and the next page load
 *     signs you back in — with nothing anywhere reporting a problem.
 *
 * `localStorage` and `window` are two hand-written stubs rather than jsdom. `web/`
 * keeps vitest DOM-free on purpose, and this needed exactly two objects with four
 * methods between them — which is the bar for reaching for a stub instead of a
 * framework.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, api, type Account, type TokenPair } from "./api";
import {
  SessionExpired,
  SessionNotStored,
  authorized,
  clearSession,
  establishSession,
  readSession,
  signOut,
  subscribeToSession,
  writeSession,
} from "./auth";

const SESSION_KEY = "hirelens.session";

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

const WHO: Account = {
  id: "acc-1",
  email: "someone@example.com",
  display_name: null,
  role: "candidate",
};
const SOMEBODY_ELSE: Account = { ...WHO, id: "acc-2", email: "other@example.com" };
const PAIR: TokenPair = {
  access_token: "access-1",
  refresh_token: "refresh-1",
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
    expect(readSession()).toBeNull();
  });

  it("reflects a stored identity", () => {
    writeSession(WHO);
    expect(readSession()).toEqual(WHO);
  });

  it("stores no credential, which is the entire point of the change", () => {
    writeSession(WHO);
    // Not "there is no key called token" — the assertion is that nothing *resembling*
    // a credential is in storage at all, so a later field that happened to carry one
    // would fail this rather than slip past a name check.
    const everything = storage.getItem(SESSION_KEY) ?? "";
    expect(everything).not.toContain("access-1");
    expect(everything).not.toContain("refresh-1");
    expect(Object.keys(JSON.parse(everything) as object).sort()).toEqual([
      "display_name",
      "email",
      "id",
      "role",
    ]);
  });

  it("reads through to storage rather than caching", () => {
    writeSession(WHO);
    // Another tab writing the key directly is the case that matters.
    storage.setItem(SESSION_KEY, JSON.stringify(SOMEBODY_ELSE));
    expect(readSession()).toEqual(SOMEBODY_ELSE);
  });

  it("returns the same object while the stored text is unchanged", () => {
    // `useSyncExternalStore` compares snapshots with `Object.is`, so a getter that
    // parsed afresh every call would hand React a new object each render and loop
    // forever. The old store returned a string and compared by value, so this
    // failure mode is new with the marker being an object — and it does not throw,
    // it hangs.
    writeSession(WHO);
    expect(readSession()).toBe(readSession());
  });

  it("gives up rather than throwing on a marker it cannot parse", () => {
    // A marker left by an older version, or by anything else. It is a rendering
    // hint; a page must not be taken down by one.
    storage.setItem(SESSION_KEY, "{not json");
    expect(readSession()).toBeNull();
  });

  it("is null once the session is cleared", () => {
    writeSession(WHO);
    clearSession();
    expect(readSession()).toBeNull();
    expect(storage.size()).toBe(0);
  });
});

describe("notifying React", () => {
  // Each of these fails silently if the `emit()` is dropped: no throw, no error,
  // just a component that goes on showing a session that has changed underneath it.

  it("wakes subscribers when a session is written", () => {
    const listener = vi.fn();
    subscribeToSession(listener);
    writeSession(WHO);
    expect(listener).toHaveBeenCalledTimes(1);
  });

  it("wakes subscribers when a session is cleared", () => {
    const listener = vi.fn();
    subscribeToSession(listener);
    clearSession();
    expect(listener).toHaveBeenCalledTimes(1);
  });

  it("wakes every subscriber, not just the first", () => {
    // The bug the store fixes: two components on one page holding different ideas
    // of who is signed in.
    const [a, b] = [vi.fn(), vi.fn()];
    subscribeToSession(a);
    subscribeToSession(b);
    writeSession(WHO);
    expect(a).toHaveBeenCalledTimes(1);
    expect(b).toHaveBeenCalledTimes(1);
  });

  it("stops waking a listener once it unsubscribes", () => {
    const listener = vi.fn();
    const unsubscribe = subscribeToSession(listener);
    unsubscribe();
    writeSession(WHO);
    expect(listener).not.toHaveBeenCalled();
  });

  it("takes its storage listener off window when it unsubscribes", () => {
    const unsubscribe = subscribeToSession(vi.fn());
    expect(win.listenerCount()).toBe(1);
    unsubscribe();
    expect(win.listenerCount()).toBe(0);
  });

  it("wakes subscribers when another tab changes the session", () => {
    // The half `emit` cannot see: `storage` fires only in the tabs that did not
    // write — and it is the *only* way one tab learns another signed out, because a
    // cookie disappearing fires no event at all.
    const listener = vi.fn();
    subscribeToSession(listener);
    win.fireStorageEvent();
    expect(listener).toHaveBeenCalledTimes(1);
  });
});

describe("establishing a session", () => {
  it("records who signed in, which the token pair never said", async () => {
    const signIn = vi.fn<() => Promise<TokenPair>>().mockResolvedValue(PAIR);
    vi.spyOn(api, "me").mockResolvedValue(WHO);

    await expect(establishSession(signIn)).resolves.toEqual(WHO);
    expect(readSession()).toEqual(WHO);
  });

  it("names the cause when the browser refused to keep the cookie", async () => {
    // 200 from the sign-in and 401 a moment later is what a cross-site page looks
    // like — `127.0.0.1:3000` reaching `localhost:8000`. Without this the screen
    // says signed in and every call fails, with nothing pointing at the reason.
    const signIn = vi.fn<() => Promise<TokenPair>>().mockResolvedValue(PAIR);
    vi.spyOn(api, "me").mockRejectedValue(new ApiError(401, "Missing bearer token"));

    await expect(establishSession(signIn)).rejects.toBeInstanceOf(SessionNotStored);
    expect(readSession()).toBeNull();
  });

  it("does not record a session when signing in failed", async () => {
    const refused = new ApiError(401, "Invalid email or password");
    const signIn = vi.fn<() => Promise<TokenPair>>().mockRejectedValue(refused);
    const me = vi.spyOn(api, "me");

    await expect(establishSession(signIn)).rejects.toBe(refused);
    expect(me).not.toHaveBeenCalled();
    expect(readSession()).toBeNull();
  });

  it("passes a non-401 through rather than blaming the cookie", async () => {
    // A 503 from `/auth/me` is the API being down, not the browser dropping a
    // cookie, and saying "open it on localhost" would send someone the wrong way.
    const signIn = vi.fn<() => Promise<TokenPair>>().mockResolvedValue(PAIR);
    const down = new ApiError(503, "unavailable");
    vi.spyOn(api, "me").mockRejectedValue(down);

    await expect(establishSession(signIn)).rejects.toBe(down);
  });
});

describe("signing out", () => {
  it("ends the session on the server, not only in this tab", async () => {
    // Under localStorage, dropping the token *was* signing out. A cookie survives
    // it: skip the call and the credential stays valid, still sent with every
    // request, and the next page load signs you straight back in.
    writeSession(WHO);
    const logout = vi.spyOn(api, "logout").mockResolvedValue(undefined);

    await signOut();

    expect(logout).toHaveBeenCalledTimes(1);
    expect(readSession()).toBeNull();
  });

  it("still signs out locally when the call fails", async () => {
    // Somebody who pressed Sign out has to end up signed out on this screen. The
    // server-side session outliving a failed request is the smaller wrong, and the
    // access token expires on its own within the half hour.
    writeSession(WHO);
    vi.spyOn(api, "logout").mockRejectedValue(new ApiError(0, "offline"));

    await expect(signOut()).resolves.toBeUndefined();
    expect(readSession()).toBeNull();
  });
});

describe("authorized", () => {
  it("refuses without a session rather than making a call that will 401", async () => {
    const call = vi.fn();
    await expect(authorized(call)).rejects.toBeInstanceOf(SessionExpired);
    expect(call).not.toHaveBeenCalled();
  });

  it("makes the call and returns the result", async () => {
    writeSession(WHO);
    const call = vi.fn(async () => "done");
    await expect(authorized(call)).resolves.toBe("done");
    expect(call).toHaveBeenCalledTimes(1);
  });

  it("renews once and retries when the access token has expired", async () => {
    writeSession(WHO);
    const refresh = vi.spyOn(api, "refresh").mockResolvedValue(PAIR);

    const call = vi
      .fn<() => Promise<string>>()
      .mockRejectedValueOnce(new ApiError(401, "expired"))
      .mockResolvedValueOnce("ok");

    await expect(authorized(call)).resolves.toBe("ok");
    expect(refresh).toHaveBeenCalledTimes(1);
    expect(call).toHaveBeenCalledTimes(2);
    // The renewal rotated the *cookies*; the marker is unchanged, and must be,
    // or the page would flicker through a signed-out render on every renewal.
    expect(readSession()).toEqual(WHO);
  });

  it("clears the session when the renewal fails, instead of claiming one that is over", async () => {
    writeSession(WHO);
    vi.spyOn(api, "refresh").mockRejectedValue(new ApiError(401, "no"));
    const call = vi.fn().mockRejectedValue(new ApiError(401, "expired"));

    await expect(authorized(call)).rejects.toBeInstanceOf(SessionExpired);
    expect(readSession()).toBeNull();
  });

  it("renews once for calls that expire together, not once each", async () => {
    // `DocumentViewer` fires two independent `authorized` calls in one `Promise.all`,
    // so an expired access token produces two 401s milliseconds apart. Renewing twice
    // is not merely wasteful: a refresh token is single-use, so the second request
    // presents one the server has just revoked, gets a 401, and `authorized` reads
    // that as a session it cannot renew — signing the user out moments after a
    // renewal that worked.
    writeSession(WHO);
    let resolveRefresh: (v: TokenPair) => void = () => {};
    const inFlight = new Promise<TokenPair>((resolve) => (resolveRefresh = resolve));
    const refresh = vi.spyOn(api, "refresh").mockReturnValue(inFlight);

    const expiringCall = () =>
      vi
        .fn<() => Promise<string>>()
        .mockRejectedValueOnce(new ApiError(401, "expired"))
        .mockResolvedValueOnce("ok");

    const both = Promise.all([authorized(expiringCall()), authorized(expiringCall())]);
    // Let both reach their 401 and ask to renew before the renewal answers.
    await Promise.resolve();
    await Promise.resolve();
    resolveRefresh(PAIR);

    await expect(both).resolves.toEqual(["ok", "ok"]);
    expect(refresh).toHaveBeenCalledTimes(1);
  });

  it("renews again the next time, rather than reusing the first answer", async () => {
    // The other half of sharing one in-flight request: the shared promise has to be
    // released once it settles, or the session would be renewed exactly once per page
    // load and every later expiry would reuse a stale result.
    writeSession(WHO);
    const refresh = vi.spyOn(api, "refresh").mockResolvedValue(PAIR);

    for (let expiry = 0; expiry < 2; expiry++) {
      const call = vi
        .fn<() => Promise<string>>()
        .mockRejectedValueOnce(new ApiError(401, "expired"))
        .mockResolvedValueOnce("ok");
      await expect(authorized(call)).resolves.toBe("ok");
    }

    expect(refresh).toHaveBeenCalledTimes(2);
  });

  it("retries exactly once, never in a loop", async () => {
    // A second 401 after a successful renewal means something else is wrong — a
    // revoked token, an epoch bump — and retrying again would spin.
    writeSession(WHO);
    vi.spyOn(api, "refresh").mockResolvedValue(PAIR);
    const call = vi.fn().mockRejectedValue(new ApiError(401, "expired"));

    await expect(authorized(call)).rejects.toBeInstanceOf(ApiError);
    expect(call).toHaveBeenCalledTimes(2);
  });

  it("rethrows anything that is not a 401, without renewing", async () => {
    // A 403 is an answer about the caller's role, not their token. Renewing on it
    // would spend a refresh and retry a call that will fail identically.
    writeSession(WHO);
    const refresh = vi.spyOn(api, "refresh");
    const forbidden = new ApiError(403, "not your row");
    const call = vi.fn().mockRejectedValue(forbidden);

    await expect(authorized(call)).rejects.toBe(forbidden);
    expect(refresh).not.toHaveBeenCalled();
    expect(call).toHaveBeenCalledTimes(1);
    expect(readSession()).toEqual(WHO);
  });

  it("rethrows a non-ApiError untouched", async () => {
    writeSession(WHO);
    const boom = new TypeError("network down");
    await expect(authorized(vi.fn().mockRejectedValue(boom))).rejects.toBe(boom);
  });
});
