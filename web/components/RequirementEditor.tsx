"use client";

import { useState } from "react";

import { RequirementFields } from "@/components/RequirementFields";
import type { Requirement, RequirementInput, RequirementPatch } from "@/lib/api";
import { makesScreeningsStale } from "@/lib/screening";

/**
 * One saved requirement, editable.
 *
 * Edits are staged behind a Save button rather than written on every keystroke,
 * because what a change *costs* depends on which field moved and the user deserves
 * to be told before it happens: `must_have` and `weight` reorder the ranking for
 * free, while `kind`, `label` and `detail` are what the judge was shown and
 * invalidate every screening that already ran.
 */

function toInput(requirement: Requirement): RequirementInput {
  return {
    kind: requirement.kind,
    label: requirement.label,
    detail: requirement.detail,
    must_have: requirement.must_have,
    weight: requirement.weight,
  };
}

/** Only the fields that actually moved, which is what `exclude_unset` means to the API. */
function changedFields(saved: Requirement, draft: RequirementInput): RequirementPatch {
  const patch: RequirementPatch = {};
  if (draft.kind !== saved.kind) patch.kind = draft.kind;
  if (draft.label !== saved.label) patch.label = draft.label;
  if (draft.detail !== saved.detail) patch.detail = draft.detail;
  if (draft.must_have !== saved.must_have) patch.must_have = draft.must_have;
  if (draft.weight !== saved.weight) patch.weight = draft.weight;
  return patch;
}

export function RequirementEditor({
  requirement,
  onSave,
  onDelete,
  screeningCount,
  disabled = false,
}: {
  requirement: Requirement;
  onSave: (patch: RequirementPatch) => Promise<void>;
  onDelete: () => Promise<void>;
  /** Completed screenings on this job, so the confirmation can name what the delete
   *  actually costs instead of gesturing at it. Omitted where the caller does not
   *  know — the sentence then states the consequence without a number rather than
   *  guessing one. */
  screeningCount?: number;
  disabled?: boolean;
}) {
  const [draft, setDraft] = useState<RequirementInput>(() => toInput(requirement));
  const [saving, setSaving] = useState(false);
  /** A delete is one click and irreversible, and it invalidates every screening on
   *  the job — while the far cheaper *edit* beside it is staged behind Save with a
   *  warning. The cost gradient was inverted; this rights it. */
  const [confirmingDelete, setConfirmingDelete] = useState(false);

  const patch = changedFields(requirement, draft);
  const dirty = Object.keys(patch).length > 0;
  const stalening = makesScreeningsStale(patch);

  async function save() {
    setSaving(true);
    try {
      await onSave(patch);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="space-y-1.5 px-4 py-3">
      <div className="flex items-start gap-2">
        <div className="flex-1">
          <RequirementFields value={draft} onChange={setDraft} disabled={disabled || saving} />
        </div>
        <button
          type="button"
          onClick={() => setConfirmingDelete(true)}
          disabled={disabled || saving || confirmingDelete}
          aria-label={`Delete requirement ${requirement.label}`}
          title="Deleting a requirement changes the question, so every screening becomes stale."
          className="mt-1 inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-md text-sm text-stone-500 hover:text-red-600 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-red-500/40 disabled:opacity-30 dark:text-stone-400 dark:hover:text-red-400"
        >
          ×
        </button>
      </div>

      {confirmingDelete && (
        <div className="flex flex-wrap items-center gap-2 rounded-md border border-red-300 bg-red-50 px-2.5 py-2 dark:border-red-900/60 dark:bg-red-950/30">
          <span className="text-xs text-red-800 dark:text-red-300">
            Delete “{requirement.label}”?{" "}
            {screeningCount === undefined
              ? "Every screening on this job becomes stale and has to be run again."
              : screeningCount === 0
                ? "No screening has run yet, so nothing has to be run again."
                : `${screeningCount} ${screeningCount === 1 ? "screening" : "screenings"} become stale and have to be run again — one model call each.`}
          </span>
          <button
            type="button"
            onClick={() => {
              setConfirmingDelete(false);
              void onDelete();
            }}
            className="rounded-md bg-red-700 px-2.5 py-1 text-xs font-medium text-white dark:bg-red-600"
          >
            Delete
          </button>
          <button
            type="button"
            onClick={() => setConfirmingDelete(false)}
            className="text-xs text-stone-600 underline-offset-2 hover:underline dark:text-stone-400"
          >
            Cancel
          </button>
        </div>
      )}

      {dirty && (
        <div className="flex flex-wrap items-center gap-2 pt-0.5">
          <button
            type="button"
            onClick={() => void save()}
            disabled={saving || draft.label.trim() === ""}
            className="rounded-md bg-stone-900 px-2.5 py-1 text-xs font-medium text-white disabled:opacity-50 dark:bg-stone-100 dark:text-stone-900"
          >
            {saving ? "Saving…" : "Save"}
          </button>
          <button
            type="button"
            onClick={() => setDraft(toInput(requirement))}
            disabled={saving}
            className="text-xs text-stone-500 underline-offset-2 hover:underline dark:text-stone-400"
          >
            Discard
          </button>

          {stalening ? (
            <span className="text-[11px] text-amber-700 dark:text-amber-500">
              Changes what the judge was shown — every screening becomes stale and has to
              be run again to rejoin the ranking.
            </span>
          ) : (
            <span className="text-[11px] text-emerald-700 dark:text-emerald-500">
              Free — reorders the ranking without re-judging anyone.
            </span>
          )}
        </div>
      )}
    </div>
  );
}
