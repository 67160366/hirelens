"use client";

import type { ApplicationEvent } from "@/lib/api";
import { describeEvent, restsOnEvidence } from "@/lib/applications";

/**
 * The append-only log an application's state is derived from.
 *
 * Rendered rather than hidden because it is the point of the whole design: the
 * state is a projection, and this is the record. Someone told "not proceeding"
 * should be able to see who decided that, when, and what it rested on.
 */
export function ApplicationTimeline({ events }: { events: ApplicationEvent[] }) {
  if (events.length === 0) {
    return <p className="text-xs text-stone-500 dark:text-stone-400">No history yet.</p>;
  }

  return (
    <ol className="space-y-2.5">
      {events.map((event) => (
        <li key={event.id} className="flex gap-2.5 text-xs">
          <span
            aria-hidden
            className={`mt-1 h-1.5 w-1.5 shrink-0 rounded-full ${
              event.actor_id === null
                ? "bg-stone-300 dark:bg-stone-600"
                : "bg-stone-800 dark:bg-stone-200"
            }`}
          />
          <div className="min-w-0 flex-1">
            <p className="text-stone-700 dark:text-stone-200">
              {describeEvent(event)}
              {restsOnEvidence(event) ? (
                // Named because a decision with evidence behind it is a different
                // kind of claim from one without, and the difference should show.
                <span className="ml-1.5 rounded bg-emerald-50 px-1.5 py-0.5 text-[10px] font-medium text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300">
                  cited evidence
                </span>
              ) : null}
            </p>
            {event.reason ? (
              <p className="mt-0.5 text-stone-600 dark:text-stone-400">“{event.reason}”</p>
            ) : null}
            <p className="mt-0.5 text-[11px] text-stone-400 dark:text-stone-500">
              {new Date(event.created_at).toLocaleString()}
            </p>
          </div>
        </li>
      ))}
    </ol>
  );
}
