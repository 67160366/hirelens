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
          <span className="mb-1 block text-ink-muted">
            Why? The applicant is told, and it is kept in the record.
          </span>
          <input
            value={reason}
            onChange={(event) => setReason(event.target.value)}
            autoFocus
            required
            className="field py-1.5 text-xs"
          />
        </label>
        <div className="flex gap-2 self-end">
          <button
            type="submit"
            disabled={busy || reason.trim().length === 0}
            className="btn btn-primary ring-focus"
          >
            Confirm
          </button>
          <button
            type="button"
            onClick={() => {
              setReasonFor(null);
              setReason("");
            }}
            className="btn btn-secondary ring-focus"
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
            onClick={() => (move.needsReason ? setReasonFor(move.to) : onMove(move.to))}
            className="btn btn-secondary ring-focus disabled:cursor-not-allowed disabled:opacity-40"
          >
            {move.label}
          </button>
          {move.blockedBecause ? (
            <span className="text-micro text-ink-muted">{move.blockedBecause}</span>
          ) : null}
        </span>
      ))}
    </div>
  );
}
