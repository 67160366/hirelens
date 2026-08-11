"use client";

import type { RequirementInput, RequirementKind } from "@/lib/api";

/**
 * The five inputs that describe one requirement.
 *
 * Shared by the authoring form and the editor on a job's page so the two cannot
 * drift — they are the same five fields, and only what happens on change differs:
 * one collects a draft, the other PATCHes a row.
 */

const KINDS: RequirementKind[] = ["skill", "experience", "education", "language", "other"];

/**
 * `kind` is carried because the judge is prompted differently per kind — a skill is
 * looked for as a mention, a duration has to be shown by a date range.
 */
const KIND_LABELS: Record<RequirementKind, string> = {
  skill: "Skill",
  experience: "Experience",
  education: "Education",
  language: "Language",
  other: "Other",
};

const field =
  "rounded-md border border-stone-300 bg-white px-2.5 py-1.5 text-sm outline-none focus:border-stone-500 dark:border-stone-700 dark:bg-stone-950";

export function RequirementFields({
  value,
  onChange,
  disabled = false,
}: {
  value: RequirementInput;
  onChange: (next: RequirementInput) => void;
  disabled?: boolean;
}) {
  const patch = (changes: Partial<RequirementInput>) => onChange({ ...value, ...changes });

  return (
    <div className="grid gap-2 sm:grid-cols-[7rem_1fr_1fr_auto_5.5rem]">
      <select
        value={value.kind}
        disabled={disabled}
        onChange={(event) => patch({ kind: event.target.value as RequirementKind })}
        className={field}
        aria-label="Requirement kind"
      >
        {KINDS.map((kind) => (
          <option key={kind} value={kind}>
            {KIND_LABELS[kind]}
          </option>
        ))}
      </select>

      <input
        value={value.label}
        disabled={disabled}
        onChange={(event) => patch({ label: event.target.value })}
        placeholder="What the job asks for"
        aria-label="Requirement label"
        className={field}
      />

      <input
        value={value.detail ?? ""}
        disabled={disabled}
        // An empty box means "no detail", which the API models as null rather than
        // an empty string — `detail: null` is what clears it on a PATCH.
        onChange={(event) => patch({ detail: event.target.value || null })}
        placeholder="Detail (optional)"
        aria-label="Requirement detail"
        className={field}
      />

      <label
        className="flex items-center gap-1.5 px-1 text-xs text-stone-600 dark:text-stone-400"
        title="A hard gate: a candidate missing this ranks below everyone who has them all, however well they score elsewhere."
      >
        <input
          type="checkbox"
          checked={value.must_have}
          disabled={disabled}
          onChange={(event) => patch({ must_have: event.target.checked })}
        />
        Must have
      </label>

      <input
        type="number"
        min={0.1}
        max={100}
        step={0.5}
        value={value.weight}
        disabled={disabled}
        onChange={(event) => patch({ weight: Number(event.target.value) })}
        aria-label="Requirement weight"
        title="How much this counts within a tier. Editing it reorders the ranking without re-running any screening."
        className={field}
      />
    </div>
  );
}
