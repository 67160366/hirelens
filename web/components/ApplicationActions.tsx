"use client";

import { useState } from "react";

import type { Application, ApplicationState, Role } from "@/lib/api";
import { availableMoves } from "@/lib/applications";

/**
 * The moves this viewer may make on one application.
 *
 * A move the server will not allow is shown **disabled with the reason**, not
 * hidden: a missing button is indistinguishable from a bug, while a disabled one
 * that says "screen this candidate first, so the decision rests on cited evidence"
 * is the thing that teaches somebody the rule.
 *
 * The rules themselves live on the server. This offers buttons; it does not decide,
 * and when the two disagree the 409 wins and its sentence is what gets shown.
 */
export function ApplicationActions({
  application,
  viewer,
  jobOwnerId,
  busy,
  onMove,
}: {
  application: Application;
  viewer: { id: string; role: Role };
  jobOwnerId: string | null;
  busy: boolean;
  onMove: (to: ApplicationState, reason?: string) => void;
}) {
  const [reasonFor, setReasonFor] = useState<ApplicationState | null>(null);
  const [reason, setReason] = useState("");

  const moves = availableMoves(application, viewer, jobOwnerId);
  if (moves.length === 0) return null;

  if (reasonFor) {
    return (
      <form
        className="flex flex-wrap items-start gap-2"
        onSubmit={(event) => {
          event.preventDefault();
          onMove(reasonFor, reason);
          setReasonFor(null);
          setReason("");
        }}
      >
        <label className="flex-1 text-xs">
          <span className="mb-1 block text-stone-600 dark:text-stone-400">
            Why? The applicant is told, and it is kept in the record.
          </span>
          <input
            value={reason}
            onChange={(event) => setReason(event.target.value)}
            autoFocus
            required
            className="w-full rounded-md border border-stone-300 px-2 py-1.5 text-xs dark:border-stone-700 dark:bg-stone-950"
          />
        </label>
        <div className="flex gap-2 self-end">
          <button
            type="submit"
            disabled={busy || reason.trim().length === 0}
            className="rounded-md bg-stone-900 px-3 py-1.5 text-xs font-medium text-white disabled:opacity-50 dark:bg-stone-100 dark:text-stone-900"
          >
            Confirm
          </button>
          <button
            type="button"
            onClick={() => {
              setReasonFor(null);
              setReason("");
            }}
            className="rounded-md border border-stone-300 px-3 py-1.5 text-xs dark:border-stone-700"
          >
            Cancel
          </button>
        </div>
      </form>
    );
  }

  return (
    <div className="flex flex-wrap items-center gap-2">
      {moves.map((move) => (
        <span key={move.to} className="inline-flex items-center gap-1.5">
          <button
            type="button"
            disabled={busy || Boolean(move.blockedBecause)}
            title={move.blockedBecause}
            onClick={() =>
              move.needsReason ? setReasonFor(move.to) : onMove(move.to)
            }
            className="rounded-md border border-stone-300 px-2.5 py-1 text-xs font-medium hover:bg-stone-50 disabled:cursor-not-allowed disabled:opacity-40 dark:border-stone-700 dark:hover:bg-stone-800"
          >
            {move.label}
          </button>
          {move.blockedBecause ? (
            <span className="text-[11px] text-stone-500 dark:text-stone-400">
              {move.blockedBecause}
            </span>
          ) : null}
        </span>
      ))}
    </div>
  );
}
