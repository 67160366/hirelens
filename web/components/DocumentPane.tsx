"use client";

import { createContext, useContext, useEffect, useMemo, useRef, useState } from "react";

import { Card, CardHeader } from "@/components/ui/Card";
import type { EvidenceRef, ExtractedProfile } from "@/lib/api";

/**
 * The source document with every citation highlighted in place.
 *
 * This is the evidence rule (see docs/HANDOFF.md §2) made visible: a claim is
 * only shown at all because its quote was located in this exact text, so the
 * claims and the document can be put side by side and the link between them
 * pointed at directly. It takes a plain list of spans rather than a profile,
 * because a screening's verdicts cite the same text in the same way.
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
 *
 * Exported because the pane no longer collects its own spans: a judgment's
 * citations point into the same text and highlight the same way, so the pane takes
 * a plain list and the caller says where it came from.
 */
export function collectEvidence(profile: ExtractedProfile): EvidenceRef[] {
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

/**
 * What a highlighted run looks like.
 *
 * The **fill** carries meaning — `ambiguous` where the quote appears more than
 * once, `cited` otherwise — and the **ring** says which one you selected. Those are
 * two different questions, so they are two different colours: before this, being
 * selected was the same green a shade stronger, which is a control state wearing a
 * verdict's colour and nearly invisible besides (docs/DESIGN.md §1).
 *
 * The selected run also keeps its wash underneath the swept fill, so the animation
 * paints over a highlight that is already there rather than out of nothing.
 */
function highlightClass(reference: EvidenceRef, isActive: boolean): string {
  const tone = reference.is_ambiguous ? "ambiguous" : "cited";
  const wash = tone === "ambiguous" ? "bg-ambiguous-wash" : "bg-cited-wash";
  if (!isActive) return `${wash} text-inherit`;
  return `${wash} cite-sweep cite-sweep-${tone} text-ink ring-1 ring-accent`;
}

export function DocumentPane({ text, references }: { text: string; references: EvidenceRef[] }) {
  const selection = useEvidenceSelection();
  const activeKey = selection?.activeKey ?? null;
  const marks = useRef(new Map<string, HTMLElement>());

  const segments = useMemo(() => buildSegments(text, references), [text, references]);

  useEffect(() => {
    if (!activeKey) return;
    marks.current.get(activeKey)?.scrollIntoView({ block: "center", behavior: "smooth" });
  }, [activeKey]);

  return (
    // `lg:top-20`, not `top-6`: the application bar is sticky and 56px tall, so a
    // pane pinned 24px from the top slid underneath it and lost its own heading.
    <Card className="lg:sticky lg:top-20">
      <CardHeader
        title="Source document"
        action={
          <p className="text-micro text-ink-faint">
            {activeKey
              ? `${references.length} cited ${references.length === 1 ? "span" : "spans"}`
              : "Select a citation to locate it"}
          </p>
        }
      />

      <div className="max-h-[70vh] overflow-y-auto px-4 py-3">
        {/* Thai has no word spaces, so wrapping needs break-words to avoid
            overflowing the pane on a long unbroken run. */}
        <p className="whitespace-pre-wrap break-words font-mono text-xs leading-7 text-ink-muted">
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
    </Card>
  );
}
