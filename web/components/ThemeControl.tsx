"use client";

import { cn } from "@/lib/cn";
import {
  THEME_PREFERENCES,
  nextPreference,
  useThemePreference,
  type ThemePreference,
} from "@/lib/theme";

/**
 * Which theme to render in — the reader's choice, or the machine's.
 *
 * It exists for two reasons and the second is the one that made it urgent. Readers
 * genuinely want it; and until it existed, **nobody could look at the light theme at
 * all.** `docs/DESIGN.md` requires every screen to be driven at 375 / 768 / 1440 in
 * both themes, the swap was behind `@media (prefers-color-scheme: dark)`, and no
 * instrument driving this app can change an operating-system setting. Two screens had
 * already shipped with half their palette unseen.
 *
 * **Three options, not a two-way toggle.** A toggle has to start somewhere, and
 * whichever way it starts it has silently overridden the machine — "follow the system"
 * is a real answer and it is the default, so it is on screen as one of the three
 * rather than implied by the absence of a choice.
 *
 * `aria-pressed` rather than radio semantics: a radio group owes the reader arrow-key
 * navigation and a roving tabindex, and three buttons that each say whether they are
 * pressed are announced correctly without any of it.
 *
 * **Two shapes, because the header runs out of room.** Measured rather than guessed:
 * the three-up group is 130px, and at 375px that pushed the bar 2px past the viewport
 * and squeezed the primary navigation to **8px** — the four routes were still there
 * and nobody could see one of them. Below `sm` it collapses to a single button showing
 * the mode you are in, which advances on each press; that is 54px and gives the
 * navigation back roughly what it had before this control existed. Hiding it below
 * `sm` was the other option and was refused: a phone reader would have no way to
 * choose, and a control that exists only on a desktop is a control that never gets
 * checked on a phone.
 *
 * The active option is tinted **accent**, exactly like the active navigation item and
 * for the same reason — `docs/DESIGN.md` §1 reserves `cited` / `ambiguous` / `dropped`
 * for what the system says about a document, and which theme you are in is a control
 * state. The pairing is already measured: 5.62:1 on paper, 4.98:1 in the dark theme.
 */
const LABELS: Record<ThemePreference, string> = {
  system: "Auto",
  light: "Light",
  dark: "Dark",
};

const DESCRIPTIONS: Record<ThemePreference, string> = {
  system: "Follow this device's appearance setting",
  light: "Always use the light theme",
  dark: "Always use the dark theme",
};

export function ThemeControl() {
  const { preference, setPreference } = useThemePreference();

  const next = nextPreference(preference);

  return (
    <>
      {/* Narrow: one button, showing where you are and saying where it goes. The
          visible word is the current mode, because that is the question a reader
          actually has; what pressing does is in the accessible name, where a
          three-word label would not fit. */}
      <button
        type="button"
        aria-label={`Theme: ${LABELS[preference]}. Switch to ${LABELS[next]}.`}
        title={DESCRIPTIONS[preference]}
        onClick={() => setPreference(next)}
        className="ring-focus rounded-control border border-line px-2 py-1 text-micro font-medium text-ink-muted transition-colors hover:bg-surface-sunken hover:text-ink sm:hidden"
      >
        {LABELS[preference]}
      </button>

      <div
        role="group"
        aria-label="Theme"
        className="hidden items-center gap-0.5 rounded-control border border-line p-0.5 sm:flex"
      >
        {THEME_PREFERENCES.map((option) => {
          const active = option === preference;
          return (
            <button
              key={option}
              type="button"
              aria-pressed={active}
              title={DESCRIPTIONS[option]}
              onClick={() => setPreference(option)}
              className={cn(
                "ring-focus rounded-control px-2 py-1 text-micro font-medium transition-colors",
                active
                  ? "bg-accent-wash text-accent"
                  : "text-ink-muted hover:bg-surface-sunken hover:text-ink",
              )}
            >
              {LABELS[option]}
            </button>
          );
        })}
      </div>
    </>
  );
}
