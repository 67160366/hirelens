"use client";

import { Badge } from "@/components/ui/Badge";
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
    return <p className="text-xs text-ink-muted">No history yet.</p>;
  }

  return (
    <ol className="space-y-2.5">
      {events.map((event) => (
        <li key={event.id} className="flex gap-2.5 text-xs">
          <span
            aria-hidden
            className={`mt-1 h-1.5 w-1.5 shrink-0 rounded-full ${
              // The system's own moves are dimmer than a person's, which is the
              // same distinction `psql` shows as a null `actor_id`.
              event.actor_id === null ? "bg-line-strong" : "bg-ink"
            }`}
          />
          <div className="min-w-0 flex-1">
            <p className="text-ink">
              {describeEvent(event)}
              {restsOnEvidence(event) ? (
                // Named because a decision with evidence behind it is a different
                // kind of claim from one without, and the difference should show.
                // `cited`, and this is the one badge on this screen that keeps a
                // meaning colour: it says a decision rests on a quote the
                // application located in a document, which is exactly what the
                // token is reserved for.
                <Badge tone="cited" className="ml-1.5 align-middle">
                  cited evidence
                </Badge>
              ) : null}
            </p>
            {event.reason ? <p className="mt-0.5 text-ink-muted">“{event.reason}”</p> : null}
            <p className="mt-0.5 text-micro tabular-nums text-ink-faint">
              {new Date(event.created_at).toLocaleString()}
            </p>
          </div>
        </li>
      ))}
    </ol>
  );
}
