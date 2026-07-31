import type { EvidenceRef, MatchKind } from "@/lib/api";

/**
 * How a quote was matched against the source. Surfaced rather than hidden: a
 * "spacing differs" match means PDF extraction mangled the text, which is worth
 * seeing while reviewing.
 */
const MATCH_LABEL: Record<MatchKind, string> = {
  exact: "exact",
  whitespace_collapsed: "spacing differs",
  whitespace_stripped: "spacing removed",
};

/**
 * A citation: the verbatim source text plus where it sits in the document.
 *
 * This component is the product's core claim rendered as UI — nothing the system
 * asserts is shown without one of these next to it.
 */
export function Evidence({ reference }: { reference: EvidenceRef }) {
  return (
    <div className="mt-1 border-l-2 border-emerald-400/70 pl-2.5 dark:border-emerald-500/60">
      <p className="evidence-quote text-stone-600 dark:text-stone-400">
        &ldquo;{reference.quote.replace(/\s+/g, " ").trim()}&rdquo;
      </p>
      <p className="mt-0.5 font-mono text-[10px] tracking-tight text-stone-400 dark:text-stone-500">
        p{reference.page} · chars {reference.char_start}–{reference.char_end} ·{" "}
        {MATCH_LABEL[reference.match_kind]}
        {reference.is_ambiguous && (
          <span
            className="ml-1.5 text-amber-600 dark:text-amber-500"
            title="This text appears more than once in the document, so the citation is not unique."
          >
            · ambiguous
          </span>
        )}
      </p>
    </div>
  );
}

/** A labelled value with its citation underneath. */
export function ClaimRow({
  label,
  value,
  reference,
}: {
  label: string;
  value: string;
  reference: EvidenceRef;
}) {
  return (
    <div className="py-2">
      <p className="text-[11px] font-medium uppercase tracking-wide text-stone-400 dark:text-stone-500">
        {label}
      </p>
      <p className="text-sm font-medium">{value}</p>
      <Evidence reference={reference} />
    </div>
  );
}
