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
  disabled = false,
}: {
  requirement: Requirement;
  onSave: (patch: RequirementPatch) => Promise<void>;
  onDelete: () => Promise<void>;
  disabled?: boolean;
}) {
  const [draft, setDraft] = useState<RequirementInput>(() => toInput(requirement));
  const [saving, setSaving] = useState(false);

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
          onClick={() => void onDelete()}
          disabled={disabled || saving}
          aria-label={`Delete requirement ${requirement.label}`}
          title="Deleting a requirement changes the question, so every screening becomes stale."
          className="mt-1 px-1.5 text-sm text-stone-400 hover:text-red-600 disabled:opacity-30 dark:hover:text-red-400"
        >
          ×
        </button>
      </div>

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
