"use client";

import { useState } from "react";

import { RequirementFields } from "@/components/RequirementFields";
import { Button } from "@/components/ui/Button";
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
          // 32×32, which `docs/DESIGN.md` §5 asks of anything destructive — and the
          // one place the meaning palette is borrowed for a control, because
          // refusing a claim and destroying a row are the same red to a reader.
          className="ring-focus mt-1 inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-control text-sm text-ink-muted hover:text-dropped disabled:opacity-30"
        >
          ×
        </button>
      </div>

      {confirmingDelete && (
        <div className="flex flex-wrap items-center gap-2 rounded-control border border-dropped/40 bg-dropped-wash px-2.5 py-2">
          <span className="text-xs text-dropped">
            Delete “{requirement.label}”?{" "}
            {screeningCount === undefined
              ? "Every screening on this job becomes stale and has to be run again."
              : screeningCount === 0
                ? "No screening has run yet, so nothing has to be run again."
                : `${screeningCount} ${screeningCount === 1 ? "screening" : "screenings"} become stale and have to be run again — one model call each.`}
          </span>
          <Button
            variant="danger"
            onClick={() => {
              setConfirmingDelete(false);
              void onDelete();
            }}
          >
            Delete
          </Button>
          <Button variant="ghost" onClick={() => setConfirmingDelete(false)}>
            Cancel
          </Button>
        </div>
      )}

      {dirty && (
        <div className="flex flex-wrap items-center gap-2 pt-0.5">
          <Button
            variant="primary"
            onClick={() => void save()}
            disabled={saving || draft.label.trim() === ""}
          >
            {saving ? "Saving…" : "Save"}
          </Button>
          <Button
            variant="ghost"
            onClick={() => setDraft(toInput(requirement))}
            disabled={saving}
          >
            Discard
          </Button>

          {/* Weight, not hue. These two lines were amber and emerald — `ambiguous`
              and `cited`, the colours reserved for what the system says about a
              *document* — spent here on what an edit will cost. Same category
              error as the ranking's must-have gate, in the same panel. The
              distinction the 2026-08-12 walkthrough valued survives: the costly
              one is set in full ink and the free one is muted, so one still reads
              louder than the other at a glance. */}
          {stalening ? (
            <span className="text-micro font-medium text-ink">
              Changes what the judge was shown — every screening becomes stale and has to be
              run again to rejoin the ranking.
            </span>
          ) : (
            <span className="text-micro text-ink-muted">
              Free — reorders the ranking without re-judging anyone.
            </span>
          )}
        </div>
      )}
    </div>
  );
}
