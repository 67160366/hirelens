/**
 * Tests for the theme store.
 *
 * Everything here fails quietly, which is the only reason any of it is worth writing:
 *
 *   * **An explicit choice losing to the operating system.** `resolveTheme` checks the
 *     explicit branch first, and the two agree whenever the reader has not chosen — so
 *     an implementation that read the OS first would look correct on the machine of
 *     anybody who had not touched the control.
 *   * **An unrecognised stored value pinning the reader to light** instead of putting
 *     them back where they were before they ever touched it.
 *   * **A write that does not notify**, which leaves the control rendering the old
 *     choice until something else happens to re-render it — `lib/auth.ts`'s bug in a
 *     new costume.
 *   * **An unsubscribe that leaks**, leaving a dead component subscribed and two
 *     listeners on `window` and the media query per mount.
 *   * **The operating system moving under a reader who has chosen.** The media
 *     listener has to re-read the preference rather than assume it is `system`,
 *     otherwise choosing Light means "light until the OS disagrees".
 *
 * `localStorage`, `window` and `document` are three hand-written stubs rather than
 * jsdom, for the reason `lib/auth.test.ts` gives: `web/` keeps vitest DOM-free and this
 * needed three objects with a handful of methods between them.
 */

import { afterEach, beforeEach, describe, expect, it } from "vitest";

import {
  THEME_BOOT_SCRIPT,
  nextPreference,
  parsePreference,
  readPreference,
  resolveTheme,
  subscribeToTheme,
  syncDocumentTheme,
  systemPrefersDark,
  writePreference,
} from "./theme";

const THEME_KEY = "hirelens.theme";

function fakeStorage() {
  const entries = new Map<string, string>();
  return {
    getItem: (key: string) => entries.get(key) ?? null,
    setItem: (key: string, value: string) => void entries.set(key, value),
    removeItem: (key: string) => void entries.delete(key),
  };
}

/** Just enough `window` for the cross-tab listener and the media query. */
function fakeWindow(prefersDark: boolean) {
  const storageHandlers = new Set<() => void>();
  const mediaHandlers = new Set<() => void>();
  const media = {
    matches: prefersDark,
    addEventListener: (type: string, handler: () => void) => {
      if (type === "change") mediaHandlers.add(handler);
    },
    removeEventListener: (type: string, handler: () => void) => {
      if (type === "change") mediaHandlers.delete(handler);
    },
  };
  return {
    matchMedia: () => media,
    addEventListener: (type: string, handler: () => void) => {
      if (type === "storage") storageHandlers.add(handler);
    },
    removeEventListener: (type: string, handler: () => void) => {
      if (type === "storage") storageHandlers.delete(handler);
    },
    /** What another tab writing to localStorage looks like from in here. */
    fireStorageEvent: () => storageHandlers.forEach((handler) => handler()),
    /** What the operating system changing looks like from in here. */
    setSystemDark: (dark: boolean) => {
      media.matches = dark;
      mediaHandlers.forEach((handler) => handler());
    },
    listenerCount: () => storageHandlers.size + mediaHandlers.size,
  };
}

function fakeDocument() {
  return { documentElement: { dataset: {} as Record<string, string> } };
}

let storage: ReturnType<typeof fakeStorage>;
let win: ReturnType<typeof fakeWindow>;
let doc: ReturnType<typeof fakeDocument>;

function install(prefersDark = false) {
  storage = fakeStorage();
  win = fakeWindow(prefersDark);
  doc = fakeDocument();
  Object.assign(globalThis, {
    localStorage: storage,
    window: win,
    document: doc,
  });
}

beforeEach(() => install());

afterEach(() => {
  Reflect.deleteProperty(globalThis, "localStorage");
  Reflect.deleteProperty(globalThis, "window");
  Reflect.deleteProperty(globalThis, "document");
});

describe("resolving a preference", () => {
  it("follows the operating system when the reader has not chosen", () => {
    expect(resolveTheme("system", true)).toBe("dark");
    expect(resolveTheme("system", false)).toBe("light");
  });

  it("lets an explicit choice outrank the operating system", () => {
    // The half that is invisible in the common case: on a machine set to dark, a
    // reader who clicked Light must get light.
    expect(resolveTheme("light", true)).toBe("light");
    expect(resolveTheme("dark", false)).toBe("dark");
  });
});

describe("cycling", () => {
  it("advances through every preference and returns to the start", () => {
    // The narrow header offers one button rather than three, so this order is the
    // only way a phone reader reaches `dark` at all — a cycle that skipped one, or
    // stopped at the end, would strand them one press short of a theme.
    expect(nextPreference("system")).toBe("light");
    expect(nextPreference("light")).toBe("dark");
    expect(nextPreference("dark")).toBe("system");
  });
});

describe("reading the stored preference", () => {
  it("is system when nothing is stored", () => {
    expect(readPreference()).toBe("system");
  });

  it("returns a value it recognises", () => {
    storage.setItem(THEME_KEY, "dark");
    expect(readPreference()).toBe("dark");
  });

  it("falls back to system rather than light for a value it does not recognise", () => {
    expect(parsePreference("solarized")).toBe("system");
    expect(parsePreference(null)).toBe("system");
    storage.setItem(THEME_KEY, "solarized");
    expect(readPreference()).toBe("system");
  });
});

describe("putting the theme on the document", () => {
  it("resolves through the operating system and writes the attribute", () => {
    install(true);
    expect(syncDocumentTheme()).toBe("dark");
    expect(doc.documentElement.dataset.theme).toBe("dark");
  });

  it("writes what the reader chose, whatever the operating system says", () => {
    install(true);
    writePreference("light");
    expect(doc.documentElement.dataset.theme).toBe("light");
    expect(storage.getItem(THEME_KEY)).toBe("light");
  });

  it("reports no system preference where there is nothing to ask", () => {
    Reflect.deleteProperty(globalThis, "window");
    expect(systemPrefersDark()).toBe(false);
  });
});

describe("subscribing", () => {
  it("wakes a listener when this tab writes", () => {
    let woken = 0;
    const unsubscribe = subscribeToTheme(() => (woken += 1));
    writePreference("dark");
    expect(woken).toBe(1);
    unsubscribe();
  });

  it("stops waking it, and leaves nothing on window, after unsubscribing", () => {
    let woken = 0;
    const unsubscribe = subscribeToTheme(() => (woken += 1));
    expect(win.listenerCount()).toBe(2);
    unsubscribe();
    writePreference("dark");
    win.fireStorageEvent();
    expect(woken).toBe(0);
    expect(win.listenerCount()).toBe(0);
  });

  it("repaints when another tab changes the preference", () => {
    let woken = 0;
    const unsubscribe = subscribeToTheme(() => (woken += 1));
    // Another tab writes the key directly; this tab only learns of it by the event.
    storage.setItem(THEME_KEY, "dark");
    win.fireStorageEvent();
    expect(doc.documentElement.dataset.theme).toBe("dark");
    expect(woken).toBe(1);
    unsubscribe();
  });

  it("follows the operating system while the reader has not chosen", () => {
    const unsubscribe = subscribeToTheme(() => {});
    win.setSystemDark(true);
    expect(doc.documentElement.dataset.theme).toBe("dark");
    unsubscribe();
  });

  it("ignores the operating system once the reader has chosen", () => {
    const unsubscribe = subscribeToTheme(() => {});
    writePreference("light");
    win.setSystemDark(true);
    // The sharp one: a media listener that assumed `system` would repaint here, and
    // "Light" would mean light only until the machine disagreed.
    expect(doc.documentElement.dataset.theme).toBe("light");
    unsubscribe();
  });
});

describe("the boot script", () => {
  it("carries the same storage key the store reads, so the two cannot drift", () => {
    // It is built by interpolation rather than retyped, and this is what says so.
    expect(THEME_BOOT_SCRIPT).toContain(JSON.stringify(THEME_KEY));
  });
});
