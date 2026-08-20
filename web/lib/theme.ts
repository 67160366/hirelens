"use client";

/**
 * Which theme the reader is looking at, and who decided.
 *
 * `docs/DESIGN.md` says both themes stay and that "a screen is not done until it has
 * been driven at 375 / 768 / 1440 in **both** themes". Until this module existed that
 * bar could not be met: the dark tokens lived behind
 * `@media (prefers-color-scheme: dark)`, so the only way to see the other half of the
 * palette was to change an operating-system setting — which no instrument driving this
 * app can do. A screen nobody can look at is a screen nobody can check, and two of them
 * had already shipped that way.
 *
 * So the swap is driven by an attribute on `<html>` instead, and this module owns it.
 * Three preferences, not two: **system** follows the OS and is the default, while
 * **light** and **dark** are a choice the reader made and outrank it.
 *
 * **The preference is an external store, the same shape as `lib/auth.ts`.**
 * `CLAUDE.md` records that `lib/auth.ts` is the only module touching `localStorage`;
 * that rule is about the *session* being one store rather than two copies, and the
 * honest generalisation of it is the one this module obeys: **anything living in
 * `localStorage` is exposed through `useSyncExternalStore` and never copied into
 * component state.** Two tabs then agree about the theme for the same reason they
 * already agree about who is signed in.
 *
 * **Nothing here runs in an effect.** The attribute is written by the three events
 * that can change it — a click, another tab, the OS — rather than by a render
 * reacting to them afterwards, which is what keeps a paint from ever showing the
 * previous theme. The first paint of all is handled by `THEME_BOOT_SCRIPT` below.
 */

import { useSyncExternalStore } from "react";

const THEME_KEY = "hirelens.theme";

const DARK_QUERY = "(prefers-color-scheme: dark)";

/** What the reader asked for. `system` is the default and defers to the OS. */
export type ThemePreference = "system" | "light" | "dark";

/** What is actually on screen once the preference has been resolved. */
export type Theme = "light" | "dark";

/** The order the control renders in. */
export const THEME_PREFERENCES: readonly ThemePreference[] = [
  "system",
  "light",
  "dark",
] as const;

/**
 * The next preference in the cycle, for the narrow header where three buttons do not
 * fit. It lives here rather than in the component because the order is the order
 * `THEME_PREFERENCES` declares, and two places deciding it is how they come to
 * disagree.
 */
export function nextPreference(preference: ThemePreference): ThemePreference {
  const at = THEME_PREFERENCES.indexOf(preference);
  return THEME_PREFERENCES[(at + 1) % THEME_PREFERENCES.length] ?? "system";
}

/**
 * Resolve a preference against the operating system.
 *
 * The explicit branch comes first on purpose: an OS set to dark must not override a
 * reader who has just clicked Light. That inversion is invisible in the default case,
 * because the two agree whenever the reader has not chosen — which is most of the time,
 * and exactly why it is worth pinning.
 */
export function resolveTheme(
  preference: ThemePreference,
  systemIsDark: boolean,
): Theme {
  if (preference === "light" || preference === "dark") return preference;
  return systemIsDark ? "dark" : "light";
}

/**
 * A stored value this version does not recognise falls back to **system**, not to
 * light. Anything else pins the reader to one theme because of a stored string they
 * cannot see and did not write, where following the OS is the state they were in
 * before they ever touched the control.
 */
export function parsePreference(raw: string | null): ThemePreference {
  return raw === "light" || raw === "dark" || raw === "system" ? raw : "system";
}

/** Does the operating system ask for dark? False anywhere there is nothing to ask. */
export function systemPrefersDark(): boolean {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function")
    return false;
  return window.matchMedia(DARK_QUERY).matches;
}

// --- the store -------------------------------------------------------------

type Listener = () => void;

const listeners = new Set<Listener>();

function emit(): void {
  for (const listener of listeners) listener();
}

/** What this tab believes the reader asked for. */
export function readPreference(): ThemePreference {
  if (typeof localStorage === "undefined") return "system";
  return parsePreference(localStorage.getItem(THEME_KEY));
}

/**
 * Put the resolved theme on `<html>`, where the CSS reads it.
 *
 * Exported because it is the whole mechanism, and called from the event handlers
 * rather than from a render: writing the attribute during render would be a side
 * effect in the wrong place, and writing it in an effect would let one frame paint in
 * the old theme first.
 */
export function syncDocumentTheme(): Theme {
  const theme = resolveTheme(readPreference(), systemPrefersDark());
  if (typeof document !== "undefined")
    document.documentElement.dataset.theme = theme;
  return theme;
}

/** Record the choice, repaint, and wake everything reading it. */
export function writePreference(preference: ThemePreference): void {
  if (typeof localStorage !== "undefined")
    localStorage.setItem(THEME_KEY, preference);
  syncDocumentTheme();
  emit();
}

/**
 * Register interest in the preference.
 *
 * Three sources, and each covers a case the others cannot see: the listener set is
 * this tab's own writes, the `storage` event is every *other* tab's, and the media
 * query is the operating system changing under all of them. The last one matters only
 * while the preference is `system`, and `syncDocumentTheme` re-reads the preference
 * rather than assuming — so a reader on `light` sees nothing happen when the OS flips,
 * which is what choosing `light` meant.
 */
export function subscribeToTheme(listener: Listener): () => void {
  listeners.add(listener);

  const wake = () => {
    syncDocumentTheme();
    listener();
  };

  const media =
    typeof window !== "undefined" && typeof window.matchMedia === "function"
      ? window.matchMedia(DARK_QUERY)
      : null;

  if (typeof window !== "undefined") window.addEventListener("storage", wake);
  media?.addEventListener("change", wake);

  return () => {
    listeners.delete(listener);
    if (typeof window !== "undefined")
      window.removeEventListener("storage", wake);
    media?.removeEventListener("change", wake);
  };
}

/** There is no stored preference during SSR, because there is no storage to read. */
function systemOnServer(): ThemePreference {
  return "system";
}

/**
 * The reader's preference, and a way to change it.
 *
 * Only the *preference* is returned, never the resolved theme: the resolved value
 * depends on `matchMedia`, which the server cannot answer, so rendering from it would
 * make the markup disagree with itself at hydration. The document already carries the
 * resolved theme as an attribute, which is where CSS wants it and where React does
 * not.
 */
export function useThemePreference(): {
  preference: ThemePreference;
  setPreference: (preference: ThemePreference) => void;
} {
  const preference = useSyncExternalStore(
    subscribeToTheme,
    readPreference,
    systemOnServer,
  );
  return { preference, setPreference: writePreference };
}

/**
 * The first paint, before React exists.
 *
 * Without this the page paints light, hydrates, and flips — a flash of the wrong theme
 * on every navigation for anybody who chose dark. It is built by interpolating the
 * constants above rather than retyped as a literal, so the storage key and the media
 * query cannot drift apart from the module that owns them.
 *
 * Deliberately tiny and total: any failure at all leaves `light`, which is a readable
 * page rather than an unstyled one.
 */
export const THEME_BOOT_SCRIPT = `(function(){try{var p=localStorage.getItem(${JSON.stringify(
  THEME_KEY,
)});if(p!=="light"&&p!=="dark")p=window.matchMedia(${JSON.stringify(
  DARK_QUERY,
)}).matches?"dark":"light";document.documentElement.dataset.theme=p}catch(e){document.documentElement.dataset.theme="light"}})()`;
