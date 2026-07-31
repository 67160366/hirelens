"use client";

import { createContext, useContext, useEffect, useMemo, useRef, useState } from "react";

import type { EvidenceRef, ExtractedProfile } from "@/lib/api";

/**
 * The source document with every citation highlighted in place.
 *
 * This is the evidence rule (see docs/HANDOFF.md §2) made visible: a claim is
 * only shown at all because its quote was located in this exact text, so the
 * profile and the document can be put side by side and the link between them
 * pointed at directly.
 *
 * Offsets index into `document_text` as returned by the API — the verbatim
 * string the backend stored, never a re-parse. Re-parsing could shift every
 * offset and silently move a highlight off its quote.
 */

/** Identifies a span. Two claims citing the same range share one highlight. */
export function spanKey(reference: EvidenceRef): string {
  return `${reference.char_start}-${reference.char_end}`;
}

interface Selection {
  activeKey: string | null;
  select: (reference: EvidenceRef) => void;
}

const SelectionContext = createContext<Selection | null>(null);

/**
 * Provides click-to-locate. Mounted only when there is document text to locate
 * quotes in, so `useEvidenceSelection` returning null is the honest signal that
 * a citation cannot be pointed anywhere and must not look clickable.
 */
export function EvidenceSelectionProvider({ children }: { children: React.ReactNode }) {
  const [activeKey, setActiveKey] = useState<string | null>(null);

  const value = useMemo<Selection>(
    () => ({ activeKey, select: (reference) => setActiveKey(spanKey(reference)) }),
    [activeKey],
  );

  return <SelectionContext.Provider value={value}>{children}</SelectionContext.Provider>;
}

export function useEvidenceSelection(): Selection | null {
  return useContext(SelectionContext);
}

/**
 * Every citation in a profile.
 *
 * Dropped claims are deliberately absent: their quote was not found in the
 * document, so there is no span to highlight. Including them would present an
 * unverified claim as sourced, which is the one thing this project must not do.
 */
function collectEvidence(profile: ExtractedProfile): EvidenceRef[] {
  const references: EvidenceRef[] = [];
  const add = (reference: EvidenceRef | null | undefined) => {
    if (reference) references.push(reference);
  };

  add(profile.full_name?.evidence);
  add(profile.headline?.evidence);
  add(profile.years_experience?.evidence);
  add(profile.seniority_evidence);
  for (const skill of profile.skills) add(skill.evidence);
  for (const role of profile.experiences) add(role.evidence);
  for (const entry of profile.education) add(entry.evidence);

  return references;
}

interface Segment {
  text: string;
  reference: EvidenceRef | null;
}

/**
 * Slice the document into alternating plain and cited runs.
 *
 * Overlapping citations keep the earliest, longest span and skip the rest —
 * nested `<mark>` elements would be unreadable, and an overlap means two claims
 * drew on the same sentence rather than that either is wrong.
 */
function buildSegments(text: string, references: EvidenceRef[]): Segment[] {
  const ordered = references
    .filter(
      (reference) =>
        reference.char_start >= 0 &&
        reference.char_end > reference.char_start &&
        reference.char_end <= text.length,
    )
    .sort((a, b) => a.char_start - b.char_start || b.char_end - a.char_end);

  const segments: Segment[] = [];
  let cursor = 0;

  for (const reference of ordered) {
    if (reference.char_start < cursor) continue;
    if (reference.char_start > cursor) {
      segments.push({ text: text.slice(cursor, reference.char_start), reference: null });
    }
    segments.push({ text: text.slice(reference.char_start, reference.char_end), reference });
    cursor = reference.char_end;
  }

  if (cursor < text.length) segments.push({ text: text.slice(cursor), reference: null });
  return segments;
}

function highlightClass(reference: EvidenceRef, isActive: boolean): string {
  // Amber for ambiguous, matching how Evidence.tsx flags a quote that appears
  // more than once. The citation is reported as unresolved, not guessed at.
  if (reference.is_ambiguous) {
    return isActive
      ? "bg-amber-300 text-stone-900 ring-1 ring-amber-500 dark:bg-amber-400/50 dark:text-amber-50"
      : "bg-amber-100/80 text-inherit dark:bg-amber-500/15";
  }
  return isActive
    ? "bg-emerald-300 text-stone-900 ring-1 ring-emerald-600 dark:bg-emerald-400/50 dark:text-emerald-50"
    : "bg-emerald-100/80 text-inherit dark:bg-emerald-500/15";
}

export function DocumentPane({
  text,
  profile,
}: {
  text: string;
  profile: ExtractedProfile | null;
}) {
  const selection = useEvidenceSelection();
  const activeKey = selection?.activeKey ?? null;
  const marks = useRef(new Map<string, HTMLElement>());

  const references = useMemo(() => (profile ? collectEvidence(profile) : []), [profile]);
  const segments = useMemo(() => buildSegments(text, references), [text, references]);

  useEffect(() => {
    if (!activeKey) return;
    marks.current.get(activeKey)?.scrollIntoView({ block: "center", behavior: "smooth" });
  }, [activeKey]);

  return (
    <section className="rounded-lg border border-stone-200 bg-white dark:border-stone-800 dark:bg-stone-900 lg:sticky lg:top-6">
      <header className="flex items-baseline justify-between gap-3 border-b border-stone-200 px-4 py-2.5 dark:border-stone-800">
        <h3 className="text-sm font-semibold">Source document</h3>
        <p className="text-[11px] text-stone-400 dark:text-stone-500">
          {activeKey
            ? `${references.length} cited ${references.length === 1 ? "span" : "spans"}`
            : "Select a citation to locate it"}
        </p>
      </header>

      <div className="max-h-[70vh] overflow-y-auto px-4 py-3">
        {/* Thai has no word spaces, so wrapping needs break-words to avoid
            overflowing the pane on a long unbroken run. */}
        <p className="whitespace-pre-wrap break-words font-mono text-[12.5px] leading-7 text-stone-700 dark:text-stone-300">
          {segments.map((segment, index) => {
            const { reference } = segment;
            if (!reference) return <span key={index}>{segment.text}</span>;

            const key = spanKey(reference);
            return (
              <mark
                key={index}
                ref={(element) => {
                  if (element) marks.current.set(key, element);
                  else marks.current.delete(key);
                }}
                className={`rounded-[2px] px-px ${highlightClass(reference, key === activeKey)}`}
              >
                {segment.text}
              </mark>
            );
          })}
        </p>
      </div>
    </section>
  );
}
